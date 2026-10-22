import tempfile
from pathlib import Path
from unittest.mock import patch
from django.test import TestCase, override_settings
from core.models import SystemState

class BackupTests(TestCase):
    def test_failed_dump_never_prunes_good_backups(self):
        from core.backup import run_backup
        with tempfile.TemporaryDirectory() as tmp, override_settings(BACKUP_DIR=Path(tmp)):
            good=Path(tmp)/'gold_20261001.dump';good.write_bytes(b'keep')
            with patch('core.backup.subprocess.run',side_effect=RuntimeError('failed')):
                with self.assertRaises(RuntimeError):run_backup()
            self.assertEqual(good.read_bytes(),b'keep')
            self.assertFalse(list(Path(tmp).glob('*.partial')))

    def test_success_is_verified_before_rename_and_prune(self):
        from core.backup import run_backup
        with tempfile.TemporaryDirectory() as tmp, override_settings(BACKUP_DIR=Path(tmp)):
            for i in range(32):(Path(tmp)/f'gold_202609{i:02}.dump').write_bytes(b'old')
            def run(cmd,**kw):
                if cmd[0]=='pg_dump':Path(cmd[cmd.index('--file')+1]).write_bytes(b'valid dump')
            with patch('core.backup.subprocess.run',side_effect=run) as runner:
                target=run_backup()
            self.assertTrue(target.exists());self.assertEqual(len(list(Path(tmp).glob('*.dump'))),30)
            self.assertEqual(runner.call_args_list[1].args[0][0],'pg_restore')
            self.assertTrue(SystemState.objects.get(pk='backup').value['last_success'])
