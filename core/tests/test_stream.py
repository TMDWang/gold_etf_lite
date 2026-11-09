import asyncio
from decimal import Decimal
from unittest import IsolatedAsyncioTestCase
from django.test import TestCase, TransactionTestCase, AsyncClient
from django.utils import timezone
from rest_framework.test import APIClient
from core.models import User, Quote

class PriceHubTests(IsolatedAsyncioTestCase):
    async def test_unchanged_price_is_not_rebroadcast_but_status_changes_are(self):
        from core.price_stream import PriceHub
        values=iter([
            {'quote':{'price':'4.000','source_at':'1'},'fresh':True,'session_open':True,'curve_date':'2026-11-05'},
            {'quote':{'price':'4.000','source_at':'2'},'fresh':True,'session_open':True,'curve_date':'2026-11-05'},
            {'quote':{'price':'4.000','source_at':'3'},'fresh':False,'session_open':False,'curve_date':'2026-11-05'},
            {'quote':{'price':'4.001','source_at':'4'},'fresh':False,'session_open':False,'curve_date':'2026-11-05'},
        ])
        hub=PriceHub(None)
        q=asyncio.Queue(maxsize=1);hub.subscribers.add(q)
        hub.update(next(values));self.assertEqual((await q.get())['quote']['price'],'4.000')
        hub.update(next(values));self.assertTrue(q.empty());self.assertEqual(hub.latest['quote']['source_at'],'2')
        hub.update(next(values));status=await q.get();self.assertTrue(status['status_only']);self.assertNotIn('quote',status)
        hub.update(next(values));self.assertEqual((await q.get())['quote']['price'],'4.001')

    async def test_multiple_subscribers_share_sampler_and_latest_value(self):
        from core.price_stream import PriceHub
        calls=0
        async def snapshot():
            nonlocal calls
            calls+=1
            return {'price':'4.000'}
        hub=PriceHub(snapshot,interval=60)
        async with hub.subscribe() as one,hub.subscribe() as two:
            self.assertEqual(await asyncio.wait_for(one.get(),1),{'price':'4.000'})
            self.assertEqual(await asyncio.wait_for(two.get(),1),{'price':'4.000'})
            self.assertEqual(calls,1)
        self.assertEqual(len(hub.subscribers),0)
        self.assertIsNone(hub.task)

    async def test_slow_subscriber_keeps_only_latest_update(self):
        from core.price_stream import PriceHub
        hub=PriceHub(lambda:None)
        q=asyncio.Queue(maxsize=1);hub.subscribers.add(q)
        hub.publish({'price':'4'});hub.publish({'price':'5'})
        self.assertEqual(q.qsize(),1);self.assertEqual(await q.get(),{'price':'5'})

class PriceEndpointTests(TestCase):
    def test_quote_snapshot_is_public_data_only_and_requires_login(self):
        c=APIClient();self.assertIn(c.get('/api/quote/').status_code,[401,403])
        user=User.objects.create_user('alice');c.force_login(user)
        Quote.objects.create(price=Decimal('4.123'),previous_close=Decimal('4'),source='test',source_at=timezone.now())
        r=c.get('/api/quote/');self.assertEqual(r.status_code,200,r.content)
        self.assertEqual(r.json()['quote']['price'],'4.123')
        self.assertNotIn('cash',r.json());self.assertNotIn('shares',r.json());self.assertNotIn('points',r.json())
        self.assertIn('no-store',r['Cache-Control'])

    def test_stream_requires_login(self):
        from django.test import AsyncClient
        from asgiref.sync import async_to_sync
        response=async_to_sync(AsyncClient().get)('/api/quote/stream/')
        self.assertIn(response.status_code,[401,403])

