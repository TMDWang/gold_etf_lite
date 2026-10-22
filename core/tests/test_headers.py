from django.test import TestCase, override_settings
from unittest.mock import patch

class HeaderTests(TestCase):
    def test_pages_disallow_framing(self):
        r=self.client.get('/')
        self.assertEqual(r.get('X-Frame-Options'),'DENY')

    @override_settings(SECURE_SSL_REDIRECT=True,SECURE_REDIRECT_EXEMPT=['^health/$'])
    def test_health_is_http_exempt_but_regular_pages_redirect(self):
        self.assertEqual(self.client.get('/').status_code,301)
        with patch('core.monitor.worker_ok',return_value=True):
            self.assertEqual(self.client.get('/health/').status_code,200)
