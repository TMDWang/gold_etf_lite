"""Run against PostgreSQL on the NAS: python manage.py test core.tests.test_concurrency.

SQLite cannot demonstrate PostgreSQL row/advisory locking. Explicitly skipped there.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
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
