from datetime import timedelta
from decimal import Decimal as D
import hashlib
import requests
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from core.models import User, Account, Plan, Episode, GroupEpisode, PublicAlert, SystemState, Delivery
from core.common import BusinessError, throttle
from core.plans import evaluate, ALERT_LABELS, PRICE_ALERT_KINDS

def cipher():
    try:return Fernet(settings.ENCRYPTION_KEY.encode())
    except (ValueError,TypeError):raise BusinessError('通知加密密钥尚未配置，请联系 NAS 维护者')

def encrypt_token(token):
    return cipher().encrypt(token.encode()).decode()

def decrypt_token(value):
    try:return cipher().decrypt(value.encode()).decode()
    except InvalidToken:raise BusinessError('通知密钥无法解密，请重新绑定或核对 NAS 加密密钥')

def send_http(token,title,content,topic=None):
    try:
        payload={'token':token,'title':title,'content':content,'template':'txt','channel':'wechat'}
        if topic:payload['topic']=topic
        response=requests.post('https://www.pushplus.plus/send',json=payload,timeout=(4,8))
        if response.status_code!=200:
            return 'UNKNOWN','服务响应异常，送达结果未确认'
        result=response.json()
        if result.get('code')==200:
            return 'SENT','PushPlus 已接收，请留意微信；接收不等于已送达'
        # Avoid copying arbitrary provider data into UI or logs.
        return 'FAILED','PushPlus 拒绝请求，请核对实名认证、密钥、额度和服务状态'
    except (requests.RequestException,ValueError):
        return 'UNKNOWN','网络或响应异常，送达结果未确认；不会自动重发本轮'

@transaction.atomic
def reserve_quota(user,now,exclude_id=None):
    token=decrypt_token(user.token_encrypted)
    return reserve_token_quota(token,now,exclude_id)

@transaction.atomic
def reserve_token_quota(token,now,exclude_id=None):
    fingerprint=hashlib.sha256(token.encode()).hexdigest()
    # Lock a token bucket shared across users before checking rolling time windows.
    throttle('push-reserve:'+fingerprint,100000,1,now)
    attempts=Delivery.objects.filter(token_hash=fingerprint)
    if exclude_id:attempts=attempts.exclude(pk=exclude_id)
    if attempts.filter(created_at__gt=now-timedelta(seconds=60)).count()>=4 or attempts.filter(created_at__gt=now-timedelta(hours=24)).count()>=180:
        raise BusinessError('已达到应用保守推送限额，请稍后再试',429)
    return token

def reserve_content(row,token,content,now):
    fingerprint=hashlib.sha256(token.encode()).hexdigest()
    content_hash=hashlib.sha256(content.encode()).hexdigest()
    throttle('push-content-lock:'+fingerprint,100000,1,now)
    if Delivery.objects.filter(token_hash=fingerprint,content_hash=content_hash,created_at__gt=now-timedelta(hours=1)).exclude(pk=row.pk).count()>=3:
        return False
    Delivery.objects.filter(pk=row.pk).update(token_hash=fingerprint,content_hash=content_hash)
    return True

def send_test(user):
    with transaction.atomic():
        u=User.objects.select_for_update().get(pk=user.pk)
        if not u.token_encrypted:raise BusinessError('请先保存自己的 PushPlus 密钥')
        throttle(f'push-test:{u.pk}',2,3600)
        token=reserve_quota(u,timezone.now())
        row=Delivery.objects.create(user=u,kind='TEST',token_hash=hashlib.sha256(token.encode()).hexdigest())
        content='这是你在金笺主动发送的测试消息。518880 提醒只供你自行核对，系统不会自动交易。'
        if not reserve_content(row,token,content,timezone.now()):
            row.status='SKIPPED';row.detail='同内容发送过于频繁';row.save()
            raise BusinessError('同内容发送过于频繁，请一小时后再试',429)
    status,detail=send_http(token,'金笺 · 个人提醒测试',content)
    Delivery.objects.filter(pk=row.pk).update(status=status,detail=detail)
    if status == 'SENT':
        User.objects.filter(pk=u.pk, token_encrypted=u.token_encrypted).update(push_tested_at=timezone.now())
    return {'status':status,'detail':detail}

