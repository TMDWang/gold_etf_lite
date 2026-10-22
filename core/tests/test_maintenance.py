from django.test import TestCase, override_settings
from decimal import Decimal as D
from core.models import User,Account,Plan,Quote,Episode
from core.tests.test_monitor import NOW

class MaintenanceTests(TestCase):
    @override_settings(PAUSE_NOTIFICATIONS=True)
    def test_restored_plans_cannot_emit_until_operator_resumes(self):
        from core.monitor import evaluate_all
        u=User.objects.create_user('alice',fee_rate=D('0.0001'),fee_minimum=1,fee_extra=0)
        Account.objects.create(user=u,budget=10000,cash=5000,initialized_at=NOW)
        Plan.objects.create(user=u,side='BUY',amount=1000,target_price=4)
        Quote.objects.create(price=4,previous_close=4,source_at=NOW,source='test')
        evaluate_all(NOW)
        self.assertFalse(Episode.objects.exists())
