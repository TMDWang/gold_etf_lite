import functools
import re
from datetime import datetime, timedelta, time
from decimal import Decimal as D, InvalidOperation
from zoneinfo import ZoneInfo
import requests
from django.utils import timezone
from django.conf import settings
from core.models import Quote, Minute, SystemState

CN=ZoneInfo('Asia/Shanghai')
HEADERS={'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn/'}

@functools.lru_cache(maxsize=1)
def trading_calendar():
    import exchange_calendars as xcals
    return xcals.get_calendar('XSHG')

def is_trading(now=None):
    now=(now or timezone.now()).astimezone(CN)
    clock=now.time().replace(tzinfo=None)
    if not (time(9,30)<=clock<=time(11,30) or time(13)<=clock<=time(15)):
        return False
    try:
        return bool(trading_calendar().is_session(now.date().isoformat()))
    except (ValueError,IndexError):
        # Calendar beyond its supported range must fail closed, never guess weekdays.
        return False

def quote_fresh(quote,now=None):
    if not quote:return False
    now=now or timezone.now()
    source_at=quote.source_at if hasattr(quote,'source_at') else quote['source_at']
    age=(now-source_at).total_seconds()
    return 0<=age<=180 and source_at.astimezone(CN).date()==now.astimezone(CN).date()

def validate_quote(data,now=None,require_fresh=False):
    now=now or timezone.now()
    if data.get('symbol')!='518880' or not D('0.001')<=data['price']<=D('1000'):
        raise ValueError('标的或价格异常')
    at=data['source_at']
    if at.tzinfo is None or (at-now).total_seconds()>0 or (now-at)>timedelta(days=10):
        raise ValueError('源时间异常')
    prev=data.get('previous_close')
    if prev is not None and (prev<=0 or abs(data['price']/prev-1)>D('0.12')):
        raise ValueError('价格变化超出校验范围')
    if require_fresh and not quote_fresh(data,now):
        raise ValueError('行情过期')
    return data

def parse_eastmoney(payload):
    d=payload.get('data') or {}
    if d.get('f57')!='518880':raise ValueError('标的错误')
    scale=10**int(d['f59'])
    if scale!=1000:raise ValueError('报价精度异常')
    return {'symbol':'518880','price':D(str(d['f43']))/scale,'previous_close':D(str(d['f60']))/scale,'source':'eastmoney','source_at':datetime.fromtimestamp(int(d['f86']),tz=CN)}

def fetch_eastmoney():
    response=requests.get('https://push2.eastmoney.com/api/qt/stock/get',params={'secid':'1.518880','fields':'f43,f57,f59,f60,f86'},headers=HEADERS,timeout=(4,8))
    response.raise_for_status()
    return parse_eastmoney(response.json())

def parse_sina(raw):
    match=re.search(r'var hq_str_sh518880="([^"]*)";',raw)
    if not match:raise ValueError('未找到518880报价')
    fields=match.group(1).split(',')
    if len(fields)<32:raise ValueError('报价字段不全')
    return {'symbol':'518880','price':D(fields[3]),'previous_close':D(fields[2]),'source':'sina','source_at':datetime.fromisoformat(fields[30]+'T'+fields[31]).replace(tzinfo=CN)}

def fetch_sina():
    response=requests.get('https://hq.sinajs.cn/list=sh518880',headers=HEADERS,timeout=(4,8))
    response.raise_for_status();response.encoding='gb18030'
    return parse_sina(response.text)

