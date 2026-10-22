from decimal import Decimal as D
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import serializers as s
from core.models import User, Account, Entry, Plan, Episode, Delivery, Quote, Minute, SystemState, Audit
from core.common import BusinessError
from core.ledger import get_account, initialize, post_entry, require_initialized, effective_payloads
from core.serializers import PlanSerializer, SettingsSerializer
from core.plans import evaluate
from core.auth_views import AppAdmin

def account_data(a):
    q=Quote.objects.order_by('-source_at','-pk').first()
    value=q.price*a.shares if q else None
    floating=value-a.cost_basis if value is not None else None
    return {'budget':str(a.budget),'cash':str(a.cash),'shares':a.shares,'cost_basis':str(a.cost_basis),'unit_cost':str(a.cost_basis/a.shares) if a.shares else None,'realized':str(a.realized),'initialized_at':a.initialized_at,'initial_cash':str(a.initial_cash),'initial_shares':a.initial_shares,'initial_cost':str(a.initial_cost),'market_value':str(value) if value is not None else None,'floating':str(floating) if floating is not None else None,'total_profit':str(a.realized+floating) if floating is not None else None}

def entry_data(e,replacements=None):
    return {'id':e.pk,'kind':e.kind,'payload':e.payload,'reason':e.reason,'corrects':e.corrects_id,'plan':e.plan_id,'created_at':e.created_at,'corrected':e.pk in (replacements or {}),'effective_payload':(replacements or {}).get(e.pk)}

def plan_data(p,account=None,user=None):
    d={field:getattr(p,field) for field in ['id','side','direction','target_price','target_profit','amount','quantity','sell_all','status','version']}
    for key in ['target_price','target_profit','amount']:
        if d[key] is not None: d[key]=str(d[key])
    q=Quote.objects.order_by('-source_at').first()
    if account and user:
        d['evaluation']=evaluate(p,account,q.price if q else None,user)
    return d

class AccountView(APIView):
    def get(self,request):
        return Response(account_data(get_account(request.user)))
    def patch(self,request):
        field=s.DecimalField(max_digits=18,decimal_places=2,min_value=0)
        value=field.run_validation(request.data.get('budget'))
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            a=get_account(request.user);a.budget=value;a.save(update_fields=['budget'])
            Audit.objects.create(actor=request.user,action='change_budget',object_id=str(a.pk))
        return Response(account_data(a))

class InitializeView(APIView):
    def post(self,request):
        return Response(account_data(initialize(request.user,request.data)),status=201)

class EntriesView(APIView):
    def get(self,request):
        try: page=max(1,int(request.query_params.get('page',1)))
        except (ValueError,TypeError): raise BusinessError('页码无效')
        qs=Entry.objects.filter(user=request.user).order_by('-id')
        rows=list(qs[(page-1)*20:page*20])
        replacements=effective_payloads(list(Entry.objects.filter(user=request.user,kind='CORRECTION').order_by('id')))
        return Response({'count':qs.count(),'results':[entry_data(e,replacements) for e in rows]})
    def post(self,request):
        row,created=post_entry(request.user,request.data,request.headers.get('Idempotency-Key'))
        return Response(entry_data(row),status=201 if created else 200)

class CashView(APIView):
    def post(self,request):
        row,created=post_entry(request.user,request.data,request.headers.get('Idempotency-Key'),kind='CASH')
        return Response(entry_data(row),status=201 if created else 200)

class CorrectView(APIView):
    def post(self,request,pk):
        # Resolve ownership before validating body or initialization status.
        get_object_or_404(Entry,user=request.user,pk=pk,kind='TRADE')
        row,created=post_entry(request.user,request.data,request.headers.get('Idempotency-Key'),kind='CORRECTION',corrects_id=pk)
        return Response(entry_data(row),status=201 if created else 200)

