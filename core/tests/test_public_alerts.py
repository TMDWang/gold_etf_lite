from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from core.models import User, Account, Plan, Episode, Quote
from core.tests.test_monitor import NOW

class PublicAlertsTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_user('admin',is_app_admin=True)
        self.user=User.objects.create_user('alice')
        for u in (self.admin,self.user):Account.objects.create(user=u)
        self.c=APIClient();self.c.force_login(self.admin)
        self.data={'kind':'PRICE','direction':'BELOW','threshold':'4','interval':30,'repeat_max':3,'label':'公共观察'}

    def test_public_rule_is_shared_but_user_can_disable_own_only(self):
        r=self.c.post('/api/admin/public-alerts/',self.data,format='json');self.assertEqual(r.status_code,201,r.content)
        rule=r.json();self.c.force_login(self.user)
        rows=self.c.get('/api/public-alerts/').json();self.assertEqual(len(rows),1);self.assertTrue(rows[0]['enabled'])
        self.assertEqual(self.c.patch(f"/api/public-alerts/{rule['id']}/",{'enabled':False},format='json').status_code,200)
        self.assertFalse(self.c.get('/api/public-alerts/').json()[0]['enabled'])
        self.assertEqual(self.c.get('/api/alerts/').json(),[])
        self.assertEqual(self.c.post('/api/admin/public-alerts/',self.data,format='json').status_code,403)
        self.c.force_login(self.admin);self.assertTrue(self.c.get('/api/public-alerts/').json()[0]['enabled'])
        self.assertFalse(Plan.objects.filter(user=self.user,side='INFO',status='ACTIVE').exists())

    def test_edit_closes_episodes_preserves_opt_out_and_delete_stops(self):
        rule=self.c.post('/api/admin/public-alerts/',self.data,format='json').json()
        self.c.force_login(self.user);self.c.patch(f"/api/public-alerts/{rule['id']}/",{'enabled':False},format='json')
        self.c.force_login(self.admin)
        p=Plan.objects.get(user=self.admin,public_alert_id=rule['id']);Episode.objects.create(plan=p,version=p.version,number=1,next_at=NOW)
        r=self.c.patch(f"/api/admin/public-alerts/{rule['id']}/",{'threshold':'3'},format='json');self.assertEqual(r.status_code,200,r.content)
        p.refresh_from_db();self.assertEqual(p.alert_threshold,Decimal('3'));self.assertEqual(Episode.objects.get().status,'CLOSED')
        self.assertEqual(Plan.objects.get(user=self.user,public_alert_id=rule['id']).status,'PAUSED')
        self.assertEqual(self.c.delete(f"/api/admin/public-alerts/{rule['id']}/").status_code,200)
        self.assertEqual(self.c.get('/api/public-alerts/').json(),[])

    def test_public_rules_cannot_use_private_cost(self):
        self.data.update(kind='PCT_COST',threshold='5')
        self.assertEqual(self.c.post('/api/admin/public-alerts/',self.data,format='json').status_code,400)

    def test_newly_registered_user_is_subscribed_by_default(self):
        self.assertEqual(self.c.post('/api/admin/public-alerts/',self.data,format='json').status_code,201)
        invite=self.c.post('/api/admin/invites/',{},format='json').json()['code']
        self.c.logout()
        r=self.c.post('/api/auth/register/',{'username':'friend','password':'Another-good-password42!','code':invite},format='json')
        self.assertEqual(r.status_code,201,r.content)
        self.assertTrue(self.c.get('/api/public-alerts/').json()[0]['enabled'])

    def test_public_signal_only_creates_events_for_subscribed_users(self):
        from core.monitor import evaluate_all
        rule=self.c.post('/api/admin/public-alerts/',self.data,format='json').json()
        self.c.force_login(self.user);self.c.patch(f"/api/public-alerts/{rule['id']}/",{'enabled':False},format='json')
        Quote.objects.create(price=4,previous_close=5,source='test',source_at=NOW)
        evaluate_all(NOW)
        self.assertEqual(Episode.objects.filter(plan__public_alert_id=rule['id']).count(),1)
        self.assertEqual(Episode.objects.get().plan.user,self.admin)
