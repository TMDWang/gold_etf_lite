from django.test import TestCase
from rest_framework.test import APIClient
from core.models import User, Account, PublicAlert, GroupEpisode, Quote
from core.tests.test_monitor import NOW

class PublicAlertsTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_user('admin',is_app_admin=True)
        self.user=User.objects.create_user('alice')
        for u in (self.admin,self.user):Account.objects.create(user=u)
        self.c=APIClient();self.c.force_login(self.admin)
        self.data={'kind':'PRICE','direction':'BELOW','threshold':'4','interval':30,'repeat_max':3,'label':'公共观察'}

    def test_public_rules_visible_but_member_cannot_edit_or_toggle_them(self):
        r=self.c.post('/api/admin/public-alerts/',self.data,format='json');self.assertEqual(r.status_code,201,r.content)
        rule=r.json();self.c.force_login(self.user)
        self.assertEqual(self.c.get('/api/public-alerts/').json()[0]['id'],rule['id'])
        self.assertEqual(self.c.get('/api/alerts/').json(),[])
        self.assertEqual(self.c.patch(f"/api/admin/public-alerts/{rule['id']}/",{'threshold':'3'},format='json').status_code,403)
        self.assertEqual(self.c.post('/api/admin/public-alerts/',self.data,format='json').status_code,403)

    def test_edit_closes_group_episode_and_delete_stops_rule(self):
        rule=self.c.post('/api/admin/public-alerts/',self.data,format='json').json()
        e=GroupEpisode.objects.create(plan_rule_id=rule['id'],version=1,number=1,next_at=NOW)
        r=self.c.patch(f"/api/admin/public-alerts/{rule['id']}/",{'threshold':'3'},format='json');self.assertEqual(r.status_code,200,r.content)
        e.refresh_from_db();self.assertEqual(e.status,'CLOSED')
        self.assertEqual(PublicAlert.objects.get(pk=rule['id']).version,2)
        self.assertEqual(self.c.delete(f"/api/admin/public-alerts/{rule['id']}/").status_code,200)
        self.assertEqual(self.c.get('/api/public-alerts/').json(),[])

    def test_public_rules_cannot_use_private_cost(self):
        self.data.update(kind='PCT_COST',threshold='5')
        self.assertEqual(self.c.post('/api/admin/public-alerts/',self.data,format='json').status_code,400)

    def test_public_rule_creates_one_group_episode_not_user_copies(self):
        from core.monitor import evaluate_all
        rule=self.c.post('/api/admin/public-alerts/',self.data,format='json').json()
        Quote.objects.create(price=4,previous_close=5,source='test',source_at=NOW)
        evaluate_all(NOW);evaluate_all(NOW)
        self.assertEqual(GroupEpisode.objects.filter(plan_rule_id=rule['id']).count(),1)
