from rest_framework.views import exception_handler as drf_handler
from django.db import IntegrityError
from rest_framework.response import Response

def exception_handler(exc, context):
    if isinstance(exc, IntegrityError):
        return Response({'detail':'数据已变化或存在重复操作，请刷新后重试'},status=409)
    return drf_handler(exc, context)
