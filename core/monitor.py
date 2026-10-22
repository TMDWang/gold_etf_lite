import logging
from contextlib import contextmanager
from datetime import timedelta
from django.db import connection, close_old_connections, transaction
from django.conf import settings
from django.utils import timezone
from core.models import User, Account, Plan, Episode, Quote, SystemState, Delivery
from core.market import is_trading, quote_fresh
from core.plans import evaluate

logger=logging.getLogger(__name__)

def worker_ok():
    row=SystemState.objects.filter(pk='heartbeat').first()
    return bool(row and (timezone.now()-row.updated_at).total_seconds()<210)

@contextmanager
def monitor_lock():
    if connection.vendor!='postgresql':
        yield True
        return
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(5188802026)')
        acquired=cursor.fetchone()[0]
    try:yield acquired
    finally:
        if acquired:
            with connection.cursor() as cursor:cursor.execute('SELECT pg_advisory_unlock(5188802026)')

def usable_quote(now):
    q=Quote.objects.order_by('-source_at','-pk').first()
    state=SystemState.objects.filter(pk='market').values_list('value',flat=True).first() or {}
    return q if is_trading(now) and quote_fresh(q,now) and state.get('available',True) else None

def evaluate_all(now=None):
    if settings.PAUSE_NOTIFICATIONS:return
    now=now or timezone.now();quote=usable_quote(now)
    if not quote:
        # A stale interval does not count as observing the condition leave.
        return
    for plan_id,user_id in Plan.objects.filter(status='ACTIVE',user__is_active=True).values_list('pk','user_id'):
        with transaction.atomic():
            user=User.objects.select_for_update().get(pk=user_id)
            if not user.is_active:continue
            account=Account.objects.select_for_update().filter(user=user).first()
            p=Plan.objects.select_for_update().get(pk=plan_id)
            if p.status!='ACTIVE' or not account:continue
            result=evaluate(p,account,quote.price,user)
            if result['eligible']:
                if not p.condition_met:
                    p.episode_counter+=1;p.condition_met=True;p.save(update_fields=['episode_counter','condition_met'])
                    Episode.objects.create(plan=p,version=p.version,number=p.episode_counter,next_at=now,context=result)
                else:
                    Episode.objects.filter(plan=p,version=p.version,status='OPEN').update(context=result)
            elif p.condition_met:
                p.condition_met=False;p.save(update_fields=['condition_met'])
                Episode.objects.filter(plan=p,status__in=['OPEN','UNKNOWN']).update(status='CLOSED')

def tick():
    close_old_connections()
    try:
        with monitor_lock() as acquired:
            if not acquired:return
            now=timezone.now()
            from core.market import collect_quotes,collect_minutes
            from core.push import deliver_due
            # Unfinished attempts after process death may have reached the provider.
            Delivery.objects.filter(status='SENDING',created_at__lt=now-timedelta(minutes=3)).update(status='UNKNOWN',detail='进程中断，送达结果未确认')
            Episode.objects.filter(delivery__status='UNKNOWN',status='OPEN').update(status='UNKNOWN')
            state=SystemState.objects.filter(pk='market').first()
            if is_trading(now) or not state or (now-state.updated_at).total_seconds()>=300:
                collect_quotes()
                collect_minutes()
            evaluate_all();deliver_due()
            SystemState.objects.update_or_create(key='heartbeat',defaults={'value':{'ok':True}})
    except Exception as exc:
        # Do not log exception text: HTTP errors may contain tokens or financial payloads.
        logger.error('monitor tick failed (%s)',type(exc).__name__)
    finally:
        close_old_connections()