class StreamIntegrationTests(TransactionTestCase):
    def test_stream_session_validation_respects_disable_and_logout(self):
        from core.price_stream import _session_valid
        user=User.objects.create_user('member');client=APIClient();client.force_login(user)
        key=client.session.session_key
        self.assertTrue(_session_valid(key))
        user.is_active=False;user.save(update_fields=['is_active']);self.assertFalse(_session_valid(key))
        user.is_active=True;user.save(update_fields=['is_active']);client.logout();self.assertFalse(_session_valid(key))

    async def test_authenticated_async_stream_starts_and_remains_private(self):
        from asgiref.sync import sync_to_async
        user=await sync_to_async(User.objects.create_user)('stream-user')
        client=AsyncClient();await client.aforce_login(user)
        response=await client.get('/api/quote/stream/')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.streaming);self.assertTrue(response.is_async)
        self.assertTrue(response['Content-Type'].startswith('text/event-stream'))
        self.assertIn('no-transform',response['Cache-Control']);self.assertIn('no-store',response['Cache-Control'])
        account=await asyncio.wait_for(client.get('/api/account/'),3)
        self.assertEqual(account.status_code,200)
        iterator=response.streaming_content
        chunk=await asyncio.wait_for(anext(iterator),3)
        self.assertIn(b'event: price',chunk);self.assertNotIn(b'cash',chunk);self.assertNotIn(b'shares',chunk)
        await iterator.aclose()
        await response._iterator.aclose()

    async def test_multiple_streams_share_one_sampler_and_do_not_block_api(self):
        from asgiref.sync import sync_to_async
        from core.price_stream import hub
        user=await sync_to_async(User.objects.create_user)('many-streams')
        client=AsyncClient();await client.aforce_login(user)
        responses=await asyncio.gather(*(client.get('/api/quote/stream/') for _ in range(8)))
        self.assertTrue(all(r.status_code==200 for r in responses))
        iterators=[r.streaming_content for r in responses]
        chunks=await asyncio.wait_for(asyncio.gather(*(anext(it) for it in iterators)),3)
        self.assertTrue(all(b'event: price' in chunk for chunk in chunks))
        self.assertEqual(len(hub.subscribers),8)
        self.assertEqual((await asyncio.wait_for(client.get('/api/account/'),3)).status_code,200)
        waiting=[asyncio.create_task(anext(it)) for it in iterators]
        await asyncio.sleep(0)
        for task in waiting:task.cancel()
        await asyncio.gather(*waiting,return_exceptions=True)
        await asyncio.gather(*(it.aclose() for it in iterators))
        await asyncio.gather(*(r._iterator.aclose() for r in responses))
        await asyncio.sleep(0)
        self.assertEqual(len(hub.subscribers),0)

    async def test_asgi_disconnect_releases_stream_subscription(self):
        from asgiref.sync import sync_to_async
        from django.conf import settings
        from config.asgi import application
        from core.price_stream import hub
        user=await sync_to_async(User.objects.create_user)('disconnect')
        client=AsyncClient();await client.aforce_login(user)
        cookie=client.cookies[settings.SESSION_COOKIE_NAME].value
        incoming=asyncio.Queue();await incoming.put({'type':'http.request','body':b'','more_body':False})
        received=asyncio.Event()
        async def receive():return await incoming.get()
        async def send(message):
            if message['type']=='http.response.body' and b'event: price' in message.get('body',b''):received.set()
        scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'GET','scheme':'http','path':'/api/quote/stream/','raw_path':b'/api/quote/stream/','query_string':b'','headers':[(b'host',b'testserver'),(b'cookie',f'{settings.SESSION_COOKIE_NAME}={cookie}'.encode())],'server':('testserver',80),'client':('127.0.0.1',1234)}
        task=asyncio.create_task(application(scope,receive,send))
        await asyncio.wait_for(received.wait(),3);self.assertEqual(len(hub.subscribers),1)
        await incoming.put({'type':'http.disconnect'})
        await asyncio.wait_for(task,3);self.assertEqual(len(hub.subscribers),0)
