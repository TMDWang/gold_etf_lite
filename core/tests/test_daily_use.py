from datetime import datetime, timedelta
from decimal import Decimal as D
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase
from rest_framework.test import APIClient

from core.ledger import initialize, post_entry
from core.models import Account, Entry, Episode, Plan, Quote, User

CN = ZoneInfo('Asia/Shanghai')
START = datetime(2026, 11, 9, 9, 0, tzinfo=CN)


class DailyUseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('daily-owner', fee_rate=0, fee_minimum=1, fee_extra=0)
        with patch('django.utils.timezone.now', return_value=START):
            self.account = initialize(self.user, {'budget':'5000','cash':'1000','shares':200,'unit_cost':'4'})
        self.client = APIClient()
        self.client.force_login(self.user)

    def trade(self, key='trade', **changes):
        data = {'side':'BUY','price':'3.000','quantity':100,'fee':'1',
                'occurred_at':START.isoformat()}
        data.update(changes)
        return post_entry(self.user, data, key)[0]

    def test_reconciliation_reports_differences_without_repairing_or_leaking(self):
        self.trade()
        Account.objects.filter(pk=self.account.pk).update(cash=123)
        response = self.client.get('/api/account/reconciliation/?user_id=999')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['consistent'])
        self.assertEqual(D(response.json()['differences']['cash']['calculated']), D('699'))
        self.account.refresh_from_db()
        self.assertEqual(self.account.cash, 123)
        admin = User.objects.create_user('other-admin', is_app_admin=True)
        self.client.force_login(admin)
        self.assertEqual(self.client.get('/api/account/reconciliation/').status_code, 400)

    def test_entry_preview_preserves_recording_order_and_rejects_stale_write(self):
        self.trade()
        body = {'side':'SELL','price':'5.000','quantity':100,'fee':'1',
                'occurred_at':(START-timedelta(days=1)).isoformat()}
        response = self.client.post('/api/account/entry-preview/', body, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()
        self.assertTrue(result['backdated'])
        self.assertEqual(result['after']['shares'], 200)
        self.assertEqual(Entry.objects.count(), 1)
        self.trade('another')
        body['ledger_revision'] = result['ledger_revision']
        response = self.client.post('/api/entries/', body, format='json', HTTP_IDEMPOTENCY_KEY='stale')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Entry.objects.count(), 2)

    def test_lost_write_response_is_recognized_before_retrying_confirmation(self):
        row = self.trade('lost-response')
        data = {**row.payload, 'confirmation_key':'lost-response'}
        response = self.client.post('/api/account/entry-preview/', data, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['already_recorded'])
        data['fee'] = '2'
        self.assertEqual(self.client.post('/api/account/entry-preview/', data, format='json').status_code, 409)
        self.assertEqual(Entry.objects.count(), 1)

    def test_manual_fee_estimate_reads_saved_settings_and_uses_decimal_rounding(self):
        User.objects.filter(pk=self.user.pk).update(fee_rate=D('0.000005'), fee_minimum=0, fee_extra=0)
        response = self.client.post('/api/account/fee-preview/', {'price':'4.000','quantity':137}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(D(response.json()['fee']), D('0.01'))
        self.assertEqual(Entry.objects.count(), 0)

    def test_cash_categories_validate_sign_and_old_calls_remain_unclassified(self):
        post_entry(self.user, {'amount':'20','reason':'旧记录'}, 'old', kind='CASH')
        response = self.client.post('/api/cash/', {'amount':'-20','reason':'方向错','category':'DEPOSIT'},
                                    format='json', HTTP_IDEMPOTENCY_KEY='bad')
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/api/cash/', {'amount':'10','reason':'分红','category':'INCOME'},
                                    format='json', HTTP_IDEMPOTENCY_KEY='income')
        self.assertEqual(response.status_code, 201)
        data = self.client.get('/api/account/').json()
        self.assertEqual(data['unclassified_count'], 1)
        self.assertIsNone(data['investment_profit'])
        self.assertEqual(D(data['cash_result']), 10)

    def test_filters_use_effective_corrections_and_do_not_count_revisions_twice(self):
        original = self.trade()
        corrected = dict(original.payload, price='2.000')
        post_entry(self.user, {'reason':'价格修正','replacement':corrected}, 'fix',
                   kind='CORRECTION', corrects_id=original.pk)
        response = self.client.get('/api/entries/?kind=BUY')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 1)
        self.assertEqual(D(response.json()['summary']['buy_amount']), 200)
        self.assertEqual(D(response.json()['summary']['fees']), 1)
        self.assertEqual(self.client.get('/api/entries/?kind=CORRECTED').json()['count'], 1)
        self.assertEqual(self.client.get('/api/entries/?start=2026-11-12&end=2026-11-01').status_code, 400)
        self.assertEqual(self.client.get('/api/entries/?kind=bogus').status_code, 400)
        self.assertIn('2.000', self.client.get('/api/entries/export.csv?kind=BUY').content.decode('utf-8-sig'))

    def test_filtered_export_keeps_effective_side_and_time_after_direction_correction(self):
        import csv
        import io
        original = self.trade()
        corrected = dict(original.payload, side='SELL', price='5.000', occurred_at=START.replace(hour=11).isoformat())
        post_entry(self.user, {'reason':'方向修正','replacement':corrected}, 'direction-fix',
                   kind='CORRECTION', corrects_id=original.pk)
        response = self.client.get('/api/entries/export.csv?kind=SELL')
        rows = list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['有效方向'], 'SELL')
        self.assertEqual(datetime.fromisoformat(rows[0]['有效成交时间']), datetime.fromisoformat(corrected['occurred_at']))
        self.assertEqual(rows[0]['方向'], 'BUY')

    def test_ignore_old_episode_cannot_stop_new_episode_or_new_plan_version(self):
        plan = Plan.objects.create(user=self.user, side='BUY', amount=1000, target_price=4)
        old = Episode.objects.create(plan=plan, version=1, number=1, status='CLOSED', next_at=START)
        current = Episode.objects.create(plan=plan, version=1, number=2, status='OPEN', next_at=START)
        response = self.client.post(f'/api/episodes/{old.pk}/ignore/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        current.refresh_from_db()
        self.assertEqual(current.status, 'OPEN')
        plan.version = 2
        plan.save(update_fields=['version'])
        latest = Episode.objects.create(plan=plan, version=2, number=3, status='OPEN', next_at=START)
        self.client.post(f'/api/episodes/{current.pk}/ignore/', {}, format='json')
        latest.refresh_from_db()
        self.assertEqual(latest.status, 'OPEN')

    def test_alert_status_separates_rest_from_network_and_shows_distance(self):
        plan = Plan.objects.create(user=self.user, side='INFO', alert_kind='PRICE',
                                   alert_threshold='3.800', direction='BELOW')
        now = START.replace(hour=10)
        Quote.objects.create(price='4.000', previous_close='4', source='test', source_at=now)
        with patch('django.utils.timezone.now', return_value=now):
            data = self.client.get('/api/alerts/').json()[0]
        self.assertEqual(D(data['evaluation']['gap']), D('0.200'))
        self.assertEqual(data['evaluation']['state'], 'WAITING')
        with patch('django.utils.timezone.now', return_value=now.replace(hour=12)):
            data = self.client.get('/api/alerts/').json()[0]
        self.assertEqual(data['evaluation']['state'], 'CLOSED')
        self.assertIn('休市', data['evaluation']['reason'])

    def test_sell_distance_uses_upward_target_even_when_default_direction_is_below(self):
        from core.activity import rule_status
        now = START.replace(hour=10)
        quote = Quote.objects.create(price='4.000', source='test', source_at=now)
        plan = Plan.objects.create(user=self.user, side='SELL', target_price=D('5.000'), quantity=100)
        result = rule_status(plan, self.account, self.user, quote, now)
        self.assertEqual(D(result['gap']), 1)

    def test_snooze_does_not_create_new_round_and_expires_at_beijing_midnight(self):
        from core.monitor import evaluate_all
        now = START.replace(hour=10)
        plan = Plan.objects.create(user=self.user, side='INFO', alert_kind='PRICE',
                                   alert_threshold='4.500', direction='BELOW')
        Quote.objects.create(price='4', source='test', source_at=now)
        evaluate_all(now)
        with patch('django.utils.timezone.now', return_value=now):
            response = self.client.post(f'/api/alerts/{plan.pk}/ignore/', {'scope':'TODAY'}, format='json')
        self.assertEqual(response.status_code, 200)
        plan.refresh_from_db()
        self.assertEqual(plan.snoozed_until.astimezone(CN), now.replace(hour=0)+timedelta(days=1))
        evaluate_all(now+timedelta(minutes=1))
        self.assertEqual(Episode.objects.count(), 1)
        response = self.client.get('/api/reminders/history/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'][0]['scope'], 'PERSONAL')

    def test_reports_exclude_deposit_from_return_and_keep_correction_revisions(self):
        from core.reports import settle_reports
        from core.models import DailyReport
        day1 = START.replace(hour=15, minute=10)
        Quote.objects.create(price='4', source='test', source_at=day1.replace(minute=0))
        Quote.objects.update(fetched_at=day1)
        settle_reports(self.user, day1)
        day2 = day1+timedelta(days=1)
        with patch('django.utils.timezone.now', return_value=day2.replace(hour=10)):
            post_entry(self.user, {'amount':'100','reason':'转入','category':'DEPOSIT'}, 'deposit', kind='CASH')
            trade = self.trade(price='4.000')
        Quote.objects.create(price='5', source='test', source_at=day2.replace(minute=0))
        Quote.objects.filter(source_at=day2.replace(minute=0)).update(fetched_at=day2)
        settle_reports(self.user, day2)
        report = DailyReport.objects.filter(user=self.user, day=day2.date()).latest('revision')
        self.assertEqual(D(report.data['daily_profit']), 299)
        count = DailyReport.objects.count()
        settle_reports(self.user, day2)
        self.assertEqual(DailyReport.objects.count(), count)
        with patch('django.utils.timezone.now', return_value=day2.replace(hour=16)):
            post_entry(self.user, {'reason':'改费用','replacement':dict(trade.payload, fee='2')},
                       'correction', kind='CORRECTION', corrects_id=trade.pk)
        settle_reports(self.user, day2.replace(hour=16))
        latest = DailyReport.objects.filter(user=self.user, day=day2.date()).latest('revision')
        self.assertGreater(latest.revision, report.revision)
        self.assertEqual(D(latest.data['daily_profit']), 298)

    def test_reports_missing_close_and_unknown_cash_do_not_invent_profit(self):
        from core.reports import settle_reports
        from core.models import DailyReport
        with patch('django.utils.timezone.now', return_value=START.replace(hour=10)):
            post_entry(self.user, {'amount':'100','reason':'未分类'}, 'unknown', kind='CASH')
        now = START.replace(hour=16)
        Quote.objects.create(price='8', source='old', source_at=now-timedelta(days=1))
        settle_reports(self.user, now)
        report = DailyReport.objects.get(user=self.user)
        self.assertIsNone(report.data['equity'])
        self.assertIsNone(report.data['daily_profit'])
        self.assertEqual(report.data['unclassified_count'], 1)
        self.assertEqual(self.client.get('/api/account/reports/').json()['count'], 1)

    def test_setup_and_history_do_not_read_another_users_test_or_token(self):
        from core.models import Delivery
        other = User.objects.create_user('someone-else', token_encrypted='secret')
        Delivery.objects.create(user=other, status='SENT', kind='TEST')
        response = self.client.get('/api/account/setup/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['fees_ready'])
        self.assertFalse(response.json()['push_ready'])
        self.assertFalse(response.json()['test_ready'])
        self.assertEqual(self.client.get('/api/reminders/history/').json()['count'], 0)

    def test_report_revision_endpoint_is_owner_scoped(self):
        from core.models import DailyReport
        DailyReport.objects.create(user=self.user, day=START.date(), revision=1, fingerprint='x', data={'equity':'1800'})
        DailyReport.objects.create(user=self.user, day=START.date(), revision=2, fingerprint='y', data={'equity':'1801'})
        response = self.client.get('/api/account/reports/?day=2026-11-09')
        self.assertEqual([item['revision'] for item in response.json()['results']], [2, 1])
        stranger = User.objects.create_user('report-admin', is_app_admin=True)
        self.client.force_login(stranger)
        self.assertEqual(self.client.get('/api/account/reports/?day=2026-11-09&user_id='+str(self.user.pk)).json()['count'], 0)

    def test_saved_closing_evidence_survives_quote_retention_and_recalculation(self):
        from core.reports import settle_reports
        from core.models import DailyReport, Minute
        now = START.replace(hour=16)
        with patch('django.utils.timezone.now', return_value=now):
            Quote.objects.create(price='4.100', source='test', source_at=now.replace(hour=15))
        settle_reports(self.user, now)
        first = DailyReport.objects.get(user=self.user)
        Quote.objects.all().delete()
        Minute.objects.all().delete()
        settle_reports(self.user, now)
        self.assertEqual(DailyReport.objects.filter(user=self.user).count(), 1)
        self.assertEqual(DailyReport.objects.latest('revision').data['equity'], first.data['equity'])
