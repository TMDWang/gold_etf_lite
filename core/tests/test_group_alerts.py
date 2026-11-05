from unittest.mock import patch
from cryptography.fernet import Fernet
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from core.models import User, Account, Quote, Delivery
from core.tests.test_monitor import NOW

@override_settings(ENCRYPTION_KEY=Fernet.generate_key().decode())
class GroupAlertsTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_user('admin',is_app_admin=True)
        self.member=User.objects.create_user('member')
        Account.objects.create(user=self.admin);Account.objects.create(user=self.member)
        self.c=APIClient();self.c.force_login(self.admin)
        self.rule={'kind':'PRICE','direction':'BELOW','threshold':'4','interval':30,'repeat_max':3,'label':'公共行情'}
        Quote.objects.create(price=4,previous_close=5,source='test',source_at=NOW)

    def configure(self):
        return self.c.patch('/api/admin/group-push/',{'token':'a'*32,'topic':'gold_public'},format='json')

    def test_group_config_write_only_and_admin_only(self):
        r=self.configure();self.assertEqual(r.status_code,200,r.content)
        self.assertTrue(r.json()['token_bound']);self.assertNotIn('token',r.json())
        self.c.force_login(self.member);self.assertEqual(self.c.get('/api/admin/group-push/').status_code,403)

    def test_public_rule_generates_one_group_send_no_personal_delivery(self):
        from core.monitor import evaluate_all
        from core.push import deliver_due
        self.assertEqual(self.configure().status_code,200)
        self.assertEqual(self.c.post('/api/admin/public-alerts/',self.rule,format='json').status_code,201)
        evaluate_all(NOW)
        with patch('core.push.timezone.now',return_value=NOW),patch('core.push.send_http',return_value=('SENT','ok')) as sender:
            deliver_due(NOW);deliver_due(NOW)
        self.assertEqual(sender.call_count,1)
        self.assertEqual(sender.call_args.kwargs['topic'],'gold_public')
        self.assertIsNone(Delivery.objects.get().episode_id)
        self.assertEqual(Delivery.objects.get().group_episode.plan_rule.label,'公共行情')

    def test_group_does_not_send_without_group_config(self):
        from core.monitor import evaluate_all
        from core.push import deliver_due
        self.c.post('/api/admin/public-alerts/',self.rule,format='json');evaluate_all(NOW)
        with patch('core.push.timezone.now',return_value=NOW),patch('core.push.send_http') as sender:deliver_due(NOW)
        sender.assert_not_called()

    def test_unknown_group_delivery_is_never_resent(self):
        from core.monitor import evaluate_all
        from core.push import deliver_due
        from core.models import GroupEpisode
        self.configure();self.c.post('/api/admin/public-alerts/',self.rule,format='json');evaluate_all(NOW)
        with patch('core.push.timezone.now',return_value=NOW),patch('core.push.send_http',return_value=('UNKNOWN','unknown')) as sender:
            deliver_due(NOW);deliver_due(NOW)
        self.assertEqual(sender.call_count,1);self.assertEqual(GroupEpisode.objects.get().status,'UNKNOWN')

    def test_user_cannot_obtain_or_update_group_credentials(self):
        self.configure();self.c.force_login(self.member)
        self.assertEqual(self.c.get('/api/admin/group-push/').status_code,403)
        self.assertEqual(self.c.patch('/api/admin/group-push/',{'topic':'other'},format='json').status_code,403)

    def test_migration_stops_legacy_public_delivery_but_keeps_personal(self):
        import importlib
        from django.apps import apps
        from core.models import Plan, Episode
        rule=self.c.post('/api/admin/public-alerts/',self.rule,format='json').json()
        old=Plan.objects.create(user=self.member,side='INFO',public_alert_id=rule['id'])
        personal=Plan.objects.create(user=self.member,side='INFO')
        episode=Episode.objects.create(plan=old,version=1,number=1,next_at=NOW)
        migration=importlib.import_module('core.migrations.0005_publicalert_condition_met_and_more')
        migration.stop_legacy_public_delivery(apps,None)
        old.refresh_from_db();personal.refresh_from_db();episode.refresh_from_db()
        self.assertEqual(old.status,'CANCELLED');self.assertEqual(episode.status,'CLOSED')
        self.assertEqual(personal.status,'ACTIVE')

    def test_pushplus_request_specifies_topic_only_for_group(self):
        from core.push import send_http
        with patch('core.push.requests.post') as post:
            post.return_value.status_code=200;post.return_value.json.return_value={'code':200}
            send_http('a'*32,'title','content',topic='gold_public')
            self.assertEqual(post.call_args.kwargs['json']['topic'],'gold_public')
            send_http('a'*32,'title','private')
            self.assertNotIn('topic',post.call_args.kwargs['json'])
