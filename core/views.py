from decimal import Decimal as D
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import serializers as s
from core.models import User, Account, Entry, Plan, Episode, GroupEpisode, Delivery, Quote, Minute, SystemState, Audit, PublicAlert
from core.common import BusinessError
from core.ledger import get_account, initialize, post_entry, require_initialized, effective_payloads, cash_round, position_snapshot, sale_cost, holding_history
from core.serializers import PlanSerializer, SettingsSerializer, AlertSerializer, BuyPreviewSerializer, SellPreviewSerializer, SellBatchPreviewSerializer
from core.plans import evaluate, estimated_fee, affordable_quantity, minimum_sale_price
from core.auth_views import AppAdmin

def account_data(a):
    q=Quote.objects.order_by('-source_at','-pk').first()
    value=q.price*a.shares if q else None
    floating=value-a.cost_basis if value is not None else None
    return {'budget':str(a.budget),'cash':str(a.cash),'shares':a.shares,'cost_basis':str(a.cost_basis),'unit_cost':str(a.cost_basis/a.shares) if a.shares else None,'realized':str(a.realized),'initialized_at':a.initialized_at,'initial_cash':str(a.initial_cash),'initial_shares':a.initial_shares,'initial_cost':str(a.initial_cost),'market_value':str(value) if value is not None else None,'floating':str(floating) if floating is not None else None,'total_profit':str(a.realized+floating) if floating is not None else None,'reference_quote':{'price':str(q.price),'source_at':q.source_at} if q else None}

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

def preview_account(user):
    account = Account.objects.filter(user=user).first()
    if not account:
        raise BusinessError('请先初始化账本')
    require_initialized(account)
    return account


def preview_fee_for(user, manual_fee):
    if manual_fee is not None:
        return lambda _: manual_fee
    if estimated_fee(user, D(0)) is None:
        raise BusinessError('请在设置中补齐券商费用参数，或手动输入预计手续费')
    return lambda gross: estimated_fee(user, gross)


def validate_sale_quantity(quantity, shares):
    if quantity > shares:
        raise BusinessError('卖出份额不能超过当前持仓')
    if quantity % 100 and quantity != shares:
        raise BusinessError('不足一手的余份须一次全部卖出')


class TradePreviewView(APIView):
    serializer_class = BuyPreviewSerializer
    side = 'BUY'

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = preview_account(request.user)
        data = serializer.validated_data
        price = data['price']
        fee = data.get('fee')
        fee_estimated = fee is None
        fee_for = preview_fee_for(request.user, fee)

        quantity = data.get('quantity')
        if quantity is None:
            quantity = affordable_quantity(price, data['budget'], fee_for, max_quantity=100000000)
            if quantity == 0:
                raise BusinessError('预算扣除手续费后不足买入 100 份')
        gross = cash_round(price * quantity)
        fee = fee_for(gross)
        if fee > gross:
            raise BusinessError('手续费不能超过成交金额，请核对')
        shares, cash, basis = account.shares, account.cash, account.cost_basis
        before = position_snapshot(shares, cash, basis)
        if self.side == 'SELL':
            validate_sale_quantity(quantity, shares)
            cost = sale_cost(shares, basis, quantity)
            net = gross - fee
            realized = net - cost
            metrics = {'net': str(net), 'realized': str(realized),
                       'return_pct': str(realized * 100 / cost) if cost else None}
            breakeven = minimum_sale_price(quantity, cost, fee_for)
            target_pct = data.get('target_profit')
            target = minimum_sale_price(quantity, cost, fee_for, target_pct) if target_pct is not None else None
            metrics.update(breakeven_price=str(breakeven) if breakeven is not None else None,
                           target_price=str(target) if target is not None else None)
            after = position_snapshot(shares - quantity, cash + net, basis - cost)
        else:
            total = gross + fee
            metrics = {'total': str(total), 'cash_sufficient': cash >= total}
            after = position_snapshot(shares + quantity, cash - total, basis + total)
        return Response({'quantity': quantity, 'gross': str(gross), 'fee': str(fee), 'fee_estimated': fee_estimated,
                         'before': before, 'after': after, **metrics})


