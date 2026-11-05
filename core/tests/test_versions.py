from django.test import TestCase
from rest_framework.test import APIClient
from core.models import User

class VersionTests(TestCase):
    def test_backend_fingerprint_is_stable_and_reflects_code(self):
        from core.version import fingerprint_entries
        one=[('core/a.py',b'one'),('config/b.py',b'two')]
        self.assertEqual(fingerprint_entries(one),fingerprint_entries(list(reversed(one))))
        self.assertNotEqual(fingerprint_entries(one),fingerprint_entries([('core/a.py',b'changed'),('config/b.py',b'two')]))

    def test_market_response_contains_nonsecret_backend_fingerprint(self):
        user=User.objects.create_user('version-test');c=APIClient();c.force_login(user)
        data=c.get('/api/market/').json()
        self.assertRegex(data['backend_version'],r'^[0-9a-f]{10}$')
