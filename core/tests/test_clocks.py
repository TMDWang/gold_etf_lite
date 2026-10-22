from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import patch
from django.test import TestCase,override_settings
from cryptography.fernet import Fernet
from core.models import User,Account,Plan,Quote,Episode
from core.tests.test_monitor import NOW

class ClockTests(TestCase):
    def test_http_response_advancing_source_timestamp_is_not_future(self):
        from core.market import collect_quotes
        data={'symbol':'518880','price':D('4'),'previous_close':D('4'),'source':'eastmoney','source_at':NOW+timedelta(seconds=5)}
        times=iter([NOW,NOW+timedelta(seconds=10)])
        def clock():return next(times,NOW+timedelta(seconds=10))
        with patch('core.market.timezone.now',side_effect=clock),patch('core.market.fetch_eastmoney',return_value=data),patch('core.market.fetch_sina',side_effect=ValueError()):
            collect_quotes()
        self.assertTrue(Quote.objects.exists())

    def test_final_send_rechecks_actual_clock_not_batch_start(self):
        from core.monitor import evaluate_all
        from core.push import encrypt_token,deliver_due
        with override_settings(ENCRYPTION_KEY=Fernet.generate_key().decode()):
            u=User.objects.create_user('alice',fee_rate=D('0.0001'),fee_minimum=1,fee_extra=0,token_encrypted=encrypt_token('a'*32))
            Account.objects.create(user=u,budget=10000,cash=5000,initialized_at=NOW)
            Plan.objects.create(user=u,side='BUY',amount=1000,target_price=4)
            Quote.objects.create(price=4,previous_close=4,source_at=NOW,source='test')
            evaluate_all(NOW)
            with patch('core.push.timezone.now',return_value=NOW+timedelta(seconds=181)),patch('core.push.send_http',return_value=('SENT','accepted')) as sender:
                deliver_due(NOW)
            sender.assert_not_called()