class SellPreviewView(TradePreviewView):
    serializer_class = SellPreviewSerializer
    side = 'SELL'


class SellBatchPreviewView(APIView):
    def post(self, request):
        serializer = SellBatchPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = preview_account(request.user)
        shares, cash, basis = account.shares, account.cash, account.cost_basis
        results = []
        total_net, total_realized = D(0), D(0)
        for index, leg in enumerate(serializer.validated_data['legs'], 1):
            quantity, price = leg['quantity'], leg['price']
            try:
                validate_sale_quantity(quantity, shares)
                gross = cash_round(price * quantity)
                fee = preview_fee_for(request.user, leg.get('fee'))(gross)
                if fee > gross:
                    raise BusinessError('手续费不能超过成交金额，请核对')
            except BusinessError as error:
                raise BusinessError(f'第 {index} 批：{error}') from error
            cost = sale_cost(shares, basis, quantity)
            net = gross - fee
            realized = net - cost
            shares -= quantity
            basis -= cost
            cash += net
            total_net += net
            total_realized += realized
            results.append({'quantity': quantity, 'price': str(price), 'fee': str(fee), 'net': str(net),
                            'realized': str(realized), 'shares_after': shares})
        return Response({'legs': results, 'net': str(total_net), 'realized': str(total_realized),
                         'after': position_snapshot(shares, cash, basis)})


class HoldingHistoryView(APIView):
    def get(self, request):
        account = Account.objects.filter(user=request.user, initialized_at__isnull=False).first()
        return Response(holding_history(account) if account else {'points': [], 'truncated': False})


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


class EntriesExportView(APIView):
    def get(self, request):
        from core.exports import csv_download, entry_rows
        columns = ('流水编号','类型','纠错目标','方向','成交时间','份额','成交价','手续费','资金变动','记账时间','备注')
        return csv_download('518880-entries.csv', columns, entry_rows(request.user))

class CorrectView(APIView):
    def post(self,request,pk):
        # Resolve ownership before validating body or initialization status.
        get_object_or_404(Entry,user=request.user,pk=pk,kind='TRADE')
        row,created=post_entry(request.user,request.data,request.headers.get('Idempotency-Key'),kind='CORRECTION',corrects_id=pk)
        return Response(entry_data(row),status=201 if created else 200)

class PlansView(APIView):
    def get(self,request):
        a=get_account(request.user)
        return Response([plan_data(p,a,request.user) for p in Plan.objects.filter(user=request.user,side__in=['BUY','SELL']).order_by('-id')[:100]])
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
            p=get_object_or_404(Plan.objects.select_for_update(),user=request.user,pk=pk,status='ACTIVE',side__in=['BUY','SELL'])
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
            p=get_object_or_404(Plan.objects.select_for_update(),user=request.user,pk=pk,side__in=['BUY','SELL'])
            if p.status=='ACTIVE':
                p.status='CANCELLED';p.save(update_fields=['status','updated_at'])
                Episode.objects.filter(plan=p,status__in=['OPEN','UNKNOWN']).update(status='CLOSED')
        return Response(plan_data(p))

class EpisodesView(APIView):
    def get(self,request):
        return Response([{'id':e.pk,'plan':e.plan_id,'version':e.version,'side':e.plan.side,'status':e.status,'context':e.context,'sent_count':e.sent_count,'created_at':e.created_at} for e in Episode.objects.filter(plan__user=request.user,plan__side__in=['BUY','SELL']).select_related('plan').order_by('-id')[:30]])

def alert_data(p):
    episode=Episode.objects.filter(plan=p,version=p.version).order_by('-id').first()
    return {'id':p.pk,'kind':p.alert_kind,'direction':p.direction,'threshold':str(p.alert_threshold),'interval':p.alert_interval,'repeat_max':p.alert_repeat_max,'label':p.alert_label,'enabled':p.status=='ACTIVE','version':p.version,'episode':{'id':episode.pk,'status':episode.status,'context':episode.context,'sent_count':episode.sent_count} if episode else None}

