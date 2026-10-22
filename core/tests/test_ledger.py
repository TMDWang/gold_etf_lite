from decimal import Decimal as D
from django.test import TestCase
from rest_framework.test import APIClient
from core.models import User

class LedgerTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user('alice', password='Example-safe-password42!')
        self.other = User.objects.create_user('bob', password='Example-safe-password42!', is_app_admin=True)
        self.c = APIClient()
        self.c.force_login(self.u)

    def init(self, **kw):
        data = {'budget': '20000', 'cash': '10000', 'shares': 1000, 'unit_cost': '5'}
        data.update(kw)
        r = self.c.post('/api/account/initialize/', data, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def trade(self, key='one', **kw):
        data = {'side': 'BUY', 'quantity': 100, 'price': '4.000', 'fee': '1', 'occurred_at': '2026-10-20T10:00:00+08:00'}
        data.update(kw)
        return self.c.post('/api/entries/', data, format='json', HTTP_IDEMPOTENCY_KEY=key)

    def test_initial_snapshot_then_buy_partial_sell_close(self):
        self.init()
        self.assertEqual(self.c.get('/api/entries/').json()['count'], 0)
        r = self.trade()
        self.assertEqual(r.status_code, 201, r.content)
        a = self.c.get('/api/account/').json()
        self.assertEqual(D(a['cash']), D('9599'))
        self.assertEqual(D(a['cost_basis']), D('5401'))
        self.assertEqual(a['shares'], 1100)
        r = self.trade('two', side='SELL', quantity=100, price='6.000', fee='1')
        self.assertEqual(r.status_code, 201, r.content)
        a = self.c.get('/api/account/').json()
        self.assertEqual(D(a['realized']), D('108.000000'))
        self.assertEqual(D(a['cost_basis']), D('4910'))
        self.trade('three', side='SELL', quantity=1000, price='6.000', fee='1')
        a = self.c.get('/api/account/').json()
        self.assertEqual(a['shares'], 0)
        self.assertEqual(D(a['cost_basis']), 0)

    def test_idempotency_rejects_changed_body_and_loss_allowed(self):
        self.init()
        self.assertEqual(self.trade().status_code, 201)
        self.assertEqual(self.trade().status_code, 200)
        self.assertEqual(self.trade(price='3.000').status_code, 409)
        self.assertEqual(self.trade('loss', side='SELL', price='2.000').status_code, 201)
        self.assertLess(D(self.c.get('/api/account/').json()['realized']), 0)

    def test_insufficient_and_over_sell_rollback(self):
        self.init(cash='0')
        self.assertEqual(self.trade().status_code, 400)
        self.assertEqual(self.trade('oversell', side='SELL', quantity=1100).status_code, 400)
        self.assertEqual(self.c.get('/api/entries/').json()['count'], 0)

    def test_correction_preserves_original_and_replays(self):
        self.init()
        original = self.trade().json()
        payload = {'reason': '价格录错', 'replacement': {'side': 'BUY', 'quantity': 100, 'price': '3.000', 'fee': '1', 'occurred_at': '2026-10-20T10:00:00+08:00'}}
        r = self.c.post(f"/api/entries/{original['id']}/correct/", payload, format='json', HTTP_IDEMPOTENCY_KEY='correct1')
        self.assertEqual(r.status_code, 201, r.content)
        a = self.c.get('/api/account/').json()
        self.assertEqual(D(a['cash']), D('9699'))
        entries = self.c.get('/api/entries/').json()['results']
        self.assertEqual(len(entries), 2)
        self.assertEqual(next(x for x in entries if x['id'] == original['id'])['payload']['price'], '4.000')

    def test_cash_adjustment_budget_and_isolation(self):
        self.init()
        self.assertEqual(self.c.post('/api/cash/', {'amount': '-100', 'reason': '取出资金'}, format='json', HTTP_IDEMPOTENCY_KEY='cash1').status_code, 201)
        self.assertEqual(self.c.patch('/api/account/', {'budget': '25000'}, format='json').status_code, 200)
        self.assertEqual(D(self.c.get('/api/account/').json()['cash']), D('9900'))
        original = self.trade().json()
        self.c.force_login(self.other)
        self.assertIsNone(self.c.get('/api/account/').json()['initialized_at'])
        self.assertEqual(self.c.get('/api/entries/?user_id='+str(self.u.pk)).json()['count'], 0)
        self.assertEqual(self.c.post(f"/api/entries/{original['id']}/correct/", {}, format='json', HTTP_IDEMPOTENCY_KEY='malicious').status_code, 404)
