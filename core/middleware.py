from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.utils.cache import patch_vary_headers

class PrivateMiddleware:
    sync_capable=True
    async_capable=True
    def __init__(self, get_response):
        self.get_response = get_response
        self.is_async=iscoroutinefunction(get_response)
        if self.is_async:markcoroutinefunction(self)

    def __call__(self, request):
        if self.is_async:return self.acall(request)
        return self.process(request,self.get_response(request))

    async def acall(self,request):
        return self.process(request,await self.get_response(request))

    def process(self,request,response):
        if request.path.startswith('/api/'):
            response['Cache-Control'] = 'no-store, private, no-transform' if response.get('Content-Type','').startswith('text/event-stream') else 'no-store, private'
            patch_vary_headers(response,['Cookie'])
        return response
