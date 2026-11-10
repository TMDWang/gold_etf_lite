from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from core.ledger import initialize, post_entry
from core.models import Entry, User


class HoldingToolsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('holding-owner', fee_rate=0, fee_minimum=1, fee_extra=0)
        self.account = initialize(self.user, {'budget': '5000', 'cash': '2000', 'shares': 150, 'unit_cost': '4.123456'})
        self.client = APIClient()
        self.client.force_login(self.user)

    def trade(self, side, quantity, price, fee='1'):
        return {'side': side, 'quantity': quantity, 'price': price, 'fee': fee,
                'occurred_at': self.account.initialized_at.isoformat()}

    def test_sell_preview_matches_the_result_of_recording_a_partial_sale(self):
        request = {'price': '4.501', 'quantity': 100}
        response = self.client.post('/api/account/sell-preview/', request, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        preview = response.json()
        self.assertEqual(Decimal(preview['net']), Decimal('449.10'))
        self.assertEqual(preview['after']['shares'], 50)
        self.assertEqual(Entry.objects.count(), 0)
        post_entry(self.user, self.trade('SELL', 100, '4.501'), 'sale')
        self.account.refresh_from_db()
        self.assertEqual(Decimal(preview['after']['cash']), self.account.cash)
        self.assertEqual(Decimal(preview['after']['cost_basis']), self.account.cost_basis)
        self.assertEqual(Decimal(preview['realized']), self.account.realized)

    def test_buy_budget_includes_fees_and_rounds_down_to_whole_lots(self):
        response = self.client.post('/api/account/buy-preview/', {'price':'4.500', 'budget':'900.99'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['quantity'], 100)
        self.assertEqual(Decimal(response.json()['total']), Decimal('451'))
        response = self.client.post('/api/account/buy-preview/', {'price':'4.500', 'budget':'901'}, format='json')
        self.assertEqual(response.json()['quantity'], 200)

    def test_odd_lot_is_only_allowed_when_selling_all(self):
        url = '/api/account/sell-preview/'
        for quantity in [50, 200]:
            self.assertEqual(self.client.post(url, {'price':'4', 'quantity':quantity, 'fee':'0'}, format='json').status_code, 400)
        response = self.client.post(url, {'price':'4', 'quantity':150, 'fee':'0'}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()['after']['unit_cost'])
        self.assertLess(Decimal(response.json()['realized']), 0)

    def test_history_reflects_effective_corrections_in_ledger_order_and_is_private(self):
        original, _ = post_entry(self.user, self.trade('BUY', 100, '4.400'), 'buy')
        post_entry(self.user, {'reason':'券商价格核对', 'replacement':self.trade('BUY', 200, '4.400')},
                   'fix', kind='CORRECTION', corrects_id=original.pk)
        post_entry(self.user, self.trade('SELL', 100, '4.300'), 'sell')
        response = self.client.get('/api/account/holding-history/')
        self.assertEqual(response.status_code, 200, response.content)
        points = response.json()['points']
        self.assertEqual([point['shares'] for point in points], [150, 350, 250])
        self.assertEqual(points[1]['id'], original.pk)
        self.assertEqual(points[1]['quantity'], 200)
        self.client.force_login(User.objects.create_user('another'))
        self.assertEqual(self.client.get('/api/account/holding-history/').json()['points'], [])
