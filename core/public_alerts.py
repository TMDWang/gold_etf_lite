from core.models import SystemState

def lock_public_alerts():
    # Serialize template changes with registration to avoid missing a new user.
    SystemState.objects.get_or_create(key='public-alert-lock', defaults={'value': {}})
    SystemState.objects.select_for_update().get(key='public-alert-lock')
