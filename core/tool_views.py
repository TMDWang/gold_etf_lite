from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers as s
from rest_framework.response import Response
from rest_framework.views import APIView

from core.account_tools import entry_preview, reconcile
from core.common import BusinessError, clean_json, throttle
from core.ledger import get_account, require_initialized
from core.models import Account, DailyReport, Delivery, Entry, Episode, GroupEpisode, Plan, User
from core.serializers import PreviewSerializer, TradeSerializer


def page_number(request):
    return s.IntegerField(min_value=1, max_value=1000000).run_validation(request.query_params.get('page', 1))


class ReconciliationView(APIView):
    def get(self, request):
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            account = Account.objects.select_for_update().get(pk=get_account(request.user).pk)
            require_initialized(account)
            rows = list(Entry.objects.filter(user=request.user).order_by('id'))
            return Response(reconcile(account, rows))


class EntryPreviewView(APIView):
    def post(self, request):
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            account = Account.objects.select_for_update().get(pk=get_account(request.user).pk)
            require_initialized(account)
            correction_id = s.IntegerField(min_value=1).run_validation(request.data['correction_id']) if request.data.get('correction_id') else None
            target = get_object_or_404(Entry, user=request.user, pk=correction_id, kind='TRADE') if correction_id else None
            serializer = TradeSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            if request.data.get('confirmation_key'):
                key = s.CharField(max_length=80).run_validation(request.data['confirmation_key'])
                existing = Entry.objects.filter(user=request.user, idempotency_key=key).first()
                if existing:
                    payload = dict(serializer.validated_data)
                    plan_id = payload.get('plan_id')
                    for field in ('plan_id', 'plan_version', 'ledger_revision'):
                        payload.pop(field, None)
                    reason = str(request.data.get('correction_reason', '')).strip()
                    if existing.payload != clean_json(payload) or existing.corrects_id != correction_id or existing.plan_id != plan_id or (correction_id and existing.reason != reason):
                        raise BusinessError('上次确认内容已入账，请先查看记录后重新打开表单', 409)
                    return Response({'already_recorded': True, 'entry_id': existing.pk})
            rows = list(Entry.objects.filter(user=request.user).order_by('id'))
            return Response(entry_preview(account, rows, serializer.validated_data, target))


class FeePreviewView(APIView):
    def post(self, request):
        from core.ledger import cash_round
        from core.plans import estimated_fee
        serializer = PreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        fee = estimated_fee(request.user, cash_round(data['price'] * data['quantity']))
        if fee is None:
            raise BusinessError('请先在个人设置补齐券商费用参数')
        return Response({'fee': str(fee), 'calculated_at': timezone.now()})


class ReportsView(APIView):
    def get(self, request):
        page = page_number(request)
        if request.query_params.get('day'):
            day = s.DateField().run_validation(request.query_params['day'])
            versions = DailyReport.objects.filter(user=request.user, day=day).order_by('-revision')
            return Response({'count': versions.count(), 'results': [
                {**row.data, 'id': row.pk, 'revision': row.revision, 'created_at': row.created_at}
                for row in versions[(page-1)*20:page*20]]})
        latest = {}
        for row in DailyReport.objects.filter(user=request.user).order_by('-day', '-revision'):
            if row.day not in latest:
                latest[row.day] = row
        rows = list(latest.values())
        return Response({'count': len(rows), 'results': [
            {**row.data, 'id': row.pk, 'revision': row.revision, 'created_at': row.created_at}
            for row in rows[(page-1)*20:page*20]]})

    def post(self, request):
        from core.reports import settle_reports
        throttle(f'report-refresh:{request.user.pk}', 6, 300)
        settle_reports(request.user)
        return self.get(request)


class SetupView(APIView):
    def get(self, request):
        user = request.user
        account = Account.objects.filter(user=user).first()
        return Response({'account_ready': bool(account and account.initialized_at),
                         'fees_ready': all(getattr(user, key) is not None for key in ('fee_rate', 'fee_minimum', 'fee_extra')),
                         'push_ready': bool(user.token_encrypted),
                         'test_ready': bool(user.token_encrypted and user.push_tested_at),
                         'rule_ready': Plan.objects.filter(user=user, status='ACTIVE', public_alert__isnull=True).exists()})


class ReminderHistoryView(APIView):
    def get(self, request):
        page = page_number(request)
        scope = s.ChoiceField(choices=['ALL', 'PERSONAL', 'PUBLIC']).run_validation(request.query_params.get('scope', 'ALL'))
        rows = []
        if scope != 'PUBLIC':
            episodes = Episode.objects.filter(plan__user=request.user, plan__public_alert__isnull=True).select_related('plan').prefetch_related('delivery_set')
            for episode in episodes:
                attempts = list(episode.delivery_set.all())
                latest = max(attempts, key=lambda item: item.pk) if attempts else None
                rows.append({'id': f'p{episode.pk}', 'scope': 'PERSONAL', 'status': episode.status,
                             'label': episode.context.get('label') or episode.plan.alert_label or ('买入计划' if episode.plan.side == 'BUY' else '卖出计划' if episode.plan.side == 'SELL' else '行情提醒'),
                             'context': episode.context, 'created_at': episode.created_at,
                             'sent_count': episode.sent_count, 'delivery_status': latest.status if latest else None,
                             'delivery_detail': latest.detail if latest else '', 'last_sent_at': latest.created_at if latest else None})
        if scope != 'PERSONAL':
            for episode in GroupEpisode.objects.select_related('plan_rule'):
                rows.append({'id': f'g{episode.pk}', 'scope': 'PUBLIC', 'status': episode.status,
                             'label': episode.context.get('label') or episode.plan_rule.label or '公共行情提醒', 'context': episode.context,
                             'created_at': episode.created_at, 'sent_count': episode.sent_count,
                             'delivery_status': None, 'delivery_detail': '公共消息按 PushPlus 群组接收'})
        rows.sort(key=lambda item: (item['created_at'], item['id']), reverse=True)
        return Response({'count': len(rows), 'results': rows[(page-1)*20:page*20]})


class PlanPauseView(APIView):
    def post(self, request, pk):
        from core.activity import pause_plan
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            plan = get_object_or_404(Plan.objects.select_for_update(), pk=pk, user=request.user,
                                    status='ACTIVE', public_alert__isnull=True)
            return Response(pause_plan(request.user, plan, request.data))
