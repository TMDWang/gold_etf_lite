from django.test import TestCase
from rest_framework.test import APIClient
from core.models import User

class AuthTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('owner', password='Example-safe-password42!', is_app_admin=True)
        self.member = User.objects.create_user('member', password='Example-safe-password42!')
        self.c = APIClient()

    def test_invite_register_once_no_role_injection(self):
        self.c.force_login(self.admin)
        result = self.c.post('/api/admin/invites/', {}, format='json')
        self.assertEqual(result.status_code, 201)
        code = result.json()['code']
        self.c.logout()
        data = {'code': code, 'username': 'friend', 'password': 'Another-good-password42!', 'is_app_admin': True}
        self.assertEqual(self.c.post('/api/auth/register/', data, format='json').status_code, 201)
        self.assertFalse(User.objects.get(username='friend').is_app_admin)
        data['username'] = 'friend2'
        self.assertEqual(self.c.post('/api/auth/register/', data, format='json').status_code, 400)

    def test_admin_scope_and_disable(self):
        self.c.force_login(self.member)
        self.assertEqual(self.c.get('/api/admin/users/').status_code, 403)
        self.c.force_login(self.admin)
        result = self.c.get('/api/admin/users/')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(set(result.json()[0]), {'id', 'username', 'is_active', 'is_app_admin'})
        self.assertEqual(self.c.patch(f'/api/admin/users/{self.member.pk}/', {'is_active': False}, format='json').status_code, 200)
        self.c.force_login(self.member)
        self.assertEqual(self.c.get('/api/me/').status_code, 403)

    def test_login_csrf_and_private_response(self):
        c = APIClient(enforce_csrf_checks=True)
        r = c.get('/api/auth/csrf/')
        self.assertEqual(r.status_code, 200)
        data = {'username': 'owner', 'password': 'Example-safe-password42!'}
        self.assertEqual(c.post('/api/auth/login/', data, format='json').status_code, 403)
        self.assertEqual(c.post('/api/auth/login/', data, format='json', HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value).status_code, 200)
        self.assertIn('no-store', c.get('/api/me/')['Cache-Control'])
