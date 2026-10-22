from rest_framework import serializers as s
from decimal import Decimal as D

class InitializeSerializer(s.Serializer):
    budget = s.DecimalField(max_digits=18, decimal_places=2, min_value=0)
    cash = s.DecimalField(max_digits=18, decimal_places=2, min_value=0)
    shares = s.IntegerField(min_value=0, max_value=100000000)
    unit_cost = s.DecimalField(max_digits=12, decimal_places=6, min_value=0)

    def validate(self, data):
        if data['shares'] and data['unit_cost'] <= 0:
            raise s.ValidationError('已有持仓请先从券商核对并填写大于 0 的每份成本；未知成本不能当成零成本入账')
        return data

class TradeSerializer(s.Serializer):
    side = s.ChoiceField(choices=['BUY', 'SELL'])
    quantity = s.IntegerField(min_value=1, max_value=100000000)
    price = s.DecimalField(max_digits=10, decimal_places=3, min_value=D('0.001'), max_value=D('1000'))
    fee = s.DecimalField(max_digits=14, decimal_places=2, min_value=0)
    occurred_at = s.DateTimeField()
    plan_id = s.IntegerField(required=False)
    plan_version = s.IntegerField(required=False)

    def validate(self, data):
        from django.utils import timezone
        from datetime import timedelta
        if data['side'] == 'BUY' and data['quantity'] % 100:
            raise s.ValidationError('买入份额必须是 100 的整数倍')
        if data['fee'] > data['price'] * data['quantity']:
            raise s.ValidationError('手续费不能超过成交金额，请核对')
        if data['occurred_at'] > timezone.now() + timedelta(minutes=5):
            raise s.ValidationError('成交时间不能晚于当前时间')
        if data.get('plan_id') and not data.get('plan_version'):
            raise s.ValidationError('请刷新计划后再确认')
        return data

class CashSerializer(s.Serializer):
    amount = s.DecimalField(max_digits=18, decimal_places=2)
    reason = s.CharField(max_length=200)

    def validate_amount(self, amount):
        if not amount:
            raise s.ValidationError('金额不能为 0')
        return amount

class PlanSerializer(s.Serializer):
    side = s.ChoiceField(choices=['BUY', 'SELL'])
    direction = s.ChoiceField(choices=['BELOW', 'ABOVE'], default='BELOW')
    target_price = s.DecimalField(max_digits=10, decimal_places=3, min_value=D('0.001'), max_value=D('1000'), allow_null=True, required=False)
    target_profit = s.DecimalField(max_digits=9, decimal_places=4, min_value=0, max_value=D('10000'), allow_null=True, required=False)
    amount = s.DecimalField(max_digits=18, decimal_places=2, min_value=D('0.01'), allow_null=True, required=False)
    quantity = s.IntegerField(min_value=1, max_value=100000000, allow_null=True, required=False)
    sell_all = s.BooleanField(default=False)

    def validate(self, d):
        if d['side'] == 'BUY' and (not d.get('target_price') or not d.get('amount')):
            raise s.ValidationError('买入须填写目标价和含费金额上限')
        if d['side'] == 'SELL':
            if not d.get('target_price') and d.get('target_profit') is None:
                raise s.ValidationError('请填写目标卖出价或本笔目标净收益率')
            if not d.get('sell_all') and not d.get('quantity'):
                raise s.ValidationError('请填写卖出份额或选择全部卖出')
        return d

class SettingsSerializer(s.Serializer):
    fee_rate = s.DecimalField(max_digits=10, decimal_places=8, min_value=0, max_value=D('0.1'), allow_null=True, required=False)
    fee_minimum = s.DecimalField(max_digits=12, decimal_places=2, min_value=0, max_value=D('10000'), allow_null=True, required=False)
    fee_extra = s.DecimalField(max_digits=12, decimal_places=2, min_value=0, max_value=D('10000'), allow_null=True, required=False)
    reminder_minutes = s.IntegerField(min_value=20, max_value=1440, required=False)
    reminder_max = s.IntegerField(min_value=1, max_value=10, required=False)
    push_token = s.RegexField(r'^[a-zA-Z0-9]{20,100}$', required=False, allow_blank=True, write_only=True)