def alert_values(p):
    return {'kind':p.alert_kind,'direction':p.direction,'threshold':p.alert_threshold,'interval':p.alert_interval,'repeat_max':p.alert_repeat_max,'label':p.alert_label}

def set_alert_values(p,d):
    p.alert_kind=d['kind'];p.direction=d['direction'];p.alert_threshold=d['threshold'];p.alert_interval=d['interval'];p.alert_repeat_max=d['repeat_max'];p.alert_label=d['label']

class AlertsView(APIView):
    def get(self,request):
        return Response([alert_data(p) for p in Plan.objects.filter(user=request.user,side='INFO',public_alert__isnull=True,status__in=['ACTIVE','PAUSED']).order_by('-id')])
    def post(self,request):
        serializer=AlertSerializer(data=request.data);serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            if Plan.objects.filter(user=request.user,side='INFO',public_alert__isnull=True,status__in=['ACTIVE','PAUSED']).count()>=100:raise BusinessError('最多设置 100 条行情提醒')
            p=Plan(user=request.user,side='INFO');set_alert_values(p,serializer.validated_data);p.save()
        return Response(alert_data(p),status=201)

class AlertDetailView(APIView):
    def patch(self,request,pk):
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            p=get_object_or_404(Plan.objects.select_for_update(),user=request.user,pk=pk,side='INFO',public_alert__isnull=True,status__in=['ACTIVE','PAUSED'])
            raw=alert_values(p);raw.update({k:v for k,v in request.data.items() if k!='enabled'})
            serializer=AlertSerializer(data=raw);serializer.is_valid(raise_exception=True)
            enabled=s.BooleanField().run_validation(request.data.get('enabled',p.status=='ACTIVE'))
            set_alert_values(p,serializer.validated_data);p.status='ACTIVE' if enabled else 'PAUSED';p.version+=1;p.condition_met=False;p.save()
            Episode.objects.filter(plan=p,status__in=['OPEN','UNKNOWN']).update(status='CLOSED')
        return Response(alert_data(p))
    def delete(self,request,pk):
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            p=get_object_or_404(Plan.objects.select_for_update(),user=request.user,pk=pk,side='INFO',public_alert__isnull=True,status__in=['ACTIVE','PAUSED'])
            p.status='CANCELLED';p.version+=1;p.condition_met=False;p.save()
            Episode.objects.filter(plan=p,status__in=['OPEN','UNKNOWN']).update(status='CLOSED')
        return Response({'detail':'提醒已删除'})

class AlertIgnoreView(APIView):
    def post(self,request,pk):
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            p=get_object_or_404(Plan.objects.select_for_update(),user=request.user,pk=pk,side='INFO',status='ACTIVE')
            Episode.objects.filter(plan=p,version=p.version,status__in=['OPEN','UNKNOWN']).update(status='IGNORED')
        return Response({'detail':'本轮提醒已停止'})

def public_rule_data(rule):
    return {'id':rule.pk,'kind':rule.kind,'direction':rule.direction,'threshold':str(rule.threshold),'interval':rule.interval,'repeat_max':rule.repeat_max,'label':rule.label}

def valid_public_rule(data):
    serializer=AlertSerializer(data=data);serializer.is_valid(raise_exception=True)
    if serializer.validated_data['kind']=='PCT_COST':raise s.ValidationError('公共提醒不能使用个人持仓成本')
    return serializer.validated_data

class PublicAlertsAdminView(APIView):
    permission_classes=[AppAdmin]
    def get(self,request):
        return Response([public_rule_data(r) for r in PublicAlert.objects.filter(active=True).order_by('-id')])
    def post(self,request):
        from core.public_alerts import lock_public_alerts
        d=valid_public_rule(request.data)
        with transaction.atomic():
            lock_public_alerts()
            if PublicAlert.objects.filter(active=True).count()>=100:raise BusinessError('最多设置 100 条公共提醒')
            rule=PublicAlert.objects.create(**d)
            Audit.objects.create(actor=request.user,action='create_public_alert',object_id=str(rule.pk))
        return Response(public_rule_data(rule),status=201)

