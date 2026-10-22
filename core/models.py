from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    is_app_admin = models.BooleanField(default=False)
    token_encrypted = models.TextField(blank=True)
    fee_rate = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    fee_minimum = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    fee_extra = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    reminder_minutes = models.PositiveIntegerField(default=30)
    reminder_max = models.PositiveSmallIntegerField(default=3)


class Invitation(models.Model):
    code_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='invitations')
    expires_at = models.DateTimeField()
    used_by = models.OneToOneField(User, on_delete=models.PROTECT, null=True, blank=True, related_name='invitation')
    created_at = models.DateTimeField(auto_now_add=True)


class Account(models.Model):
    user = models.OneToOneField(User, on_delete=models.PROTECT)
    budget = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    initial_cash = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    initial_shares = models.PositiveIntegerField(default=0)
    initial_cost = models.DecimalField(max_digits=24, decimal_places=6, default=0)
    cash = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    shares = models.PositiveIntegerField(default=0)
    cost_basis = models.DecimalField(max_digits=24, decimal_places=6, default=0)
    realized = models.DecimalField(max_digits=24, decimal_places=6, default=0)
    initialized_at = models.DateTimeField(null=True, blank=True)


class Plan(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    side = models.CharField(max_length=4, choices=[('BUY', '买入'), ('SELL', '卖出')])
    direction = models.CharField(max_length=5, default='BELOW')
    target_price = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    target_profit = models.DecimalField(max_digits=9, decimal_places=4, null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    quantity = models.PositiveIntegerField(null=True, blank=True)
    sell_all = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=12, default='ACTIVE')
    condition_met = models.BooleanField(default=False)
    episode_counter = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'side'], condition=models.Q(status='ACTIVE'), name='one_active_plan_per_side')]
        indexes = [models.Index(fields=['user', 'status'])]


class Entry(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    kind = models.CharField(max_length=12)
    payload = models.JSONField()
    idempotency_key = models.CharField(max_length=80)
    request_hash = models.CharField(max_length=64)
    plan = models.OneToOneField(Plan, on_delete=models.PROTECT, null=True, blank=True)
    corrects = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True)
    reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'idempotency_key'], name='entry_idempotency_per_user')]
        indexes = [models.Index(fields=['user', '-id'])]


class Episode(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    version = models.PositiveIntegerField()
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=12, default='OPEN')
    sent_count = models.PositiveSmallIntegerField(default=0)
    next_at = models.DateTimeField()
    context = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['plan', 'version', 'number'], name='unique_plan_episode')]


class Delivery(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    episode = models.ForeignKey(Episode, on_delete=models.PROTECT, null=True, blank=True)
    status = models.CharField(max_length=12, default='SENDING')
    detail = models.CharField(max_length=200, blank=True)
    token_hash = models.CharField(max_length=64, blank=True, db_index=True)
    content_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Quote(models.Model):
    symbol = models.CharField(max_length=6, default='518880')
    price = models.DecimalField(max_digits=10, decimal_places=3)
    previous_close = models.DecimalField(max_digits=10, decimal_places=3, null=True)
    source = models.CharField(max_length=20)
    source_at = models.DateTimeField()
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['-source_at'])]


class Minute(models.Model):
    at = models.DateTimeField(unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=3)
    source = models.CharField(max_length=20)


class SystemState(models.Model):
    key = models.CharField(max_length=40, primary_key=True)
    value = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)


class Audit(models.Model):
    actor = models.ForeignKey(User, on_delete=models.PROTECT, null=True)
    action = models.CharField(max_length=40)
    object_id = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class RateWindow(models.Model):
    key = models.CharField(max_length=100, primary_key=True)
    started_at = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)
