import configparser
from django.conf import settings
from django.test import SimpleTestCase

class DeploymentTests(SimpleTestCase):
    def test_image_checks_wsgi_import_as_web_user_after_copy(self):
        dockerfile=(settings.BASE_DIR/'Dockerfile').read_text(encoding='utf-8')
        self.assertGreater(dockerfile.index('chmod -R a+rX /app'),dockerfile.index('COPY --from=frontend'))
        self.assertIn("su -s /bin/sh appuser",dockerfile)
        self.assertIn('from config.wsgi import application',dockerfile)

    def test_supervisor_owns_root_log_pipes_workers_are_unprivileged(self):
        config=configparser.ConfigParser()
        config.read(settings.BASE_DIR/'deploy'/'supervisord.conf')
        self.assertNotEqual(config.get('supervisord','user',fallback='root'),'appuser')
        for section in ['program:web','program:monitor']:
            self.assertEqual(config.get(section,'user',fallback='root'),'appuser')
