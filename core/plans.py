from decimal import Decimal as D, ROUND_CEILING
from core.ledger import cash_round

def estimated_fee(user,gross):
    if any(x is None for x in (user.fee_rate,user.fee_minimum,user.fee_extra)):
        return None
    # Conservative round up for predictions; actual accounting uses the user's real fee.
    return (max(D(user.fee_minimum),gross*D(user.fee_rate))+D(user.fee_extra)).quantize(D('0.01'),rounding=ROUND_CEILING)

def evaluate(plan,account,price,user):
    result={'eligible':False,'reason':'等待有效行情','quantity':0,'price':str(price) if price else None,'net':None}
    if not price or not account.initialized_at:
        result['reason']='请先初始化账本' if not account.initialized_at else '等待有效行情'
        return result
    price=D(price)
    if estimated_fee(user,D(0)) is None:
        result['reason']='请先在设置补齐券商费用参数';return result
    if plan.side=='BUY':
        limit=min(plan.amount,account.cash,max(D(0),account.budget-account.cost_basis))
        hi=int(limit/price)//100
        lo=0
        while lo<hi:
            mid=(lo+hi+1)//2
            gross=price*(mid*100)
            if gross+estimated_fee(user,gross)<=limit: lo=mid
            else: hi=mid-1
        q=lo*100;result['quantity']=q
        if q<100:
            result['reason']='现金、预算或含费金额不足 100 份';return result
        met=price<=plan.target_price if plan.direction=='BELOW' else price>=plan.target_price
        result['eligible']=met;result['reason']=('跌到买入条件已达到' if plan.direction=='BELOW' else '涨到买入条件已达到') if met else '尚未到达买入目标价'
        return result
    q=account.shares if plan.sell_all else plan.quantity
    result['quantity']=q or 0
    if not q or q>account.shares or (q%100 and q!=account.shares):
        result['reason']='卖出份额超过持仓或不符合交易单位';return result
    if account.shares<=0 or account.cost_basis<=0:
        result['reason']='持仓成本无法确认，暂停不亏损卖出提醒';return result
    basis=account.cost_basis*D(q)/account.shares
    net=cash_round(price*q)-basis-estimated_fee(user,price*q)
    pct=net/basis*100
    result['net']=str(net);result['net_percent']=str(pct)
    if net<0:
        result['reason']='预计扣费后仍亏损，暂不提醒';return result
    met=(plan.target_price is not None and price>=plan.target_price) or (plan.target_profit is not None and pct>=plan.target_profit)
    result['eligible']=bool(met);result['reason']='卖出目标已达到，预计扣费后不亏损' if met else '尚未到达卖出目标'
    return result
