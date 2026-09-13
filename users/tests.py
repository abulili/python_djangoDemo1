from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status

from .models import UserProfile

# Create your tests here.

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


