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
                self.assertIn('no-cache',r['Cache-Control'])
                self.assertIn('javascript',r['Content-Type'])
            finally:
                r.close()
