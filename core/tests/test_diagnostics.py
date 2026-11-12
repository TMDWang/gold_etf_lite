from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase
from core.models import SystemState


class DiagnosticsTests(TestCase):
    @patch('core.diagnostics.notify_maintainers')
    @patch('core.diagnostics.shutil.disk_usage')
    def test_fault_and_recovery_are_recorded_once_per_transition(self, disk, notify):
        from core.diagnostics import run_diagnostics
        now = datetime(2026, 11, 9, 16, tzinfo=ZoneInfo('Asia/Shanghai'))
        total = 100 * 1024**3
        with patch('django.utils.timezone.now', return_value=now):
            SystemState.objects.create(key='heartbeat', value={'ok':True})
            SystemState.objects.create(key='backup', value={'last_success':now.isoformat(),'ok':True})
            disk.return_value = SimpleNamespace(total=total, free=total//2)
            run_diagnostics(now)
            self.assertEqual(notify.call_count, 0)
            disk.return_value = SimpleNamespace(total=total, free=total//100)
            run_diagnostics(now)
            run_diagnostics(now)
            self.assertEqual(notify.call_count, 1)
            disk.return_value = SimpleNamespace(total=total, free=total//2)
            result = run_diagnostics(now)
            self.assertEqual(notify.call_count, 2)
            self.assertEqual(len(result['events']), 2)
            self.assertTrue(result['events'][0]['recovered'])
            self.assertNotIn('cash', str(result))
