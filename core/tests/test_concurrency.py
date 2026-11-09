"""Run against PostgreSQL on the NAS: python manage.py test core.tests.test_concurrency.

SQLite cannot demonstrate PostgreSQL row/advisory locking. Explicitly skipped there.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest import skipUnless
from django.db import connection,close_old_connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient
from core.models import User,Entry
from core.ledger import initialize,post_entry

@skipUnless(connection.vendor=='postgresql','需要 PostgreSQL 才能验证真实行锁')
class ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.u=User.objects.create_user('concurrent')
        initialize(self.u,{'budget':'20000','cash':'500','shares':0,'unit_cost':'0'})

    def parallel(self,operation):
        barrier=Barrier(2)
        def run(n):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return operation(n)
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(run,range(2)))

    def test_duplicate_trade_locks_to_one_entry(self):
        data={'side':'BUY','quantity':100,'price':'4','fee':'1','occurred_at':'2026-10-20T10:00:00+08:00'}
        results=self.parallel(lambda n:post_entry(User.objects.get(pk=self.u.pk),data,'same-key')[1])
        self.assertEqual(sorted(results),[False,True]);self.assertEqual(Entry.objects.count(),1)

    def test_cash_cannot_be_spent_twice(self):
        data={'side':'BUY','quantity':100,'price':'4','fee':'1','occurred_at':'2026-10-20T10:00:00+08:00'}
        def op(n):
            c=APIClient();c.force_login(User.objects.get(pk=self.u.pk))
            return c.post('/api/entries/',data,format='json',HTTP_IDEMPOTENCY_KEY=str(n)).status_code
        self.assertEqual(sorted(self.parallel(op)),[201,400]);self.assertEqual(Entry.objects.count(),1)

    def test_invite_can_be_consumed_once(self):
        self.u.is_app_admin=True;self.u.save()
        c=APIClient();c.force_login(self.u)
        code=c.post('/api/admin/invites/',{},format='json').json()['code']
        def op(n):
            return APIClient().post('/api/auth/register/',{'code':code,'username':f'friend{n}','password':'Another-safe-password42!'},format='json').status_code
        self.assertEqual(sorted(self.parallel(op)),[201,400])


    def test_ledger_can_write_while_pushplus_is_waiting(self):
        from unittest.mock import patch
        from cryptography.fernet import Fernet
        from django.test import override_settings
        from core.models import Delivery, Plan, Quote
        from core.monitor import evaluate_all
        from core.push import deliver_due, encrypt_token
        from core.tests.test_monitor import NOW

        started, ledger_written = Event(), Event()

        def send(*args, **kwargs):
            started.set()
            if not ledger_written.wait(5):
                raise AssertionError('PushPlus 持锁期间账本无法写入')
            return 'SENT', 'ok'

        def deliver():
            try:
                deliver_due(NOW)
            finally:
                close_old_connections()

        with override_settings(ENCRYPTION_KEY=Fernet.generate_key().decode()):
            self.u.fee_rate = 0
            self.u.fee_minimum = 0
            self.u.fee_extra = 0
            self.u.token_encrypted = encrypt_token('a' * 32)
            self.u.save()
            Plan.objects.create(user=self.u, side='BUY', target_price=4, amount=500)
            Quote.objects.create(price=4, previous_close=5, source='test', source_at=NOW)
            evaluate_all(NOW)

            with patch('core.push.send_http', side_effect=send), patch('core.push.timezone.now', return_value=NOW):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(deliver)
                    try:
                        self.assertTrue(started.wait(5))
                        trade = {'side':'BUY','quantity':100,'price':'4','fee':'1','occurred_at':NOW.isoformat()}
                        self.assertTrue(post_entry(self.u, trade, 'parallel-with-push')[1])
                    finally:
                        ledger_written.set()
                    future.result(timeout=10)

        self.assertEqual(Delivery.objects.get().status, 'SENT')
        self.assertEqual(Entry.objects.count(), 1)