def collect_quotes(now=None):
    snapshot=now
    now=now or timezone.now()
    open_now=is_trading(now)
    state=SystemState.objects.filter(pk='market').values_list('value',flat=True).first() or {}
    selected=None;primary=None;failures=[]
    try:
        primary=validate_quote(fetch_eastmoney(),snapshot or timezone.now(),require_fresh=open_now)
        primary_ok=int(state.get('primary_ok',0))+1
    except (requests.RequestException,ValueError,TypeError,KeyError,OverflowError,InvalidOperation):
        primary_ok=0;failures.append('主源本次未通过校验')
    if primary and (state.get('source')!='sina' or primary_ok>=2):
        selected=primary
    else:
        try:selected=validate_quote(fetch_sina(),snapshot or timezone.now(),require_fresh=open_now)
        except (requests.RequestException,ValueError,TypeError,KeyError,OverflowError,InvalidOperation):
            failures.append('备源本次未通过校验');selected=primary
    now=snapshot or timezone.now()
    if selected:
        previous=Quote.objects.order_by('-source_at').first()
        if not previous or selected['source_at']>=previous.source_at:
            if not previous or previous.source_at!=selected['source_at'] or previous.source!=selected['source'] or previous.price!=selected['price']:
                Quote.objects.create(**selected)
            at=selected['source_at'].replace(second=0,microsecond=0)
            if is_trading(selected['source_at']):
                existing=Minute.objects.filter(at=at).first()
                if not existing or existing.source!='eastmoney-minute':
                    Minute.objects.update_or_create(at=at,defaults={'price':selected['price'],'source':selected['source']+'-sample'})
        state.update({'source':selected['source'],'message':'行情已更新' if quote_fresh(selected,now) else '非交易时段，显示最后报价'})
    else:
        state.update({'message':'免费主备行情均未通过校验，到价提醒暂停'})
    state.update({'primary_ok':primary_ok,'checked_at':now.isoformat(),'failures':failures,'available':selected is not None})
    SystemState.objects.update_or_create(key='market',defaults={'value':state})
    Quote.objects.filter(source_at__lt=now-timedelta(days=10)).delete()
    Minute.objects.filter(at__lt=now-timedelta(days=7)).delete()
    return selected

def collect_minutes(now=None):
    now=now or timezone.now()
    try:
        response=requests.get('https://push2his.eastmoney.com/api/qt/stock/trends2/get',params={'secid':'1.518880','fields1':'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11','fields2':'f51,f52,f53,f54,f55,f56,f57,f58','ndays':'1','iscr':'0','iscca':'0'},headers=HEADERS,timeout=(4,8))
        response.raise_for_status();data=response.json().get('data') or {}
        if str(data.get('code'))!='518880':raise ValueError('标的错误')
        for line in data.get('trends',[]):
            f=line.split(',');at=datetime.fromisoformat(f[0]).replace(tzinfo=CN);price=D(f[2])
            if at.astimezone(CN).date()!=now.astimezone(CN).date() or at>now or not D('0.001')<=price<=1000 or not is_trading(at):continue
            Minute.objects.update_or_create(at=at,defaults={'price':price,'source':'eastmoney-minute'})
    except (requests.RequestException,ValueError,TypeError,KeyError,IndexError,InvalidOperation):
        return False
    return True

def market_data():
    now=timezone.now();today=now.astimezone(CN).date();q=Quote.objects.order_by('-source_at','-pk').first()
    state=SystemState.objects.filter(pk='market').values_list('value',flat=True).first() or {}
    fresh=quote_fresh(q,now) and is_trading(now) and state.get('available',True)
    start=datetime.combine(today,time.min,tzinfo=CN)
    points=Minute.objects.filter(at__gte=start,at__lt=start+timedelta(days=1)).order_by('at')
    sampled=points.exclude(source='eastmoney-minute').exists()
    try:calendar_until=str(trading_calendar().last_session.date())
    except Exception:calendar_until='不可用'
    calendar_valid=calendar_until!='不可用' and str(today)<=calendar_until
    message=state.get('message','等待首次采集；行情未就绪时到价提醒暂停')
    if not calendar_valid:message='交易日历未覆盖当前日期，请联系维护者更新；到价提醒暂停'
    if settings.PAUSE_NOTIFICATIONS:message='维护模式：自动提醒已暂停，可核对账目及计划'
    return {'quote':{'price':str(q.price),'source':q.source,'source_at':q.source_at,'fetched_at':q.fetched_at} if q else None,'fresh':fresh and calendar_valid and not settings.PAUSE_NOTIFICATIONS,'session_open':is_trading(now),'message':message,'calendar_until':calendar_until,'notifications_paused':settings.PAUSE_NOTIFICATIONS,'change_percent':str((q.price/q.previous_close-1)*100) if q and q.previous_close else None,'curve_date':str(today),'points':[{'at':m.at,'price':str(m.price)} for m in points],'curve_note':'含采集时点数据；缺失区间留空，不是完整分钟历史。' if sampled else '显示今天已取得的分钟数据；缺失区间留空。'}
