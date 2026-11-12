"""Read-only tools using the same recording-order calculations as the ledger."""
from decimal import Decimal as D

from django.utils import timezone
from rest_framework.fields import DateTimeField

from core.common import clean_json
from core.ledger import effective_payloads, ledger_steps, position_snapshot
from core.models import Entry


def cash_summary(rows):
    external, result, unknown = D(0), D(0), 0
    for row in rows:
        if row.kind != 'CASH':
            continue
        category = row.payload.get('category', 'UNCLASSIFIED')
        amount = D(row.payload['amount'])
        if category in ('DEPOSIT', 'WITHDRAW'):
            external += amount
        elif category in ('INCOME', 'EXPENSE'):
            result += amount
        else:
            unknown += 1
    return {'net_contributions': str(external), 'cash_result': str(result), 'unclassified_count': unknown}


def calculated_balances(account, rows=None):
    for _, _, cash, shares, basis, realized in ledger_steps(account, rows):
        pass
    return {'cash': cash, 'shares': shares, 'cost_basis': basis, 'realized': realized}


def reconcile(account, rows):
    calculated = calculated_balances(account, rows)
    differences = {key: {'stored': str(getattr(account, key)), 'calculated': str(value)}
                   for key, value in calculated.items() if getattr(account, key) != value}
    return {'consistent': not differences, 'differences': differences,
            'ledger_revision': rows[-1].pk if rows else 0, 'checked_at': timezone.now()}


def entry_preview(account, rows, data, corrects=None):
    original_revision = rows[-1].pk if rows else 0
    simulated = Entry(pk=original_revision + 1, user_id=account.user_id,
                      kind='CORRECTION' if corrects else 'TRADE', corrects=corrects,
                      payload=clean_json(data))
    after = calculated_balances(account, [*rows, simulated])
    replacements = effective_payloads(rows)
    previous_times = [DateTimeField().run_validation(replacements.get(row.pk, row.payload)['occurred_at'])
                      for row in rows if row.kind == 'TRADE' and row.pk != getattr(corrects, 'pk', None)]
    backdated = bool(previous_times and data['occurred_at'] < max(previous_times))
    return {'before': position_snapshot(account.shares, account.cash, account.cost_basis),
            'after': position_snapshot(after['shares'], after['cash'], after['cost_basis']),
            'realized_before': str(account.realized), 'realized_after': str(after['realized']),
            'ledger_revision': original_revision, 'backdated': backdated,
            'calculated_at': timezone.now(), 'recording_order': True}
