from django.test import TestCase
from rest_framework.test import APIClient
from core.models import User

class VersionTests(TestCase):
    def test_market_response_contains_semantic_backend_version(self):
        from core.version import backend_version
        user=User.objects.create_user('version-test');c=APIClient();c.force_login(user)
        data=c.get('/api/market/').json()
        self.assertRegex(data['backend_version'],r'^\d+\.\d+\.\d+$')
        self.assertEqual(data['backend_version'],backend_version())
