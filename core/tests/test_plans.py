from django.test import TestCase
from rest_framework.test import APIClient
from core.models import User

class PlanTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user('alice')
        self.c = APIClient()
        self.c.force_login(self.u)
        self.c.post('/api/account/initialize/', {'budget': '20000', 'cash': '10000', 'shares': 1000, 'unit_cost': '5'}, format='json')

    def test_one_active_per_side_version_and_confirm(self):
        data = {'side': 'BUY', 'direction': 'BELOW', 'target_price': '4.000', 'amount': '1000'}
        r = self.c.post('/api/plans/', data, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        plan = r.json()
        self.assertEqual(self.c.post('/api/plans/', data, format='json').status_code, 400)
        r = self.c.patch(f"/api/plans/{plan['id']}/", {'target_price': '3.900'}, format='json')
        self.assertEqual(r.json()['version'], 2)
        trade = {'side': 'BUY', 'quantity': 100, 'price': '4.000', 'fee': '1', 'plan_id': plan['id'], 'plan_version': 2, 'occurred_at': '2026-10-20T10:00:00+08:00'}
        r = self.c.post('/api/entries/', trade, format='json', HTTP_IDEMPOTENCY_KEY='fill')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.c.get('/api/plans/').json()[0]['status'], 'COMPLETED')

    def test_invalid_target_or_lot(self):
        self.assertEqual(self.c.post('/api/plans/', {'side': 'SELL', 'quantity': 100}, format='json').status_code, 400)
        self.assertEqual(self.c.post('/api/plans/', {'side': 'BUY', 'target_price': '4.0001', 'amount': '1000', 'direction': 'BELOW'}, format='json').status_code, 400)
        r = self.c.post('/api/entries/', {'side': 'BUY', 'quantity': 1, 'price': '4', 'fee': '0', 'occurred_at': '2026-10-20T10:00:00+08:00'}, format='json', HTTP_IDEMPOTENCY_KEY='badlot')
        self.assertEqual(r.status_code, 400)
