from datetime import timedelta
import hashlib
import requests
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from core.models import User, Account, Plan, Episode, Delivery
from core.common import BusinessError, throttle
from core.plans import evaluate

def cipher():
    try:return Fernet(settings.ENCRYPTION_KEY.encode())
    except (ValueError,TypeError):raise BusinessError('通知加密密钥尚未配置，请联系 NAS 维护者')

def encrypt_token(token):
    return cipher().encrypt(token.encode()).decode()

def decrypt_token(value):
    try:return cipher().decrypt(value.encode()).decode()
    except InvalidToken:raise BusinessError('通知密钥无法解密，请重新绑定或核对 NAS 加密密钥')

def send_http(token,title,content):
    try:
        response=requests.post('https://www.pushplus.plus/send',json={'token':token,'title':title,'content':content,'template':'txt','channel':'wechat'},timeout=(4,8))
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
        row=Delivery.objects.create(user=u,token_hash=hashlib.sha256(token.encode()).hexdigest())
        content='这是你在金笺主动发送的测试消息。518880 提醒只供你自行核对，系统不会自动交易。'
        if not reserve_content(row,token,content,timezone.now()):
            row.status='SKIPPED';row.detail='同内容发送过于频繁';row.save()
            raise BusinessError('同内容发送过于频繁，请一小时后再试',429)
    status,detail=send_http(token,'金笺 · 个人提醒测试',content)
    Delivery.objects.filter(pk=row.pk).update(status=status,detail=detail)
    return {'status':status,'detail':detail}

def deliver_due(now=None):
    if settings.PAUSE_NOTIFICATIONS:return
    now=now or timezone.now()
    for ep_id,user_id in Episode.objects.filter(status='OPEN',next_at__lte=now,plan__status='ACTIVE',plan__user__is_active=True).values_list('pk','plan__user_id'):
        with transaction.atomic():
            u=User.objects.select_for_update().get(pk=user_id)
            if not u.is_active or not u.token_encrypted:continue
            account=Account.objects.select_for_update().filter(user=u).first()
            raw=Episode.objects.get(pk=ep_id)
            p=Plan.objects.select_for_update().get(pk=raw.plan_id)
            e=Episode.objects.select_for_update().get(pk=ep_id)
            if p.status!='ACTIVE' or p.version!=e.version or e.status!='OPEN' or e.next_at>now or e.sent_count>=u.reminder_max:continue
            from core.monitor import usable_quote
            quote=usable_quote(now)
            if not quote or not account:continue
            context=evaluate(p,account,quote.price,u)
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
            context=evaluate(p,account,quote.price if quote else None,u)
            if not u.is_active or not u.token_encrypted or p.version!=e.version or p.status!='ACTIVE' or e.status!='OPEN' or not quote or not context['eligible']:
                Delivery.objects.filter(pk=d.pk).update(status='SKIPPED',detail='行情、计划或账号状态已变化')
                continue
            try:token=reserve_quota(u,send_now,exclude_id=d.pk)
            except BusinessError:
                Delivery.objects.filter(pk=d.pk).update(status='SKIPPED',detail='发送前限额或密钥检查未通过')
                continue
            title='金笺 · 518880 '+('买入' if p.side=='BUY' else '卖出')+'条件达到'
            content=f"事件 #{e.pk} / 计划版本 {e.version}\n参考价 {quote.price} 元（源时间 {quote.source_at.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Shanghai')).isoformat()}）\n{context['reason']}\n参考份额 {context['quantity']} 份。请到券商自行核对及交易，再回金笺记录实际成交。\n{settings.PUBLIC_URL}"
            if not reserve_content(d,token,content,send_now):
                Delivery.objects.filter(pk=d.pk).update(status='SKIPPED',detail='同内容发送已到本小时上限')
                e.next_at=now+timedelta(hours=1);e.save(update_fields=['next_at']);continue
            status,detail=send_http(token,title,content)
            Delivery.objects.filter(pk=d.pk).update(status=status,detail=detail)
            if status=='SENT':
                e.sent_count+=1;e.next_at=send_now+timedelta(minutes=u.reminder_minutes)
            elif status=='UNKNOWN':
                e.status='UNKNOWN'
            else:
                e.next_at=send_now+timedelta(minutes=5*(failures+1))
            e.save(update_fields=['sent_count','next_at','status'])
