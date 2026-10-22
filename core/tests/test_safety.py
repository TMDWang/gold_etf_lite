from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from cryptography.fernet import Fernet
from core.models import User, Account, Entry, Plan, Episode, Quote, SystemState, Invitation
from core.tests.test_monitor import NOW

class SafetyTests(TestCase):
    def setUp(self):
        self.u=User.objects.create_user('alice')
        self.other=User.objects.create_user('admin',is_app_admin=True)
        self.c=APIClient();self.c.force_login(self.u)
        self.c.post('/api/account/initialize/',{'budget':'20000','cash':'10000','shares':1000,'unit_cost':'5'},format='json')

    def trade(self,key,**kw):
        d={'side':'BUY','quantity':100,'price':'4.000','fee':'1','occurred_at':'2026-10-20T10:00:00+08:00'};d.update(kw)
        return self.c.post('/api/entries/',d,format='json',HTTP_IDEMPOTENCY_KEY=key)

    def test_existing_holdings_require_known_positive_cost(self):
        self.c.force_login(self.other)
        r=self.c.post('/api/account/initialize/',{'budget':'10000','cash':'5000','shares':1000,'unit_cost':'0'},format='json')
        self.assertEqual(r.status_code,400)

    def test_bad_correction_rolls_back_and_keeps_future_records(self):
        first=self.trade('first').json()
        self.trade('sell',side='SELL',quantity=1100,price='6.000')
        payload={'reason':'发现错误','replacement':{'side':'BUY','quantity':200,'price':'100.000','fee':'1','occurred_at':'2026-10-20T10:00:00+08:00'}}
        before=self.c.get('/api/account/').json()
        r=self.c.post(f"/api/entries/{first['id']}/correct/",payload,format='json',HTTP_IDEMPOTENCY_KEY='badcorrection')
        self.assertEqual(r.status_code,400)
        self.assertEqual(self.c.get('/api/account/').json()['cash'],before['cash'])
        self.assertEqual(Entry.objects.filter(user=self.u).count(),2)

    def test_all_private_objects_and_secrets_are_scoped(self):
        with override_settings(ENCRYPTION_KEY=Fernet.generate_key().decode()):
            token='abc123'*6
            self.assertEqual(self.c.patch('/api/settings/',{'push_token':token},format='json').status_code,200)
            plan=self.c.post('/api/plans/',{'side':'BUY','direction':'BELOW','target_price':'4','amount':'1000'},format='json').json()
            ep=Episode.objects.create(plan_id=plan['id'],version=1,number=1,next_at=timezone.now())
            for url in ['/api/settings/','/api/me/','/api/account/','/api/plans/','/api/deliveries/']:
                self.assertNotIn(token,self.c.get(url).content.decode())
            self.c.force_login(self.other)
            self.assertEqual(self.c.patch(f"/api/plans/{plan['id']}/",{'amount':'50'},format='json').status_code,404)
            self.assertEqual(self.c.post(f'/api/episodes/{ep.pk}/ignore/',{}).status_code,404)
            self.assertFalse(self.c.get('/api/settings/').json()['token_bound'])
            self.assertEqual(self.c.patch(f'/api/admin/users/{self.u.pk}/',{'password':'bad','is_active':False},format='json').status_code,400)

    def test_expired_invitation_rejected(self):
        import hashlib
        Invitation.objects.create(created_by=self.other,code_hash=hashlib.sha256(b'expired').hexdigest(),expires_at=timezone.now()-timedelta(seconds=1))
        self.c.logout()
        self.assertEqual(self.c.post('/api/auth/register/',{'code':'expired','username':'friend','password':'Another-password42!'},format='json').status_code,400)

    def test_failed_sources_pause_even_if_last_quote_young(self):
        from core.monitor import evaluate_all
        self.u.fee_rate=D('0.0001');self.u.fee_minimum=1;self.u.fee_extra=0;self.u.save()
        Plan.objects.create(user=self.u,side='BUY',target_price=4,amount=1000)
        Quote.objects.create(price=4,previous_close=4,source='test',source_at=NOW)
        SystemState.objects.create(key='market',value={'available':False})
        evaluate_all(NOW)
        self.assertFalse(Episode.objects.exists())

    def test_sample_does_not_overwrite_true_minute(self):
        from core.market import collect_quotes
        from core.models import Minute
        Minute.objects.create(at=NOW,price='4.100',source='eastmoney-minute')
        data={'symbol':'518880','price':D('4'),'previous_close':D('4'),'source':'eastmoney','source_at':NOW}
        with patch('core.market.fetch_eastmoney',return_value=data):collect_quotes(NOW)
        self.assertEqual(Minute.objects.get().price,D('4.100'))

    def test_collection_marks_all_sources_unavailable(self):
        from core.market import collect_quotes
        with patch('core.market.fetch_eastmoney',side_effect=ValueError()),patch('core.market.fetch_sina',side_effect=ValueError()):
            collect_quotes(NOW)
        self.assertFalse(SystemState.objects.get(pk='market').value.get('available',True))

    def test_token_limits_are_shared_and_rolling(self):
        from core.push import reserve_quota
        from core.common import BusinessError
        from core.models import Delivery
        token='a'*32
        with override_settings(ENCRYPTION_KEY=Fernet.generate_key().decode()):
            from core.push import encrypt_token
            import hashlib
            fingerprint=hashlib.sha256(token.encode()).hexdigest()
            self.u.token_encrypted=encrypt_token(token);self.u.save()
            for i in range(4):
                d=Delivery.objects.create(user=self.other,token_hash=fingerprint)
                Delivery.objects.filter(pk=d.pk).update(created_at=NOW-timedelta(seconds=10+i))
            with self.assertRaises(BusinessError):reserve_quota(self.u,NOW)
