from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import patch
from cryptography.fernet import Fernet
from django.test import TestCase,override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from core.models import User,Account,Plan,Episode,Quote,Delivery
from core.tests.test_monitor import NOW

class AlertTests(TestCase):
    def setUp(self):
        self.u=User.objects.create_user('alice')
        self.other=User.objects.create_user('other',is_app_admin=True)
        self.a=Account.objects.create(user=self.u,budget=20000,cash=10000,shares=1000,cost_basis=5000,initialized_at=NOW)
        self.q=Quote.objects.create(price=4,previous_close=5,source='test',source_at=NOW)
        self.c=APIClient();self.c.force_login(self.u)

    def create(self,**kw):
        data={'kind':'PRICE','direction':'BELOW','threshold':'4.000','interval':30,'repeat_max':3,'label':'价格提醒'}
        data.update(kw)
        return self.c.post('/api/alerts/',data,format='json')

    def tick(self,now=NOW):
        from core.monitor import evaluate_all
        evaluate_all(now)

    def test_multiple_rules_independent_of_buy_sell_plans(self):
        Plan.objects.create(user=self.u,side='BUY',target_price=4,amount=1000)
        a=self.create();b=self.create(kind='PCT_CLOSE',threshold='-10',direction='BELOW')
        self.assertEqual(a.status_code,201,a.content);self.assertEqual(b.status_code,201,b.content)
        self.assertEqual(len(self.c.get('/api/alerts/').json()),2)
        self.assertEqual(len(self.c.get('/api/plans/').json()),1)
        self.tick();self.tick()
        self.assertEqual(Episode.objects.filter(plan__side='INFO').count(),2)
        self.assertEqual(self.c.get('/api/episodes/').json(),[])

    def test_previous_close_and_personal_cost_are_different_and_missing_values_fail_closed(self):
        from core.plans import evaluate
        p=Plan(user=self.u,side='INFO',alert_kind='PCT_CLOSE',direction='ABOVE',alert_threshold=D('10'))
        self.assertTrue(evaluate(p,self.a,D('5.5'),self.u,quote=self.q)['eligible'])
        p.alert_kind='PCT_COST';self.assertTrue(evaluate(p,self.a,D('5.5'),self.u,quote=self.q)['eligible'])
        self.a.cost_basis=0
        self.assertFalse(evaluate(p,self.a,D('6'),self.u,quote=self.q)['eligible'])
        p.alert_kind='PCT_CLOSE';self.q.previous_close=None
        self.assertFalse(evaluate(p,self.a,D('6'),self.u,quote=self.q)['eligible'])

    def test_stale_quote_and_disabled_user_never_trigger(self):
        self.create();self.tick(NOW+timedelta(seconds=181))
        self.assertFalse(Episode.objects.exists())
        self.u.is_active=False;self.u.save();self.tick()
        self.assertFalse(Episode.objects.exists())

    def test_ignore_rearm_and_pause_version_preserve_other_rules(self):
        alert=self.create().json();self.tick()
        e=Episode.objects.get(plan_id=alert['id'])
        self.assertEqual(self.c.post(f"/api/alerts/{alert['id']}/ignore/",{},format='json').status_code,200)
        self.tick();self.assertEqual(Episode.objects.count(),1)
        self.q.price=5;self.q.save();self.tick()
        self.q.price=4;self.q.save();self.tick();self.assertEqual(Episode.objects.count(),2)
        r=self.c.patch(f"/api/alerts/{alert['id']}/",{'enabled':False},format='json')
        self.assertEqual(r.status_code,200,r.content)
        self.assertEqual(r.json()['version'],2)
        self.assertFalse(Episode.objects.filter(plan_id=alert['id'],status='OPEN').exists())
        r=self.c.patch(f"/api/alerts/{alert['id']}/",{'enabled':True},format='json')
        self.assertEqual(r.json()['version'],3)
        self.tick();self.assertEqual(Episode.objects.count(),3)

    def test_admin_cannot_access_other_users_rules_or_mutate_them(self):
        alert=self.create().json()
        self.c.force_login(self.other)
        self.assertEqual(self.c.get('/api/alerts/').json(),[])
        self.assertEqual(self.c.patch(f"/api/alerts/{alert['id']}/",{'enabled':False},format='json').status_code,404)
        self.assertEqual(self.c.delete(f"/api/alerts/{alert['id']}/").status_code,404)

    def test_validation_and_soft_deletion(self):
        self.assertEqual(self.create(kind='PRICE',threshold='4.0001').status_code,400)
        self.assertEqual(self.create(kind='PRICE',threshold='0').status_code,400)
        self.assertEqual(self.create(kind='PCT_COST',threshold='-2',interval=1).status_code,400)
        alert=self.create().json()
        self.assertEqual(self.c.delete(f"/api/alerts/{alert['id']}/").status_code,200)
        self.assertEqual(self.c.get('/api/alerts/').json(),[])
        self.assertTrue(Plan.objects.filter(pk=alert['id'],status='CANCELLED').exists())

    def test_market_alert_uses_push_limits_and_timeout_is_not_retried(self):
        from core.push import encrypt_token,deliver_due
        with override_settings(ENCRYPTION_KEY=Fernet.generate_key().decode()):
            self.u.token_encrypted=encrypt_token('a'*32);self.u.save()
            self.create(interval=20,repeat_max=2);self.tick()
            with patch('core.push.timezone.now',return_value=NOW),patch('core.push.send_http',return_value=('UNKNOWN','未知')) as sender:
                deliver_due(NOW);deliver_due(NOW)
            self.assertEqual(sender.call_count,1)
            self.assertIn('行情',sender.call_args.args[1])
            self.assertEqual(Episode.objects.get().status,'UNKNOWN')
            self.assertEqual(Delivery.objects.get().status,'UNKNOWN')

    def test_each_alert_uses_its_own_repeat_limit_and_interval(self):
        from core.push import encrypt_token,deliver_due
        with override_settings(ENCRYPTION_KEY=Fernet.generate_key().decode()):
            self.u.token_encrypted=encrypt_token('b'*32);self.u.reminder_max=1;self.u.save()
            self.create(interval=20,repeat_max=2);self.tick()
            with patch('core.push.send_http',return_value=('SENT','接收')) as sender:
                with patch('core.push.timezone.now',return_value=NOW):deliver_due(NOW)
                later=NOW+timedelta(minutes=20)
                self.q.source_at=later;self.q.save()
                with patch('core.push.timezone.now',return_value=later):deliver_due(later)
                later+=timedelta(minutes=20)
                self.q.source_at=later;self.q.save()
                with patch('core.push.timezone.now',return_value=later):deliver_due(later)
            self.assertEqual(sender.call_count,2)
            self.assertEqual(Episode.objects.get().sent_count,2)
