import hashlib
import secrets
from datetime import timedelta
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from core.models import User, Invitation, Account, Audit
from core.common import BusinessError, throttle

def identity(user):
    return {'id':user.pk,'username':user.username,'is_app_admin':user.is_app_admin}

def csrf(request):
    SessionAuthentication().enforce_csrf(request)

def password_valid(password,user):
    try:
        validate_password(password,user)
    except ValidationError as exc:
        raise BusinessError('；'.join(exc.messages))

def public_limit(request,label):
    # Forwarded client IP is not trusted: all proxy traffic shares the conservative bucket.
    ip=request.META.get('REMOTE_ADDR','unknown')
    throttle(f'{label}:{hashlib.sha256(ip.encode()).hexdigest()}',20,300)

class CsrfView(APIView):
    permission_classes=[AllowAny]
    def get(self,request):
        return Response({'csrfToken':get_token(request)})

class LoginView(APIView):
    permission_classes=[AllowAny]
    def post(self,request):
        csrf(request);public_limit(request,'login')
        username=str(request.data.get('username',''))[:150]
        password=request.data.get('password','')
        if not isinstance(password,str) or len(password)>256:
            raise BusinessError('用户名或密码不正确')
        user=authenticate(request,username=username,password=password)
        if not user:
            raise BusinessError('用户名或密码不正确，或账号已停用')
        login(request,user)
        return Response(identity(user))

class RegisterView(APIView):
    permission_classes=[AllowAny]
    def post(self,request):
        csrf(request);public_limit(request,'register')
        username=request.data.get('username','')
        password=request.data.get('password','')
        code=request.data.get('code','')
        if not all(isinstance(x,str) for x in (username,password,code)) or not username or len(username)>50 or len(password)>256 or len(code)>100:
            raise BusinessError('请填写有效的用户名、密码和邀请码')
        try:
            User._meta.get_field('username').run_validators(username)
        except ValidationError:
            raise BusinessError('用户名只能包含字母、数字及 @ . + - _')
        user=User(username=username)
        password_valid(password,user)
        with transaction.atomic():
            invite=Invitation.objects.select_for_update().filter(code_hash=hashlib.sha256(code.strip().encode()).hexdigest()).first()
            if not invite or invite.used_by_id or invite.expires_at<=timezone.now():
                raise BusinessError('邀请码无效、已使用或已过期')
            # Uniqueness is also protected by the database constraint.
            if User.objects.filter(username=username).exists():
                raise BusinessError('用户名已被使用')
            user.set_password(password);user.save();Account.objects.create(user=user)
            invite.used_by=user;invite.save(update_fields=['used_by'])
            Audit.objects.create(actor=user,action='register',object_id=str(user.pk))
        login(request,user)
        return Response(identity(user),status=201)

class LogoutView(APIView):
    def post(self,request):
        logout(request)
        return Response({'detail':'已退出'})

class MeView(APIView):
    def get(self,request):
        return Response(identity(request.user))

class PasswordView(APIView):
    def post(self,request):
        throttle(f'password:{request.user.pk}',5,300)
        old=request.data.get('old_password','');new=request.data.get('new_password','')
        if not isinstance(old,str) or not isinstance(new,str) or len(new)>256 or not request.user.check_password(old):
            raise BusinessError('当前密码不正确或新密码无效')
        password_valid(new,request.user)
        request.user.set_password(new);request.user.save(update_fields=['password'])
        update_session_auth_hash(request,request.user)
        Audit.objects.create(actor=request.user,action='change_password',object_id=str(request.user.pk))
        return Response({'detail':'密码已更新'})

class AppAdmin(BasePermission):
    def has_permission(self,request,view):
        return bool(request.user and request.user.is_authenticated and request.user.is_active and request.user.is_app_admin)

class InvitesView(APIView):
    permission_classes=[AppAdmin]
    def post(self,request):
        throttle(f'invite:{request.user.pk}',30,86400)
        code=secrets.token_urlsafe(18)
        Invitation.objects.create(code_hash=hashlib.sha256(code.encode()).hexdigest(),created_by=request.user,expires_at=timezone.now()+timedelta(days=7))
        Audit.objects.create(actor=request.user,action='create_invite')
        return Response({'code':code,'valid_days':7},status=201)

class AdminUsersView(APIView):
    permission_classes=[AppAdmin]
    def get(self,request):
        return Response(list(User.objects.order_by('id').values('id','username','is_active','is_app_admin')[:2000]))
    def patch(self,request,pk):
        if set(request.data)!={'is_active'} or not isinstance(request.data['is_active'],bool):
            raise BusinessError('这里只支持账号启停')
        with transaction.atomic():
            user=get_object_or_404(User.objects.select_for_update(),pk=pk,is_app_admin=False,is_superuser=False)
            user.is_active=request.data['is_active'];user.save(update_fields=['is_active'])
            # Re-enabling an account must not resurrect its previous sessions.
            from django.contrib.sessions.models import Session
            for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
                if str(session.get_decoded().get('_auth_user_id'))==str(user.pk):
                    session.delete()
            Audit.objects.create(actor=request.user,action='enable_user' if user.is_active else 'disable_user',object_id=str(user.pk))
        return Response({'id':user.pk,'is_active':user.is_active})
