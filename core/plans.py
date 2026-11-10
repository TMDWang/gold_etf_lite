from decimal import Decimal as D, ROUND_CEILING
from core.ledger import cash_round

ALERT_LABELS = {
    'PRICE': '价格', 'PCT_CLOSE': '相对昨收涨跌幅', 'PCT_COST': '相对持仓成本涨跌幅',
    'PCT_OPEN': '相对今日首个采样涨跌幅', 'DRAWDOWN': '自今日已采样高点回撤', 'MOVE_10M': '近10分钟价格变化',
}
PRICE_ALERT_KINDS = {'PRICE', 'MOVE_10M'}
INTRADAY_ALERT_KINDS = {'PCT_OPEN', 'DRAWDOWN', 'MOVE_10M'}

def estimated_fee(user,gross):
    if any(x is None for x in (user.fee_rate,user.fee_minimum,user.fee_extra)):
        return None
    # Conservative round up for predictions; actual accounting uses the user's real fee.
    return (max(D(user.fee_minimum),gross*D(user.fee_rate))+D(user.fee_extra)).quantize(D('0.01'),rounding=ROUND_CEILING)

def affordable_quantity(price, budget, fee_for, max_quantity=None):
    low, high = 0, int(budget / price) // 100
    if max_quantity is not None:
        high = min(high, max_quantity // 100)
    while low < high:
        middle = (low + high + 1) // 2
        gross = cash_round(price * middle * 100)
        if gross + fee_for(gross) <= budget:
            low = middle
        else:
            high = middle - 1
    return low * 100


def minimum_sale_price(quantity, cost, fee_for, target_pct=0):
    target_net = cost * (1 + D(target_pct) / 100)

    def covers(ticks):
        gross = cash_round(D(ticks) * D('0.001') * quantity)
        return gross - fee_for(gross) >= target_net

    low, high = 1, 1000000
    if not covers(high):
        return None
    while low < high:
        mid = (low + high) // 2
        if covers(mid):
            high = mid
        else:
            low = mid + 1
    return D(low) * D('0.001')


def evaluate(plan,account,price,user,quote=None):
    result={'eligible':False,'reason':'等待有效行情','quantity':0,'price':str(price) if price else None,'net':None}
    if plan.side=='INFO':
        if not price:return result
        price=D(price)
        kind = plan.alert_kind
        if kind == 'PRICE':
            value = price
        else:
            if kind == 'PCT_CLOSE':
                basis = quote.previous_close if quote else None
            elif kind == 'PCT_COST':
                basis = D(account.cost_basis) / account.shares if account and account.initialized_at and account.shares else None
            elif quote and kind in INTRADAY_ALERT_KINDS:
                from core.market import intraday_reference
                basis = intraday_reference(kind, quote)
            else:
                basis = None
            if basis is None or basis <= 0:
                result['reason'] = '缺少有效比较基准，暂不提醒'
                if kind in INTRADAY_ALERT_KINDS:
                    result['comparison_missing'] = True
                return result
            if kind == 'MOVE_10M':
                value = price - basis
            elif kind == 'DRAWDOWN':
                value = (1 - price / basis) * 100
            else:
                value = (price / basis - 1) * 100
        result['value']=str(value)
        result['eligible']=value>=plan.alert_threshold if plan.direction=='ABOVE' else value<=plan.alert_threshold
        result['reason']='行情条件已达到' if result['eligible'] else '尚未达到行情条件'
        return result
    if not price or not account.initialized_at:
        result['reason']='请先初始化账本' if not account.initialized_at else '等待有效行情'
        return result
    price=D(price)
    if estimated_fee(user,D(0)) is None:
        result['reason']='请先在设置补齐券商费用参数';return result
    if plan.side=='BUY':
        limit=min(plan.amount,account.cash,max(D(0),account.budget-account.cost_basis))
        q = affordable_quantity(price, limit, lambda gross: estimated_fee(user, gross))
        result['quantity'] = q
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
