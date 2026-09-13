from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status

from .models import UserProfile, LoginEvent

# Create your tests here.
@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": (
            "users.authentication.SingleSessionJWTAuthentication",
        ),
        "DEFAULT_THROTTLE_CLASSES": [],
        "DEFAULT_THROTTLE_RATES": {
            "user": "1000/minute",
            "anon": "1000/minute",
            "ai_call": "1000/minute",
            "task_status": "1000/minute",
        },
    }
)
class SingleSessionLoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="single_login_user",
            password="123456",
            email="single@example.com",
        )
        self.client = APIClient()

    # 登录会创建/更新 profile
    def test_login_increments_token_version(self):
        profile = self.user.profile
        self.assertEqual(profile.token_version, 0)

        response = self.client.post("/api/token/", {
            "username": "single_login_user",
            "password": "123456",
        }, format="json")

        self.assertEqual(response.status_code, 200)
        profile.refresh_from_db()
        self.assertEqual(profile.token_version, 1)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    # 第二次登录后旧 token 失效
    def test_old_access_token_invalid_after_second_login(self):
        first_login = self.client.post("/api/token/", {
            "username": "single_login_user",
            "password": "123456",
        }, format="json")
        self.assertEqual(first_login.status_code, 200)
        old_access = first_login.data["access"]

        second_login = self.client.post("/api/token/", {
            "username": "single_login_user",
            "password": "123456",
        }, format="json")
        self.assertEqual(second_login.status_code, 200)
        new_access = second_login.data["access"]

        old_client = APIClient()
        old_client.credentials(HTTP_AUTHORIZATION=f"Bearer {old_access}")
        old_response = old_client.get("/api/logs/")

        self.assertEqual(old_response.status_code, 401)

        new_client = APIClient()
        new_client.credentials(HTTP_AUTHORIZATION=f"Bearer {new_access}")
        new_response = new_client.get("/api/logs/")

        self.assertNotEqual(new_response.status_code, 401)

    # 登录记录 IP 和 User-Agent
    def test_login_records_ip_and_user_agent(self):
        response = self.client.post(
            "/api/token/",
            {
                "username": "single_login_user",
                "password": "123456",
            },
            format="json",
            # Web 服务器/Django 根据连接信息放进来的，这次请求的来源 IP
            REMOTE_ADDR="127.0.0.1",
            HTTP_USER_AGENT="test-browser",
        )
        self.assertEqual(response.status_code, 200)

        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.last_login_ip, "127.0.0.1")
        self.assertEqual(profile.last_login_user_agent, "test-browser")
        self.assertIsNotNone(profile.last_login_at)

    # X-Forwarded-For 优先
    def test_login_uses_x_forwarded_for_ip(self):
        response = self.client.post(
            "/api/token/",
            {
                "username": "single_login_user",
                "password": "123456",
            },
            format="json",
            REMOTE_ADDR="10.0.0.1",
            # 因为profile.last_login_ip = forwarded_for.split(',')[0].strip() 第一个通常是用户原始 IP
            HTTP_X_FORWARDED_FOR="8.8.8.8, 10.0.0.1",
        )

        self.assertEqual(response.status_code, 200)

        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.last_login_ip, "8.8.8.8")

    def test_login_creates_login_event(self):
        response = self.client.post(
            "/api/token/",
            {
                "username": "single_login_user",
                "password": "123456",
            },
            format="json",
            REMOTE_ADDR="127.0.0.1",
            HTTP_USER_AGENT="test-browser",
        )

        self.assertEqual(response.status_code, 200)

        event = LoginEvent.objects.get(user=self.user)
        self.assertEqual(event.ip_address, "127.0.0.1")
        self.assertEqual(event.user_agent, "test-browser")
        self.assertEqual(event.token_version, 1)
        self.assertTrue(event.success)
        self.assertEqual(event.reason, "login_success")

    def test_old_refresh_token_invalid_after_second_login(self):
        first_login = self.client.post("/api/token/", {
            "username": "single_login_user",
            "password": "123456",
        }, format="json")
        self.assertEqual(first_login.status_code, 200)
        old_refresh = first_login.data["refresh"]

        second_login = self.client.post("/api/token/", {
            "username": "single_login_user",
            "password": "123456",
        }, format="json")
        self.assertEqual(second_login.status_code, 200)

        response = self.client.post("/api/token/refresh/", {
            "refresh": old_refresh,
        }, format="json")

        self.assertEqual(response.status_code, 401)

    def test_latest_refresh_token_can_refresh_access(self):
        login_response = self.client.post("/api/token/", {
            "username": "single_login_user",
            "password": "123456",
        }, format="json")
        self.assertEqual(login_response.status_code, 200)

        response = self.client.post("/api/token/refresh/", {
            "refresh": login_response.data["refresh"],
        }, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)

    def test_logout_invalidates_current_access_token(self):
        login_response = self.client.post("/api/token/", {
            "username": "single_login_user",
            "password": "123456",
        }, format="json")
        self.assertEqual(login_response.status_code, 200)

        access = login_response.data["access"]

        auth_client = APIClient()
        auth_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        logout_response = auth_client.post("/api/users/logout/")
        self.assertEqual(logout_response.status_code, 200)

        old_response = auth_client.get("/api/logs/")
        self.assertEqual(old_response.status_code, 401)

    def test_logout_invalidates_current_refresh_token(self):
        login_response = self.client.post("/api/token/", {
            "username": "single_login_user",
            "password": "123456",
        }, format="json")
        self.assertEqual(login_response.status_code, 200)

        access = login_response.data["access"]
        refresh = login_response.data["refresh"]

        auth_client = APIClient()
        auth_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        logout_response = auth_client.post("/api/users/logout/")
        self.assertEqual(logout_response.status_code, 200)

        refresh_response = self.client.post("/api/token/refresh/", {
            "refresh": refresh,
        }, format="json")

        self.assertEqual(refresh_response.status_code, 401)

class LoginEventApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="normal_login_user",
            password="123456",
        )
        self.admin = User.objects.create_superuser(
            username="admin_login_user",
            password="123456",
            email="admin@example.com",
        )
        self.client = APIClient()

        LoginEvent.objects.create(
            user=self.user,
            ip_address="127.0.0.1",
            user_agent="normal-browser",
            token_version=1,
            success=True,
            reason="login_success",
        )
        LoginEvent.objects.create(
            user=self.admin,
            ip_address="8.8.8.8",
            user_agent="admin-browser",
            token_version=1,
            success=True,
            reason="login_success",
        )

    def test_normal_user_cannot_query_login_events(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.get("/api/users/login-events/")

        self.assertEqual(response.status_code, 403)

    def test_admin_can_query_login_events(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.get("/api/users/login-events/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)

    def test_admin_can_filter_login_events_by_username(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.get("/api/users/login-events/?username=normal")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["username"], "normal_login_user")

    def test_admin_can_filter_login_events_by_success(self):
        LoginEvent.objects.create(
            user=self.user,
            ip_address="127.0.0.2",
            user_agent="failed-browser",
            token_version=1,
            success=False,
            reason="login_failed",
        )

        self.client.force_authenticate(user=self.admin)

        response = self.client.get("/api/users/login-events/?success=false")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["reason"], "login_failed")
