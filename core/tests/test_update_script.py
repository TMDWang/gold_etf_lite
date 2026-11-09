import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from django.conf import settings
from django.test import SimpleTestCase

class UpdateScriptTests(SimpleTestCase):
    def setUp(self):
        self.parent = settings.BASE_DIR / '.update-tests'
        self.parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.parent)
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / 'project'
        (self.project / 'deploy').mkdir(parents=True)
        shutil.copyfile(settings.BASE_DIR / 'deploy' / 'update.sh', self.project / 'deploy' / 'update.sh')
        fake = Path(self.temp.name) / 'bin'; fake.mkdir()
        (fake/'git').write_text('''#!/bin/sh
printf 'git %s\\n' "$*" >> "$PWD/commands.log"
case "$*" in
  'rev-parse --show-toplevel') pwd;;
  'rev-parse HEAD') printf '%s\n' 'test-sha';;
  'symbolic-ref --quiet --short HEAD') printf '%s\\n' "${TEST_BRANCH:-main}";;
  'status --porcelain') [ "${TEST_DIRTY:-0}" = 1 ] && printf ' M file\\n'; exit 0;;
  'pull --ff-only origin main') [ "${TEST_PULL_FAIL:-0}" = 0 ] || exit 1;;
  *) exit 2;;
esac
''',encoding='utf-8')
        (fake/'docker').write_text('''#!/bin/sh
printf 'docker %s\\n' "$*" >> "$PWD/commands.log"
case "$*" in
  'info') exit 0;;
  'compose exec -T app python manage.py backup') [ "${TEST_BACKUP_FAIL:-0}" = 0 ] || exit 1;;
  'compose up -d --build --wait --wait-timeout 240') [ "${TEST_BUILD_FAIL:-0}" = 0 ] || exit 1;;
  'compose ps') exit 0;;
  'compose ps -q app') printf '%s\n' 'test-app';;
  inspect*) printf '%s\n' "${TEST_RUNNING_REVISION:-test-sha}";;
  *) exit 2;;
esac
''',encoding='utf-8')
        for name in ['git','docker']:(fake/name).chmod(0o755)
        self.env={**os.environ,'TEST_FAKE_BIN':str(fake)}
        bash='C:/Program Files/Git/bin/bash.exe' if os.name=='nt' else shutil.which('bash')
        self.bash=bash

    def run_update(self, **flags):
        prefix='$(cygpath -u "$TEST_FAKE_BIN")' if os.name=='nt' else '$TEST_FAKE_BIN'
        return subprocess.run([self.bash, '-c', f'PATH="{prefix}:$PATH"; export PATH; exec sh "$1"', 'test', str(self.project/'deploy'/'update.sh')], cwd=self.project,
                              env={**self.env,**flags},capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20)

    def calls(self):
        p=self.project/'commands.log'
        return p.read_text(encoding='utf-8').splitlines() if p.exists() else []

    def test_success_backs_up_before_pull_then_builds_and_shows_status(self):
        result=self.run_update()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        calls=self.calls()
        self.assertLess(calls.index('docker compose exec -T app python manage.py backup'),calls.index('git pull --ff-only origin main'))
        self.assertLess(calls.index('git pull --ff-only origin main'),calls.index('docker compose up -d --build --wait --wait-timeout 240'))
        self.assertIn('docker compose ps',calls)

    def test_failed_backup_or_dirty_checkout_never_pulls_or_rebuilds(self):
        result=self.run_update(TEST_BACKUP_FAIL='1')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('git pull --ff-only origin main',self.calls())
        (self.project/'commands.log').unlink()
        result=self.run_update(TEST_DIRTY='1')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(x.startswith('docker ') for x in self.calls()))

    def test_wrong_branch_and_failed_pull_never_rebuild(self):
        result=self.run_update(TEST_BRANCH='other')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('git pull --ff-only origin main',self.calls())
        (self.project/'commands.log').unlink()
        result=self.run_update(TEST_PULL_FAIL='1')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('docker compose up -d --build --wait --wait-timeout 240',self.calls())

    def test_running_revision_must_match_the_checkout(self):
        result = self.run_update(TEST_RUNNING_REVISION='stale')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('stale', result.stderr)

    def test_failed_health_wait_reports_status_and_exits(self):
        result = self.run_update(TEST_BUILD_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('docker compose ps', self.calls())
        self.assertIn('健康', result.stderr)
