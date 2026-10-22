from django.http import JsonResponse, FileResponse, HttpResponse
from django.conf import settings
from django.db import connection
from django.urls import path
from core import auth_views as a, views as v

def health(request):
    from core.monitor import worker_ok
    try:
        with connection.cursor() as cursor:cursor.execute('SELECT 1')
        ok=worker_ok()
    except Exception:
        ok=False
    return JsonResponse({'status':'ok' if ok else 'degraded'},status=200 if ok else 503)

def index(request):
    target=settings.BASE_DIR/'frontend'/'dist'/'index.html'
    if target.exists():
        response=FileResponse(target.open('rb'),content_type='text/html; charset=utf-8')
        response['Cache-Control']='no-cache'
        return response
    return HttpResponse('请先构建前端，参见 README.md',status=503)

def service_worker(request):
    target=settings.BASE_DIR/'frontend'/'dist'/'sw.js'
    if not target.exists():return HttpResponse('请重新构建前端',status=404)
    response=FileResponse(target.open('rb'),content_type='application/javascript; charset=utf-8')
    response['Cache-Control']='no-cache, max-age=0, must-revalidate'
    response['Service-Worker-Allowed']='/'
    return response

urlpatterns = [
    path('',index),path('health/',health),path('sw.js',service_worker),
    path('api/auth/csrf/',a.CsrfView.as_view()),path('api/auth/login/',a.LoginView.as_view()),
    path('api/auth/register/',a.RegisterView.as_view()),path('api/auth/logout/',a.LogoutView.as_view()),path('api/auth/password/',a.PasswordView.as_view()),
    path('api/me/',a.MeView.as_view()),path('api/account/',v.AccountView.as_view()),path('api/account/initialize/',v.InitializeView.as_view()),
    path('api/entries/',v.EntriesView.as_view()),path('api/cash/',v.CashView.as_view()),path('api/entries/<int:pk>/correct/',v.CorrectView.as_view()),
    path('api/plans/',v.PlansView.as_view()),path('api/plans/<int:pk>/',v.PlanDetailView.as_view()),path('api/plans/<int:pk>/cancel/',v.CancelPlanView.as_view()),
    path('api/episodes/',v.EpisodesView.as_view()),path('api/episodes/<int:pk>/ignore/',v.IgnoreView.as_view()),
    path('api/settings/',v.SettingsView.as_view()),path('api/settings/test-push/',v.TestPushView.as_view()),path('api/deliveries/',v.DeliveryView.as_view()),
    path('api/market/',v.MarketView.as_view()),path('api/admin/invites/',a.InvitesView.as_view()),
    path('api/admin/users/',a.AdminUsersView.as_view()),path('api/admin/users/<int:pk>/',a.AdminUsersView.as_view()),path('api/admin/system/',v.SystemView.as_view()),
]
