"""One set of filters and effective-value totals for screens and exports."""
from datetime import date, datetime, time
from decimal import Decimal as D
from zoneinfo import ZoneInfo

from django.db import transaction
from rest_framework import serializers as s

from core.common import BusinessError
from core.ledger import cash_round, effective_payloads
from core.models import Entry, User


@transaction.atomic
def selected_entries(user, params):
    kind = s.ChoiceField(choices=['ALL', 'BUY', 'SELL', 'CASH', 'CORRECTED', 'CORRECTION']).run_validation(params.get('kind', 'ALL'))
    start = s.DateField().run_validation(params['start']) if params.get('start') else None
    end = s.DateField().run_validation(params['end']) if params.get('end') else None
    if start and end and start > end:
        raise BusinessError('开始日期不能晚于结束日期')
    User.objects.select_for_update().get(pk=user.pk)
    replacements = effective_payloads(Entry.objects.filter(user=user, kind='CORRECTION').order_by('id'))
    query = Entry.objects.filter(user=user).order_by('-id')
    cn = ZoneInfo('Asia/Shanghai')
    if start and start > date.min:
        query = query.filter(created_at__gte=datetime.combine(start, time.min, cn))
    if end:
        query = query.filter(created_at__lte=datetime.combine(end, time.max, cn))
    rows = []
    totals = {'buy_amount': D(0), 'sell_amount': D(0), 'fees': D(0), 'cash_change': D(0)}
    for row in query.iterator():
        payload = replacements.get(row.pk, row.payload)
        if kind in ('BUY', 'SELL') and (row.kind != 'TRADE' or payload.get('side') != kind):
            continue
        if kind == 'CORRECTED' and row.pk not in replacements:
            continue
        if kind in ('CASH', 'CORRECTION') and row.kind != kind:
            continue
        rows.append(row)
        if row.kind == 'TRADE':
            totals['buy_amount' if payload['side'] == 'BUY' else 'sell_amount'] += cash_round(D(payload['price']) * int(payload['quantity']))
            totals['fees'] += D(payload['fee'])
        elif row.kind == 'CASH':
            totals['cash_change'] += D(payload['amount'])
    return rows, replacements, {key: str(value) for key, value in totals.items()}
