from core.models import SystemState, PublicAlert, Plan

def lock_public_alerts():
    # Serialize template changes with registration to avoid missing a new user.
    SystemState.objects.get_or_create(key='public-alert-lock', defaults={'value': {}})
    SystemState.objects.select_for_update().get(key='public-alert-lock')

def copy_values(plan, rule):
    plan.alert_kind=rule.kind;plan.direction=rule.direction;plan.alert_threshold=rule.threshold
    plan.alert_interval=rule.interval;plan.alert_repeat_max=rule.repeat_max;plan.alert_label=rule.label

def subscribe_new_user(user):
    for rule in PublicAlert.objects.filter(active=True):
        plan=Plan(user=user,side='INFO',public_alert=rule)
        copy_values(plan,rule);plan.save()