class PublicAlertAdminDetailView(APIView):
    permission_classes=[AppAdmin]
    def patch(self,request,pk):
        from core.public_alerts import lock_public_alerts
        with transaction.atomic():
            lock_public_alerts();rule=get_object_or_404(PublicAlert.objects.select_for_update(),pk=pk,active=True)
            raw=public_rule_data(rule);raw.update(request.data);d=valid_public_rule(raw)
            for k,v in d.items():setattr(rule,k,v)
            rule.version+=1;rule.condition_met=False;rule.save()
            GroupEpisode.objects.filter(plan_rule=rule,status__in=['OPEN','UNKNOWN']).update(status='CLOSED')
            Audit.objects.create(actor=request.user,action='edit_public_alert',object_id=str(rule.pk))
        return Response(public_rule_data(rule))
    def delete(self,request,pk):
        from core.public_alerts import lock_public_alerts
        with transaction.atomic():
            lock_public_alerts();rule=get_object_or_404(PublicAlert.objects.select_for_update(),pk=pk,active=True)
            rule.active=False;rule.version+=1;rule.condition_met=False;rule.save()
            GroupEpisode.objects.filter(plan_rule=rule,status__in=['OPEN','UNKNOWN']).update(status='CLOSED')
            Audit.objects.create(actor=request.user,action='delete_public_alert',object_id=str(rule.pk))
        return Response({'detail':'公共提醒已删除'})

class PublicAlertsView(APIView):
    def get(self,request):
        return Response([public_rule_data(r) for r in PublicAlert.objects.filter(active=True).order_by('-id')])

class GroupPushView(APIView):
    permission_classes=[AppAdmin]
    def get(self,request):
        value=SystemState.objects.filter(pk='group-push').values_list('value',flat=True).first() or {}
        return Response({'topic':value.get('topic',''),'token_bound':bool(value.get('token_encrypted'))})
    def patch(self,request):
        from core.public_alerts import lock_public_alerts
        from core.push import encrypt_token
        topic=s.RegexField(r'^[a-zA-Z0-9_-]{1,100}$').run_validation(request.data['topic']) if 'topic' in request.data else None
        token=s.RegexField(r'^[a-zA-Z0-9]{20,100}$',allow_blank=True).run_validation(request.data['token']) if 'token' in request.data else None
        with transaction.atomic():
            lock_public_alerts()
            state,_=SystemState.objects.select_for_update().get_or_create(key='group-push',defaults={'value':{}})
            value=state.value or {}
            if topic is not None:value['topic']=topic
            if token is not None:value['token_encrypted']=encrypt_token(token) if token else ''
            value['owner_id']=request.user.pk;state.value=value;state.save()
            Audit.objects.create(actor=request.user,action='edit_group_push')
        return self.get(request)

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


class MarketHistoryView(APIView):
    download = False

    def get(self, request):
        from core.market import quote_history
        days = s.ChoiceField(choices=['1', '3', '7']).run_validation(request.query_params.get('days', '7'))
        history = quote_history(int(days))
        if self.download:
            from core.exports import csv_download
            rows = ((point['at'], point['price'], point['source']) for point in history['points'])
            return csv_download(f'518880-quotes-{days}d.csv', ('北京时间','价格','来源'), rows)
        return Response(history)

class QuoteView(APIView):
    def get(self,request):
        from core.market import price_data
        return Response(price_data())

class SystemView(APIView):
    permission_classes=[AppAdmin]
    def get(self,request):
        from core.monitor import worker_ok
        return Response({'worker_ok':worker_ok(),'market':SystemState.objects.filter(pk='market').values_list('value',flat=True).first() or {},'backup':SystemState.objects.filter(pk='backup').values_list('value',flat=True).first() or {}})
