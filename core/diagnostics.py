"""Small NAS health history and deduplicated fault/recovery notifications."""
import hashlib
import logging
import shutil
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from core.common import BusinessError
from core.market import is_trading
from core.models import Delivery, SystemState, User

logger = logging.getLogger(__name__)


def notify_maintainers(event):
    from core.push import reserve_content, reserve_quota, send_http
    for user in User.objects.filter(is_app_admin=True, is_active=True).exclude(token_encrypted=''):
        try:
            with transaction.atomic():
                user = User.objects.select_for_update().get(pk=user.pk)
                token = reserve_quota(user, timezone.now())
                delivery = Delivery.objects.create(user=user, kind='SYSTEM', token_hash=hashlib.sha256(token.encode()).hexdigest())
                content = f"{event['label']}\n{'已恢复' if event['recovered'] else '需要检查'}\n检查时间 {event['at']}"
                if not reserve_content(delivery, token, content, timezone.now()):
                    delivery.status = 'SKIPPED'
                    delivery.detail = '同类系统消息发送过于频繁'
                    delivery.save(update_fields=['status', 'detail'])
                    continue
            status, detail = send_http(token, '金笺 · 系统运行提醒', content)
            Delivery.objects.filter(pk=delivery.pk).update(status=status, detail=detail)
        except BusinessError:
            logger.warning('system notification could not be reserved')


def run_diagnostics(now=None):
    now = now or timezone.now()
    from core.monitor import monitor_lock
    close_old_connections()
    try:
        with monitor_lock(5188802028) as acquired:
            if not acquired:
                return
            heartbeat = SystemState.objects.filter(pk='heartbeat').first()
            market = SystemState.objects.filter(pk='market').values_list('value', flat=True).first() or {}
            backup = SystemState.objects.filter(pk='backup').values_list('value', flat=True).first() or {}
            folder = settings.BACKUP_DIR
            while not folder.exists() and folder != folder.parent:
                folder = folder.parent
            disk = shutil.disk_usage(folder)
            backup_time = timezone.datetime.fromisoformat(backup['last_success']) if backup.get('last_success') else None
            last_delivery = Delivery.objects.filter(user_id=OuterRef('pk'), kind__in=['ALERT', 'TEST']).order_by('-created_at', '-pk')
            delivery_failed = User.objects.filter(is_active=True).exclude(token_encrypted='').annotate(
                last_status=Subquery(last_delivery.values('status')[:1])).filter(last_status__in=['FAILED', 'UNKNOWN']).exists()
            checks = {
                'worker': {'ok': bool(heartbeat and now-heartbeat.updated_at < timedelta(seconds=210)), 'label': '后台监测心跳'},
                'market': {'ok': not is_trading(now) or bool(market.get('available') and market.get('last_success_at') and now-timezone.datetime.fromisoformat(market['last_success_at']) < timedelta(seconds=210)), 'label': '交易时段行情采集'},
                'backup': {'ok': bool(backup_time and backup.get('ok', True) and now-backup_time < timedelta(hours=36)), 'label': '最近备份'},
                'disk': {'ok': disk.free >= 512*1024*1024 and disk.free/disk.total >= 0.05, 'label': '备份目录可用空间'},
                'notifications': {'ok': not delivery_failed, 'label': '通知投递状态'},
            }
            with transaction.atomic():
                state, _ = SystemState.objects.select_for_update().get_or_create(pk='diagnostics')
                previous = state.value.get('checks', {})
                events = list(state.value.get('events', []))
                changed = []
                for key, check in checks.items():
                    old = previous.get(key)
                    if (old is None and not check['ok']) or (old is not None and old['ok'] != check['ok']):
                        event = {'key': key, 'label': check['label'], 'recovered': check['ok'], 'at': now.isoformat()}
                        changed.append(event)
                        events.insert(0, event)
                state.value = {'checks': checks, 'events': events[:30], 'checked_at': now.isoformat(),
                               'disk_free_gb': str(round(disk.free/(1024**3), 2)),
                               'last_collection_at': market.get('last_success_at')}
                state.save()
            for event in changed:
                notify_maintainers(event)
            return state.value
    except Exception as error:
        logger.error('system diagnostics failed (%s)', type(error).__name__)
    finally:
        close_old_connections()
