"""Share one public-price sampler per ASGI process, regardless of client count."""
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from importlib import import_module
from types import SimpleNamespace
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user
from django.db import close_old_connections
from django.http import HttpResponseForbidden, StreamingHttpResponse
from django.views.decorators.http import require_GET

logger=logging.getLogger(__name__)

def _snapshot():
    from core.market import price_data
    close_old_connections()
    try:return price_data()
    finally:close_old_connections()

async def snapshot():
    return await sync_to_async(_snapshot,thread_sensitive=False)()

class PriceHub:
    def __init__(self,reader,interval=5):
        self.reader=reader;self.interval=interval;self.subscribers=set();self.task=None;self.latest=None
    def publish(self,value):
        self.latest=value
        for queue in tuple(self.subscribers):
            if queue.full():
                try:queue.get_nowait()
                except asyncio.QueueEmpty:pass
            queue.put_nowait(value)
    def update(self,value):
        previous=self.latest
        def price(item):
            return (item.get('quote') or {}).get('price',item.get('price'))
        keys=('fresh','session_open','unavailable','curve_date','calendar_until','calendar_valid','calendar_notice')
        if previous is None or price(previous)!=price(value):
            self.publish(value)
        elif any(previous.get(k)!=value.get(k) for k in keys):
            status={'status_only':True,**{k:value.get(k) for k in keys},'message':value.get('message')}
            for queue in tuple(self.subscribers):
                if queue.full():
                    pending=queue.get_nowait()
                    if not pending.get('status_only'):
                        queue.put_nowait({**pending,**{k:v for k,v in status.items() if k!='status_only'}})
                        continue
                queue.put_nowait(status)
        self.latest=value
    async def run(self):
        while self.subscribers:
            try:value=await self.reader()
            except asyncio.CancelledError:raise
            except Exception as exc:
                logger.warning('public quote snapshot failed (%s)',type(exc).__name__)
                value={'unavailable':True,'message':'行情暂不可用'}
            self.update(value)
            await asyncio.sleep(self.interval)
    def attach(self):
        queue=asyncio.Queue(maxsize=1);self.subscribers.add(queue)
        if self.latest is not None:queue.put_nowait(self.latest)
        if self.task is None or self.task.done():self.task=asyncio.create_task(self.run())
        return queue
    def detach(self,queue):
        self.subscribers.discard(queue)
        if not self.subscribers and self.task:
            self.task.cancel();self.task=None;self.latest=None
    @asynccontextmanager
    async def subscribe(self):
        queue=self.attach()
        try:yield queue
        finally:self.detach(queue)

hub=PriceHub(snapshot)

def _session_valid(key):
    if not key:return False
    close_old_connections()
    try:
        session=import_module(settings.SESSION_ENGINE).SessionStore(session_key=key)
        user=get_user(SimpleNamespace(session=session))
        return bool(user.is_authenticated and user.is_active)
    finally:close_old_connections()

async def session_valid(key):
    return await sync_to_async(_session_valid,thread_sensitive=False)(key)

async def stream_events(session_key):
    next_check=time.monotonic()+60
    queue=hub.attach()
    try:
        while True:
            if time.monotonic()>=next_check:
                if not await session_valid(session_key):return
                next_check=time.monotonic()+60
            try:
                value=await asyncio.wait_for(queue.get(),timeout=15)
                yield 'event: price\ndata: '+json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n\n'
            except asyncio.TimeoutError:
                yield 'event: heartbeat\ndata: {}\n\n'
    finally:hub.detach(queue)

@require_GET
async def quote_stream(request):
    user=await request.auser()
    if not user.is_authenticated or not user.is_active:return HttpResponseForbidden()
    response=StreamingHttpResponse(stream_events(request.session.session_key),content_type='text/event-stream; charset=utf-8')
    response['Cache-Control']='no-store, no-transform';response['X-Accel-Buffering']='no'
    return response
