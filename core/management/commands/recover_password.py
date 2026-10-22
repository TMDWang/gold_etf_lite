import getpass
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from core.models import User, Audit

class Command(BaseCommand):
    help = '仅 NAS 维护者使用；核实本人身份后恢复密码'
    def add_arguments(self, parser):
        parser.add_argument('username')
    def handle(self, username, **options):
        try:
            user=User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError('账号不存在')
        password=getpass.getpass('新密码（已核实账号本人身份）: ')
        if password != getpass.getpass('再次输入: '):
            raise CommandError('两次输入不一致')
        try:
            validate_password(password,user)
        except ValidationError as exc:
            raise CommandError('；'.join(exc.messages))
        user.set_password(password); user.save(update_fields=['password'])
        Audit.objects.create(actor=None,action='operator_password_recovery',object_id=str(user.pk))
        self.stdout.write('密码已恢复，原会话会因密码变更失效。')
