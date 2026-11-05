from decimal import Decimal as D
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from core.models import User, Account, Entry, Quote

class BuyPreviewTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('preview',fee_rate=D('0.0001'),fee_minimum=D('1'),fee_extra=D('0'))
        self.account=Account.objects.create(user=self.user,initialized_at=timezone.now(),cash=D('2000'),shares=100,cost_basis=D('500'))
        self.client=APIClient();self.client.force_login(self.user)

    def test_preview_uses_same_fee_and_cost_rules_without_writing(self):
        response=self.client.post('/api/account/buy-preview/',{'price':'4.567','quantity':100},format='json')
        self.assertEqual(response.status_code,200,response.content)
        data=response.json()
        self.assertEqual(D(data['fee']),D('1.00'));self.assertEqual(D(data['gross']),D('456.70'))
        self.assertEqual(data['after']['shares'],200);self.assertEqual(D(data['after']['cost_basis']),D('957.70'))
        self.assertEqual(D(data['after']['unit_cost']),D('4.7885'));self.assertEqual(D(data['after']['cash']),D('1542.30'))
        self.assertTrue(data['cash_sufficient']);self.account.refresh_from_db();self.assertEqual(self.account.shares,100)
        self.assertEqual(Entry.objects.count(),0)

    def test_manual_fee_zero_and_insufficient_cash(self):
        response=self.client.post('/api/account/buy-preview/',{'price':'100','quantity':100,'fee':'0'},format='json')
        self.assertEqual(response.status_code,200,response.content)
        data=response.json();self.assertEqual(D(data['fee']),0);self.assertFalse(data['cash_sufficient'])
        self.assertEqual(D(data['after']['cash']),D('-8000'))

    def test_validation_and_missing_fee_configuration(self):
        self.assertEqual(self.client.post('/api/account/buy-preview/',{'price':'4','quantity':101},format='json').status_code,400)
        self.user.fee_rate=None;self.user.save()
        self.assertEqual(self.client.post('/api/account/buy-preview/',{'price':'4','quantity':100},format='json').status_code,400)
        self.assertEqual(self.client.post('/api/account/buy-preview/',{'price':'4','quantity':100,'fee':'0'},format='json').status_code,200)

    def test_account_includes_latest_reference_quote_without_intraday_points(self):
        Quote.objects.create(price=D('4.123'),previous_close=D('4'),source='test',source_at=timezone.now())
        data=self.client.get('/api/account/').json()
        self.assertEqual(D(data['reference_quote']['price']),D('4.123'))
        self.assertIn('source_at',data['reference_quote']);self.assertNotIn('points',data)