@transaction.atomic
def finish_delivery(delivery, episode, status, detail, send_now, repeat_minutes, failures):
    updated = Delivery.objects.filter(pk=delivery.pk, status='SENDING').update(status=status, detail=detail)
    if not updated:
        return
    active = type(episode).objects.filter(pk=episode.pk, version=episode.version, status='OPEN')
    if status == 'SENT':
        active.update(sent_count=F('sent_count') + 1, next_at=send_now + timedelta(minutes=repeat_minutes))
    elif status == 'UNKNOWN':
        active.update(status='UNKNOWN')
    else:
        active.update(next_at=send_now + timedelta(minutes=5 * (failures + 1)))


def deliver_due(now=None):
    if settings.PAUSE_NOTIFICATIONS:return
    now=now or timezone.now()
    for ep_id,user_id in Episode.objects.filter(status='OPEN',next_at__lte=now,plan__status='ACTIVE',plan__public_alert__isnull=True,plan__user__is_active=True).values_list('pk','plan__user_id'):
        with transaction.atomic():
            u=User.objects.select_for_update().get(pk=user_id)
            if not u.is_active or not u.token_encrypted:continue
            account=Account.objects.select_for_update().filter(user=u).first()
            raw=Episode.objects.get(pk=ep_id)
            p=Plan.objects.select_for_update().get(pk=raw.plan_id)
            e=Episode.objects.select_for_update().get(pk=ep_id)
            if p.snoozed_until and p.snoozed_until > now:continue
            maximum=p.alert_repeat_max if p.side=='INFO' else u.reminder_max
            if p.status!='ACTIVE' or p.version!=e.version or e.status!='OPEN' or e.next_at>now or e.sent_count>=maximum:continue
            from core.monitor import usable_quote
            quote=usable_quote(now)
            if not quote or not account:continue
            context=evaluate(p,account,quote.price,u,quote=quote)
            if context.get('comparison_missing'):continue
            if not context['eligible']:
                e.status='CLOSED';e.save(update_fields=['status']);continue
            # Finite, explicit-rejection retry budget separate from business repetition.
            failures=Delivery.objects.filter(episode=e,status='FAILED').count()
            if failures>=3:
                e.status='FAILED';e.save(update_fields=['status']);continue
            if Delivery.objects.filter(episode=e,status='SENDING').exists():continue
            try:token=reserve_quota(u,now)
            except BusinessError:continue
            d=Delivery.objects.create(user=u,episode=e,token_hash=hashlib.sha256(token.encode()).hexdigest())
            # Claim persists before HTTP. Crash => SENDING then UNKNOWN, never blind resend.
        with transaction.atomic():
            u=User.objects.select_for_update().get(pk=user_id)
            account=Account.objects.select_for_update().get(user=u)
            p=Plan.objects.select_for_update().get(pk=p.pk)
            e=Episode.objects.select_for_update().get(pk=ep_id)
            from core.monitor import usable_quote
            send_now=timezone.now()
            quote=usable_quote(send_now)
            context=evaluate(p,account,quote.price if quote else None,u,quote=quote)
            if not u.is_active or not u.token_encrypted or p.version!=e.version or p.status!='ACTIVE' or e.status!='OPEN' or not quote or not context['eligible'] or (p.snoozed_until and p.snoozed_until > send_now):
                Delivery.objects.filter(pk=d.pk).update(status='SKIPPED',detail='行情、计划或账号状态已变化')
                continue
            try:token=reserve_quota(u,send_now,exclude_id=d.pk)
            except BusinessError:
                Delivery.objects.filter(pk=d.pk).update(status='SKIPPED',detail='发送前限额或密钥检查未通过')
                continue
            if p.side=='INFO':
                title='金笺 · 518880 行情提醒'
                basis=ALERT_LABELS[p.alert_kind]
                unit='元' if p.alert_kind in PRICE_ALERT_KINDS else '%'
                content=f"事件 #{e.pk} / {p.alert_label or '行情提醒'}\n参考价 {quote.price} 元（源时间 {quote.source_at.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Shanghai')).isoformat()}）\n{basis} {'达到或高于' if p.direction=='ABOVE' else '达到或低于'} {p.alert_threshold}{unit}；当前 {D(context['value']).quantize(D('0.0001'))}{unit}\n仅供观察行情，不构成买卖建议。\n{settings.PUBLIC_URL}"
            else:
                title='金笺 · 518880 '+('买入' if p.side=='BUY' else '卖出')+'条件达到'
                content=f"事件 #{e.pk} / 计划版本 {e.version}\n参考价 {quote.price} 元（源时间 {quote.source_at.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Shanghai')).isoformat()}）\n{context['reason']}\n参考份额 {context['quantity']} 份。请到券商自行核对及交易，再回金笺记录实际成交。\n{settings.PUBLIC_URL}"
            if not reserve_content(d,token,content,send_now):
                Delivery.objects.filter(pk=d.pk).update(status='SKIPPED',detail='同内容发送已到本小时上限')
                e.next_at=now+timedelta(hours=1);e.save(update_fields=['next_at']);continue
            repeat_minutes = p.alert_interval if p.side == 'INFO' else u.reminder_minutes
        status, detail = send_http(token, title, content)
        finish_delivery(d, e, status, detail, send_now, repeat_minutes, failures)
    deliver_group_due(now)

