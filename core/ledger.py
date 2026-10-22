from decimal import Decimal as D, ROUND_HALF_UP
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from core.models import User, Account, Entry, Plan, Episode, Audit
from core.common import BusinessError, clean_json, digest
from core.serializers import TradeSerializer, CashSerializer, InitializeSerializer

CENT = D('0.01')
MICRO = D('0.000001')

def cash_round(n):
    return n.quantize(CENT, rounding=ROUND_HALF_UP)

def get_account(user):
    return Account.objects.get_or_create(user=user)[0]

def require_initialized(account):
    if not account.initialized_at:
        raise BusinessError('请先初始化现金和持仓')

@transaction.atomic
def initialize(user, data):
    User.objects.select_for_update().get(pk=user.pk)
    account=get_account(user)
    account=Account.objects.select_for_update().get(pk=account.pk)
    if account.initialized_at:
        raise BusinessError('账户已经初始化，后续变化请通过流水记录',409)
    s=InitializeSerializer(data=data); s.is_valid(raise_exception=True); d=s.validated_data
    account.budget=d['budget']; account.initial_cash=account.cash=d['cash']
    account.initial_shares=account.shares=d['shares']
    account.initial_cost=account.cost_basis=(d['unit_cost']*d['shares']).quantize(MICRO)
    account.initialized_at=timezone.now(); account.save()
    Audit.objects.create(actor=user,action='initialize_account',object_id=str(account.pk))
    return account

def effective_payloads(entries):
    replacements={e.corrects_id:e.payload for e in entries if e.kind=='CORRECTION'}
    return replacements

def replay(account):
    rows=list(Entry.objects.filter(user=account.user).order_by('id'))
    replacements=effective_payloads(rows)
    cash, shares, basis, realized=account.initial_cash,account.initial_shares,account.initial_cost,D('0')
    # Recording order is explicit; a correction replaces its target at its original position.
    for row in rows:
        if row.kind=='CORRECTION':
            continue
        d=replacements.get(row.pk,row.payload)
        if row.kind=='CASH':
            cash+=D(d['amount'])
        else:
            q=int(d['quantity']); gross=cash_round(D(d['price'])*q); fee=D(d['fee'])
            if d['side']=='BUY':
                cash-=gross+fee; basis+=gross+fee; shares+=q
            else:
                if q>shares:
                    raise BusinessError(f'第 {row.pk} 笔卖出超过当时持仓，已回滚；请核对流水顺序')
                if q%100 and q != shares:
                    raise BusinessError('不足一手的余份须一次全部卖出')
                transferred=basis if q==shares else (basis*q/shares).quantize(MICRO,rounding=ROUND_HALF_UP)
                basis-=transferred; shares-=q; cash+=gross-fee; realized+=gross-fee-transferred
        if cash<0:
            raise BusinessError(f'第 {row.pk} 笔之后现金不足，已回滚；请先补齐遗漏的资金流水')
        if cash>D('999999999999999999') or basis>D('999999999999999999'):
            raise BusinessError('金额超出本版可记录范围')
    account.cash=cash; account.shares=shares; account.cost_basis=basis; account.realized=realized
    account.save(update_fields=['cash','shares','cost_basis','realized'])

def idempotency(user,key,request_data):
    if not key or len(key)>80:
        raise BusinessError('请携带有效 Idempotency-Key 后再确认')
    fingerprint=digest(request_data)
    existing=Entry.objects.filter(user=user,idempotency_key=key).first()
    if existing:
        if existing.request_hash!=fingerprint:
            raise BusinessError('同一确认标识对应了不同内容，请重新打开表单',409)
        return existing,fingerprint
    return None,fingerprint

@transaction.atomic
def post_entry(user,data,key,kind='TRADE',corrects_id=None):
    user=User.objects.select_for_update().get(pk=user.pk)
    account=get_account(user)
    account=Account.objects.select_for_update().get(pk=account.pk)
    require_initialized(account)
    target=None
    if corrects_id:
        target=get_object_or_404(Entry,user=user,pk=corrects_id,kind='TRADE')
    previous,fingerprint=idempotency(user,key,{'kind':kind,'data':data,'corrects':corrects_id})
    if previous:
        return previous,False
    plan=None
    reason=''
    raw=data
    if kind=='CORRECTION':
        reason=str(data.get('reason','')).strip()
        if not reason or len(reason)>200:
            raise BusinessError('纠错原因须为 1–200 字')
        raw=data.get('replacement',{})
    serializer=CashSerializer(data=raw) if kind=='CASH' else TradeSerializer(data=raw)
    serializer.is_valid(raise_exception=True)
    d=dict(serializer.validated_data)
    plan_id=d.pop('plan_id',None); plan_version=d.pop('plan_version',None)
    if kind=='CORRECTION' and plan_id:
        raise BusinessError('纠错不能重新绑定计划')
    if plan_id:
        plan=get_object_or_404(Plan.objects.select_for_update(),user=user,pk=plan_id)
        if plan.status!='ACTIVE' or plan.version!=plan_version or plan.side!=d['side']:
            raise BusinessError('计划已变化或已结束，请刷新后重新核对',409)
    if kind=='CASH':
        reason=d.pop('reason')
    row=Entry.objects.create(user=user,kind=kind,payload=clean_json(d),idempotency_key=key,request_hash=fingerprint,plan=plan,corrects=target,reason=reason)
    replay(account)
    if plan:
        plan.status='COMPLETED'; plan.save(update_fields=['status','updated_at'])
        Episode.objects.filter(plan=plan,status__in=['OPEN','UNKNOWN']).update(status='CLOSED')
    Audit.objects.create(actor=user,action='record_'+kind.lower(),object_id=str(row.pk))
    return row,True
