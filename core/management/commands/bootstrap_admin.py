import getpass
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from core.models import User, Account, Audit
from django.db import transaction

class Command(BaseCommand):
    help = '创建首个受限应用管理员；不授予 Django 超级用户权限'
    def add_arguments(self, parser):
        parser.add_argument('username')

    @transaction.atomic
    def handle(self, username, **options):
        if User.objects.filter(is_app_admin=True).exists():
            raise CommandError('已存在应用管理员；不能用初始化命令追加管理员')
        if User.objects.filter(username=username).exists():
            raise CommandError('用户名已存在，不能将现有账号提权')
        user = User(username=username, is_app_admin=True)
        password = getpass.getpass('管理员密码（至少10位）: ')
        if password != getpass.getpass('再次输入: '):
            raise CommandError('两次输入不一致')
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError('；'.join(exc.messages))
        user.set_password(password); user.save()
        Account.objects.create(user=user)
        Audit.objects.create(actor=user, action='bootstrap_admin', object_id=str(user.pk))
        self.stdout.write(self.style.SUCCESS('应用管理员已创建。请登录并初始化自己的账本。'))
