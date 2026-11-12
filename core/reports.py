"""Revisioned closing snapshots using registration dates and effective corrections."""
import logging
from datetime import datetime, time, timedelta
from decimal import Decimal as D

from django.db import close_old_connections, transaction
from django.utils import timezone

from core.account_tools import calculated_balances, cash_summary, reconcile
from core.common import BusinessError, clean_json, digest
from core.market import CN, is_trading
from core.models import Account, DailyReport, Entry, Minute, Quote, User

logger = logging.getLogger(__name__)


def close_price(day, now):
    close = datetime.combine(day, time(15), CN)
    earliest = close - timedelta(minutes=1)
    quote = Quote.objects.filter(source_at__gte=earliest, source_at__lte=close,
                                 fetched_at__lte=now).order_by('-source_at', '-pk').first()
    if quote:
        return quote.price, {'price': str(quote.price), 'source': quote.source, 'at': quote.source_at.isoformat()}
    minute = Minute.objects.filter(at__gte=earliest, at__lte=close).order_by('-at').first()
    if minute:
        return minute.price, {'price': str(minute.price), 'source': minute.source, 'at': minute.at.isoformat()}
    return None, None


@transaction.atomic
def settle_reports(user, now=None):
    now = now or timezone.now()
    User.objects.select_for_update().get(pk=user.pk)
    account = Account.objects.select_for_update().filter(user=user).first()
    if not account or not account.initialized_at:
        return []
    rows = list(Entry.objects.filter(user=user, created_at__lte=now).order_by('id'))
    if not reconcile(account, rows)['consistent']:
        raise BusinessError('账目检查发现差异，请核对后再生成日报', 409)
    day = account.initialized_at.astimezone(CN).date()
    last_day = now.astimezone(CN).date()
    existing = {}
    for report in DailyReport.objects.filter(user=user).order_by('day', 'revision'):
        existing[report.day] = report
    previous = None
    generated = []
    while day <= last_day:
        cutoff = datetime.combine(day, time(15), CN)
        if cutoff < account.initialized_at or now < cutoff + timedelta(minutes=5) or not is_trading(cutoff):
            day += timedelta(days=1)
            continue
        originals = [row for row in rows if row.kind != 'CORRECTION' and row.created_at <= cutoff]
        ids = {row.pk for row in originals}
        effective_rows = sorted([*originals, *(row for row in rows if row.kind == 'CORRECTION' and row.corrects_id in ids)], key=lambda row: row.pk)
        balances = calculated_balances(account, effective_rows)
        cash = cash_summary(originals)
        report = existing.get(day)
        price, evidence = close_price(day, now)
        if price is None and report and report.data.get('close_quote'):
            # Closing evidence belongs to the permanent report after raw quote retention.
            evidence = report.data['close_quote']
            price = D(evidence['price'])
        market_value = price * balances['shares'] if price is not None else D(0) if not balances['shares'] else None
        equity = balances['cash'] + market_value if market_value is not None else None
        income = D(cash['cash_result'])
        initial = account.initial_cash + account.initial_cost
        profit = equity - initial - D(cash['net_contributions']) if equity is not None and not cash['unclassified_count'] else None
        daily = None
        previous_data = previous.data if previous else None
        if equity is not None and previous_data and previous_data['equity'] is not None and cash['unclassified_count'] == previous_data['unclassified_count']:
            daily = equity - D(previous_data['equity']) - (D(cash['net_contributions']) - D(previous_data['net_contributions']))
        data = clean_json({'day': day.isoformat(), 'rule': 'RECORDING_ORDER_V1', 'cutoff_at': cutoff,
                           **balances, **cash, 'market_value': market_value, 'equity': equity,
                           'investment_profit': profit, 'daily_profit': daily, 'close_quote': evidence,
                           'valuation_status': 'CASH_ONLY' if not balances['shares'] else 'CLOSE_SAMPLE' if evidence else 'MISSING_CLOSE',
                           'cash_result': income, 'previous_revision': previous.revision if previous else None,
                           'ledger_fingerprint': digest([(row.pk, row.request_hash) for row in effective_rows])})
        fingerprint = digest(data)
        if report is None or report.fingerprint != fingerprint:
            report = DailyReport.objects.create(user=user, day=day, revision=report.revision + 1 if report else 1,
                                                fingerprint=fingerprint, data=data)
            generated.append(report.pk)
        previous = report
        day += timedelta(days=1)
    return generated


def scheduled_reports():
    close_old_connections()
    try:
        for user in User.objects.filter(account__initialized_at__isnull=False).iterator():
            try:
                settle_reports(user)
            except Exception as error:
                logger.error('daily report generation failed (%s)', type(error).__name__)
    finally:
        close_old_connections()
