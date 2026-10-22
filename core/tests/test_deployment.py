import configparser
from django.conf import settings
from django.test import SimpleTestCase

class DeploymentTests(SimpleTestCase):
    def test_supervisor_owns_root_log_pipes_workers_are_unprivileged(self):
        config=configparser.ConfigParser()
        config.read(settings.BASE_DIR/'deploy'/'supervisord.conf')
        self.assertNotEqual(config.get('supervisord','user',fallback='root'),'appuser')
        for section in ['program:web','program:monitor']:
            self.assertEqual(config.get(section,'user',fallback='root'),'appuser')