def deliver_group_due(now):
    from core.public_alerts import lock_public_alerts
    from core.monitor import usable_quote
    for eid in GroupEpisode.objects.filter(status='OPEN',next_at__lte=now,plan_rule__active=True).values_list('pk',flat=True):
        with transaction.atomic():
            lock_public_alerts()
            state=SystemState.objects.filter(pk='group-push').first();config=state.value if state else {}
            if not config.get('token_encrypted') or not config.get('topic'):continue
            owner=User.objects.filter(pk=config.get('owner_id'),is_active=True,is_app_admin=True).first()
            e=GroupEpisode.objects.select_for_update().select_related('plan_rule').get(pk=eid);rule=e.plan_rule
            if not owner or not rule.active or rule.version!=e.version or e.status!='OPEN' or e.next_at>now or e.sent_count>=rule.repeat_max:continue
            q=usable_quote(now)
            p=Plan(side='INFO',alert_kind=rule.kind,direction=rule.direction,alert_threshold=rule.threshold)
            if not q or not evaluate(p,None,q.price,None,quote=q)['eligible']:continue
            failures=Delivery.objects.filter(group_episode=e,status='FAILED').count()
            if failures>=3:e.status='FAILED';e.save(update_fields=['status']);continue
            if Delivery.objects.filter(group_episode=e,status='SENDING').exists():continue
            try:token=reserve_token_quota(decrypt_token(config['token_encrypted']),now)
            except BusinessError:continue
            claimed_config=(config['token_encrypted'],config['topic'],config['owner_id'])
            d=Delivery.objects.create(user=owner,group_episode=e,token_hash=hashlib.sha256(token.encode()).hexdigest())
        with transaction.atomic():
            lock_public_alerts()
            state=SystemState.objects.filter(pk='group-push').first();config=state.value if state else {}
            e=GroupEpisode.objects.select_for_update().select_related('plan_rule').get(pk=eid);rule=e.plan_rule
            send_now=timezone.now();q=usable_quote(send_now)
            p=Plan(side='INFO',alert_kind=rule.kind,direction=rule.direction,alert_threshold=rule.threshold)
            context=evaluate(p,None,q.price if q else None,None,quote=q)
            owner=User.objects.filter(pk=config.get('owner_id'),is_active=True,is_app_admin=True).first()
            if not owner or (config.get('token_encrypted'),config.get('topic'),config.get('owner_id'))!=claimed_config or not rule.active or rule.version!=e.version or e.status!='OPEN' or not q or not context['eligible']:
                Delivery.objects.filter(pk=d.pk).update(status='SKIPPED',detail='群组配置、行情或规则已变化');continue
            try:token=reserve_token_quota(decrypt_token(config['token_encrypted']),send_now,exclude_id=d.pk)
            except BusinessError:
                Delivery.objects.filter(pk=d.pk).update(status='SKIPPED',detail='发送前限额或密钥检查未通过');continue
            unit='元' if rule.kind in PRICE_ALERT_KINDS else '%'
            basis=ALERT_LABELS[rule.kind]
            content=f"公共事件 #{e.pk} / {rule.label or '行情提醒'}\n参考价 {q.price} 元（源时间 {q.source_at.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Shanghai')).isoformat()}）\n{basis} {'达到或高于' if rule.direction=='ABOVE' else '达到或低于'} {rule.threshold}{unit}；当前 {D(context['value']).quantize(D('0.0001'))}{unit}\n仅供观察行情，不构成买卖建议。\n{settings.PUBLIC_URL}"
            if not reserve_content(d,token,content,send_now):
                Delivery.objects.filter(pk=d.pk).update(status='SKIPPED',detail='同内容发送已到本小时上限')
                e.next_at=send_now+timedelta(hours=1);e.save(update_fields=['next_at']);continue
            repeat_minutes = rule.interval
            topic = config['topic']
        status, detail = send_http(token, '金笺 · 518880 公共行情提醒', content, topic=topic)
        finish_delivery(d, e, status, detail, send_now, repeat_minutes, failures)
