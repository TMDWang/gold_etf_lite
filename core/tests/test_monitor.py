from datetime import datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from core.models import User, Account, Plan, Quote, Episode, Delivery

CN = ZoneInfo('Asia/Shanghai')
NOW = datetime(2026, 10, 20, 10, 0, tzinfo=CN)

class MonitorTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user('alice', fee_rate=D('0.0001'), fee_minimum=1, fee_extra=0)
        self.a = Account.objects.create(user=self.u, budget=20000, cash=10000, shares=1000, cost_basis=5000, initialized_at=NOW)
        self.p = Plan.objects.create(user=self.u, side='BUY', target_price=4, amount=1000)
        self.q = Quote.objects.create(price=4, previous_close=5, source='test', source_at=NOW)

    def tick(self, now=NOW):
        from core.monitor import evaluate_all
        with patch('core.monitor.timezone.now', return_value=now):
            evaluate_all(now)

    def test_episode_repeat_persist_ignore_rearm(self):
        self.tick()
        self.assertEqual(Episode.objects.count(), 1)
        self.tick()
        self.assertEqual(Episode.objects.count(), 1)
        c = APIClient(); c.force_login(self.u)
        ep = Episode.objects.get()
        self.assertEqual(c.post(f'/api/episodes/{ep.pk}/ignore/').status_code, 200)
        self.tick()
        self.assertEqual(Episode.objects.count(), 1)
        self.q.price = 5; self.q.save(); self.tick()
        self.q.price = 4; self.q.save(); self.tick()
        self.assertEqual(Episode.objects.count(), 2)

    def test_stale_future_or_lunch_no_new_alerts(self):
        self.tick(NOW+timedelta(seconds=181))
        self.assertFalse(Episode.objects.exists())
        self.q.source_at = NOW+timedelta(minutes=3); self.q.save(); self.tick()
        self.assertFalse(Episode.objects.exists())
        self.q.source_at = NOW.replace(hour=12); self.q.save(); self.tick(NOW.replace(hour=12))
        self.assertFalse(Episode.objects.exists())

    def test_sell_or_condition_net_gate_and_actual_fee(self):
        from core.plans import evaluate
        self.p.side='SELL'; self.p.quantity=100; self.p.target_price=D('4.9'); self.p.target_profit=D('1')
        self.assertFalse(evaluate(self.p, self.a, D('4.99'), self.u)['eligible'])
        self.assertTrue(evaluate(self.p, self.a, D('5.2'), self.u)['eligible'])
        self.p.target_price=D('10')
        self.assertTrue(evaluate(self.p, self.a, D('5.2'), self.u)['eligible'])
        self.u.fee_rate = None
        self.assertFalse(evaluate(self.p, self.a, D('6'), self.u)['eligible'])

    def test_buy_both_directions_and_fee_budget(self):
        from core.plans import evaluate
        r = evaluate(self.p, self.a, D('4'), self.u)
        self.assertEqual(r['quantity'], 200)
        self.p.direction='ABOVE'
        self.assertFalse(evaluate(self.p, self.a, D('3.9'), self.u)['eligible'])
        self.assertTrue(evaluate(self.p, self.a, D('4'), self.u)['eligible'])
        self.a.cash=D('400')
        self.assertFalse(evaluate(self.p, self.a, D('4'), self.u)['eligible'])

    def test_timeout_marked_unknown_and_does_not_blindly_retry(self):
        from core.push import deliver_due, encrypt_token
        from cryptography.fernet import Fernet
        with override_settings(ENCRYPTION_KEY=Fernet.generate_key().decode()):
            self.u.token_encrypted=encrypt_token('a'*32); self.u.save()
            self.tick()
            with patch('core.push.send_http', return_value=('UNKNOWN', '结果未确认')) as sender,patch('core.push.timezone.now',return_value=NOW):
                deliver_due(NOW)
                deliver_due(NOW)
                self.assertEqual(sender.call_count, 1)
            self.assertEqual(Delivery.objects.get().status, 'UNKNOWN')
            self.assertEqual(Episode.objects.get().status, 'UNKNOWN')

    def test_disabled_user_never_gets_alert(self):
        self.u.is_active=False; self.u.save(); self.tick()
        self.assertFalse(Episode.objects.exists())

class MarketTests(TestCase):
    def test_market_sessions_and_holidays(self):
        from core.market import is_trading
        self.assertTrue(is_trading(NOW))
        self.assertFalse(is_trading(NOW.replace(day=1)))
        self.assertFalse(is_trading(NOW.replace(hour=12)))
        self.assertFalse(is_trading(NOW.replace(hour=15, minute=5)))

    def test_parsers_validate_source_time_and_identity(self):
        from core.market import parse_eastmoney, parse_sina
        r = parse_eastmoney({'data': {'f57':'518880','f43':4000,'f60':3900,'f59':3,'f86':int(NOW.timestamp())}})
        self.assertEqual(r['price'], D('4'))
        raw = 'var hq_str_sh518880="黄金ETF,4.000,3.900,4.000,4.1,3.8,0,0,100,1000,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-10-20,10:00:00,00";'
        self.assertEqual(parse_sina(raw)['source_at'], NOW)
        with self.assertRaises(ValueError):
            parse_eastmoney({'data': {'f57':'510300','f43':4000,'f60':3900,'f59':3,'f86':int(NOW.timestamp())}})

    def test_market_fallback_persists_verified_backup(self):
        from core.market import collect_quotes
        with patch('core.market.fetch_eastmoney', side_effect=ValueError('unavailable')), patch('core.market.fetch_sina', return_value={'symbol':'518880','price':D('4'),'previous_close':D('3.9'),'source':'sina','source_at':NOW}):
            collect_quotes(NOW)
        self.assertEqual(Quote.objects.get().source, 'sina')
