import tempfile
from pathlib import Path
from django.test import TestCase,override_settings

class PwaTests(TestCase):
    def test_episode_api_includes_version_for_safe_confirmation(self):
        from core.models import User,Plan,Episode
        from django.utils import timezone
        user=User.objects.create_user('alice')
        plan=Plan.objects.create(user=user,side='BUY',target_price=4,amount=1000,version=3)
        Episode.objects.create(plan=plan,version=3,number=1,next_at=timezone.now())
        self.client.force_login(user)
        self.assertEqual(self.client.get('/api/episodes/').json()[0]['version'],3)

    def test_root_worker_is_uncached_and_allowed_to_control_root(self):
        with tempfile.TemporaryDirectory() as tmp,override_settings(BASE_DIR=Path(tmp)):
            dist=Path(tmp)/'frontend'/'dist';dist.mkdir(parents=True)
            (dist/'sw.js').write_text('/* generated worker */',encoding='utf-8')
            r=self.client.get('/sw.js')
            try:
                self.assertEqual(r.status_code,200)
                self.assertEqual(r['Service-Worker-Allowed'],'/')
                self.assertIn('no-store',r['Cache-Control'])
                self.assertIn('javascript',r['Content-Type'])
            finally:
                r.close()


    def test_home_and_offline_shell_serve_current_build_without_http_caching(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(BASE_DIR=Path(tmp)):
            dist = Path(tmp) / 'frontend' / 'dist'
            dist.mkdir(parents=True)
            entry = b'<!doctype html><meta name="gold-etf-version" content="0.5.1">'
            (dist / 'index.html').write_bytes(entry)
            for path in ('/', '/offline-shell.html'):
                response = self.client.get(path)
                with self.subTest(path=path):
                    try:
                        self.assertEqual(response.status_code, 200)
                        self.assertIn('no-store', response['Cache-Control'])
                        self.assertEqual(b''.join(response.streaming_content), entry)
                    finally:
                        response.close()
