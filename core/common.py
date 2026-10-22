import hashlib
import json
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException
from core.models import RateWindow

class BusinessError(APIException):
    status_code = 400
    default_code = 'invalid_operation'
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status_code = status

def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str, separators=(',', ':')).encode()).hexdigest()

def clean_json(data):
    return json.loads(json.dumps(data, default=str))

@transaction.atomic
def throttle(key, limit, seconds, now=None):
    now = now or timezone.now()
    row, _ = RateWindow.objects.get_or_create(key=key, defaults={'started_at': now})
    row = RateWindow.objects.select_for_update().get(pk=key)
    if (now-row.started_at).total_seconds() >= seconds:
        row.started_at, row.count = now, 0
    if row.count >= limit:
        raise BusinessError('操作过于频繁，请稍后再试', 429)
    row.count += 1
    row.save()
