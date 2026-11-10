from datetime import datetime
from decimal import Decimal as D
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase
from rest_framework.test import APIClient

from core.ledger import initialize, post_entry
from core.models import Entry, Minute, Quote, User
from core.plans import evaluate

NOW = datetime(2026, 11, 10, 10, 0, tzinfo=ZoneInfo('Asia/Shanghai'))


class TransferredToolsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('owner', fee_rate=0, fee_minimum=1, fee_extra=0)
        self.account = initialize(self.user, {'budget':'5000','cash':'1000','shares':200,'unit_cost':'4'})
        self.client = APIClient()
        self.client.force_login(self.user)

    def test_trade_csv_is_private_and_neutralizes_excel_formulas(self):
        post_entry(self.user, {'amount':'10','reason':'=2+2'}, 'owner-cash', kind='CASH')
        stranger = User.objects.create_user('stranger')
        initialize(stranger, {'budget':'5000','cash':'1000','shares':0,'unit_cost':'0'})
        post_entry(stranger, {'amount':'70','reason':'别人的流水'}, 'other-cash', kind='CASH')
        response = self.client.get('/api/entries/export.csv')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'\xef\xbb\xbf'))
        body = response.content.decode('utf-8-sig')
        self.assertIn("'=2+2", body)
        self.assertNotIn('别人的流水', body)
        self.assertIn('no-store', response['Cache-Control'])

    @patch('core.market.timezone.now', return_value=NOW)
    def test_quote_history_filters_date_window_and_future_points(self, _):
        for day, hour in [(7,10),(8,10),(9,10),(10,10),(10,11)]:
            Minute.objects.create(at=NOW.replace(day=day,hour=hour),price=D(day),source='test')
        response = self.client.get('/api/market/history/?days=3')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([D(row['price']) for row in response.json()['points']], [8,9,10])
        self.assertEqual(self.client.get('/api/market/history/?days=30').status_code, 400)

    def test_target_price_is_the_first_tick_covering_fees_and_target(self):
        response = self.client.post('/api/account/sell-preview/', {'price':'4','quantity':100,'target_profit':'2'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(D(response.json()['breakeven_price']), D('4.01'))
        self.assertEqual(D(response.json()['target_price']), D('4.09'))

    def test_batch_sale_deducts_each_fee_and_cannot_exceed_holdings(self):
        url = '/api/account/sell-batch-preview/'
        legs = [{'quantity':100,'price':'4.300'},{'quantity':100,'price':'4.500'}]
        response = self.client.post(url, {'legs':legs}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(D(response.json()['net']), D('878'))
        self.assertEqual(D(response.json()['realized']), D('78'))
        self.assertEqual(response.json()['after']['shares'], 0)
        self.assertFalse(Entry.objects.exists())
        self.assertEqual(self.client.post(url, {'legs':legs+[legs[-1]]}, format='json').status_code, 400)

    def test_daily_drawdown_rule_uses_the_actual_high_and_ignores_future_data(self):
        from core.models import Plan
        for minute, price in [(57,'4.800'),(58,'4.950'),(59,'4.900')]:
            Minute.objects.create(at=NOW.replace(hour=9,minute=minute),price=price,source='test')
        Minute.objects.create(at=NOW.replace(minute=1),price='8.000',source='test')
        Quote.objects.create(price=D('5.000'),source='test',source_at=NOW.replace(hour=9,minute=58))
        quote = Quote.objects.create(price=D('4.850'),source='test',source_at=NOW)
        plan = Plan(side='INFO',alert_kind='DRAWDOWN',direction='ABOVE',alert_threshold=D('3'))
        result = evaluate(plan,self.account,quote.price,self.user,quote=quote)
        self.assertTrue(result['eligible'])
        self.assertEqual(D(result['value']), 3)

    def test_short_move_requires_a_reference_from_the_same_session(self):
        from core.models import Plan
        Minute.objects.create(at=NOW.replace(hour=11,minute=30),price='4.000',source='test')
        quote = Quote(price=D('4.050'),source='test',source_at=NOW.replace(hour=13,minute=5))
        plan = Plan(side='INFO',alert_kind='MOVE_10M',direction='ABOVE',alert_threshold=D('0.03'))
        self.assertFalse(evaluate(plan,self.account,quote.price,self.user,quote=quote)['eligible'])
        Minute.objects.create(at=NOW.replace(hour=13,minute=5),price='4.000',source='test')
        quote.source_at = NOW.replace(hour=13,minute=15)
        result = evaluate(plan,self.account,quote.price,self.user,quote=quote)
        self.assertTrue(result['eligible'])
        self.assertEqual(D(result['value']), D('0.050'))