class PlansView(APIView):
    def get(self,request):
        a=get_account(request.user)
        return Response([plan_data(p,a,request.user) for p in Plan.objects.filter(user=request.user).order_by('-id')[:100]])
    def post(self,request):
        serializer=PlanSerializer(data=request.data);serializer.is_valid(raise_exception=True)
        d=serializer.validated_data
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            require_initialized(get_account(request.user))
            if Plan.objects.filter(user=request.user,side=d['side'],status='ACTIVE').exists():
                raise BusinessError('每个方向只能保留一条有效计划，请编辑已有计划')
            p=Plan.objects.create(user=request.user,**d)
            Audit.objects.create(actor=request.user,action='create_plan',object_id=str(p.pk))
        return Response(plan_data(p),status=201)

class PlanDetailView(APIView):
    def patch(self,request,pk):
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            p=get_object_or_404(Plan.objects.select_for_update(),user=request.user,pk=pk,status='ACTIVE')
            raw={k:getattr(p,k) for k in PlanSerializer().fields}
            raw.update(request.data)
            if raw.get('side')!=p.side: raise BusinessError('不能改变计划方向，请取消后新建')
            serializer=PlanSerializer(data=raw);serializer.is_valid(raise_exception=True)
            for k,v in serializer.validated_data.items():setattr(p,k,v)
            p.version+=1;p.condition_met=False;p.save()
            Episode.objects.filter(plan=p,status__in=['OPEN','UNKNOWN']).update(status='CLOSED')
            Audit.objects.create(actor=request.user,action='edit_plan',object_id=str(p.pk))
        return Response(plan_data(p))

class CancelPlanView(APIView):
    def post(self,request,pk):
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            p=get_object_or_404(Plan.objects.select_for_update(),user=request.user,pk=pk)
            if p.status=='ACTIVE':
                p.status='CANCELLED';p.save(update_fields=['status','updated_at'])
                Episode.objects.filter(plan=p,status__in=['OPEN','UNKNOWN']).update(status='CLOSED')
        return Response(plan_data(p))

class EpisodesView(APIView):
    def get(self,request):
        return Response([{'id':e.pk,'plan':e.plan_id,'version':e.version,'side':e.plan.side,'status':e.status,'context':e.context,'sent_count':e.sent_count,'created_at':e.created_at} for e in Episode.objects.filter(plan__user=request.user).select_related('plan').order_by('-id')[:30]])

class IgnoreView(APIView):
    def post(self,request,pk):
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            e=get_object_or_404(Episode.objects.select_for_update(),plan__user=request.user,pk=pk)
            if e.status in ['OPEN','UNKNOWN']:e.status='IGNORED';e.save(update_fields=['status'])
        return Response({'detail':'本轮提醒已停止'})

class SettingsView(APIView):
    def get(self,request):
        u=request.user
        return Response({**{k:str(getattr(u,k)) if getattr(u,k) is not None else '' for k in ['fee_rate','fee_minimum','fee_extra']},'reminder_minutes':u.reminder_minutes,'reminder_max':u.reminder_max,'token_bound':bool(u.token_encrypted)})
    def patch(self,request):
        from core.push import encrypt_token
        serializer=SettingsSerializer(data=request.data);serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            u=User.objects.select_for_update().get(pk=request.user.pk)
            for k,v in serializer.validated_data.items():
                if k=='push_token':u.token_encrypted=encrypt_token(v) if v else ''
                else:setattr(u,k,v)
            u.save()
        request.user=u
        return self.get(request)

class DeliveryView(APIView):
    def get(self,request):
        labels={'SENDING':'发送中','SENT':'服务已接收','FAILED':'发送失败','UNKNOWN':'结果未确认','SKIPPED':'已作废'}
        return Response([{'id':d.pk,'status':d.status,'label':labels.get(d.status,d.status),'detail':d.detail,'created_at':d.created_at} for d in Delivery.objects.filter(user=request.user).order_by('-id')[:30]])

class TestPushView(APIView):
    def post(self,request):
        from core.push import send_test
        return Response(send_test(request.user))

class MarketView(APIView):
    def get(self,request):
        from core.market import market_data
        return Response(market_data())

class SystemView(APIView):
    permission_classes=[AppAdmin]
    def get(self,request):
        from core.monitor import worker_ok
        return Response({'worker_ok':worker_ok(),'market':SystemState.objects.filter(pk='market').values_list('value',flat=True).first() or {},'backup':SystemState.objects.filter(pk='backup').values_list('value',flat=True).first() or {}})
