"""Explanations and pauses for existing rules, without changing their triggers."""
from datetime import timedelta
from decimal import Decimal as D

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers as s

from core.market import CN, calendar_status, is_trading, quote_fresh
from core.models import Audit, Episode, SystemState
from core.plans import evaluate


def rule_status(plan, account, user, quote, now=None, market_state=None):
    now = now or timezone.now()
    result = evaluate(plan, account, quote.price if quote else None, user, quote=quote)
    value = result.get('value') if plan.side == 'INFO' else result.get('price')
    target = plan.alert_threshold if plan.side == 'INFO' else plan.target_price
    if value is not None and target is not None:
        direction = 'ABOVE' if plan.side == 'SELL' else plan.direction
        remaining = D(value) - D(target) if direction == 'BELOW' else D(target) - D(value)
        result.update(value=value, target=str(target), gap=str(max(D(0), remaining)))
    if plan.side == 'SELL' and plan.target_profit is not None:
        result['net_target'] = str(plan.target_profit)
        if result.get('net_percent') is not None:
            result['net_gap'] = str(max(D(0), D(plan.target_profit) - D(result['net_percent'])))
    result['state'] = 'REACHED' if result['eligible'] else 'WAITING'
    result['source_at'] = quote.source_at if quote else None
    result['snoozed_until'] = plan.snoozed_until
    result['delivery_ready'] = bool(user.token_encrypted)
    result['delivery_reason'] = '' if user.token_encrypted else '个人推送尚未绑定 PushPlus'
    if market_state is None:
        market_state = SystemState.objects.filter(pk='market').values_list('value', flat=True).first() or {}
    if plan.status != 'ACTIVE':
        result.update(state='PAUSED', reason='规则已暂停')
    elif plan.snoozed_until and plan.snoozed_until > now:
        result.update(state='SNOOZED', reason='提醒已暂时停用，到期后按原规则继续检查')
    elif settings.PAUSE_NOTIFICATIONS:
        result.update(state='MAINTENANCE', reason='系统维护中，自动提醒已暂停')
    elif not calendar_status(now)['calendar_valid']:
        result.update(state='CALENDAR', reason='交易日历待更新，自动提醒已暂停')
    elif not is_trading(now):
        result.update(state='CLOSED', reason='休市或非监测时段，保留最后行情供参考')
    elif not quote_fresh(quote, now) or not market_state.get('available', True):
        result.update(state='STALE', reason='等待有效行情，暂时停止检查条件')
    result['eligible'] = result['eligible'] and result['state'] == 'REACHED'
    return result


def pause_plan(user, plan, data, now=None):
    now = now or timezone.now()
    scope = s.ChoiceField(choices=['CURRENT', 'TODAY', 'LATER', 'RESUME']).run_validation(data.get('scope', 'CURRENT'))
    if scope == 'CURRENT':
        Episode.objects.filter(plan=plan, version=plan.version, status__in=['OPEN', 'UNKNOWN']).update(status='IGNORED')
    else:
        if scope == 'TODAY':
            plan.snoozed_until = now.astimezone(CN).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        elif scope == 'LATER':
            minutes = s.IntegerField(min_value=20, max_value=1440).run_validation(data.get('minutes', 60))
            plan.snoozed_until = now + timedelta(minutes=minutes)
        else:
            plan.snoozed_until = None
        plan.save(update_fields=['snoozed_until', 'updated_at'])
    Audit.objects.create(actor=user, action='reminder_' + scope.lower(), object_id=str(plan.pk))
    return {'scope': scope, 'snoozed_until': plan.snoozed_until,
            'detail': '本轮提醒已停止' if scope == 'CURRENT' else '提醒设置已更新'}
