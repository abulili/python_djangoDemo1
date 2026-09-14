from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status

from .models import UserProfile, LoginEvent, IPBlockRule, RequestRiskEvent
from django.utils import timezone

from django.core.cache import cache

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

class ForceLogoutUsersTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            username="force_logout_user1",
            password="123456",
        )
        self.user2 = User.objects.create_user(
            username="force_logout_user2",
            password="123456",
        )
        self.normal_user = User.objects.create_user(
            username="force_logout_normal",
            password="123456",
        )
        self.admin = User.objects.create_superuser(
            username="force_logout_admin",
            password="123456",
            email="force-admin@example.com",
        )

        self.client = APIClient()

    def test_normal_user_cannot_force_logout_users(self):
        self.client.force_authenticate(user=self.normal_user)

        response = self.client.post("/api/users/force-logout/", {
            "user_ids": [self.user1.id],
        }, format="json")

        self.assertEqual(response.status_code, 403)

    def test_admin_can_force_logout_users(self):
        self.client.force_authenticate(user=self.admin)

        before_user1_version = self.user1.profile.token_version
        before_user2_version = self.user2.profile.token_version

        response = self.client.post("/api/users/force-logout/", {
            "user_ids": [self.user1.id, self.user2.id],
        }, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["requested_count"], 2) # 因为传了两个用户
        self.assertEqual(response.data["data"]["updated_count"], 2)

        self.user1.profile.refresh_from_db() # self.user1.profile因为这个 Python 对象可能还是旧数据，所以重新从数据库加载这个 profile 的最新值
        self.user2.profile.refresh_from_db()

        self.assertEqual(self.user1.profile.token_version, before_user1_version + 1)
        self.assertEqual(self.user2.profile.token_version, before_user2_version + 1)

    def test_force_logout_returns_missing_user_ids(self):
        self.client.force_authenticate(user=self.admin)

        missing_user_id = 999999

        response = self.client.post("/api/users/force-logout/", {
            "user_ids": [self.user1.id, missing_user_id],
        }, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["requested_count"], 2)
        self.assertEqual(response.data["data"]["updated_count"], 1) # 表示实际数据库里找到并更新了几个用户
        self.assertEqual(response.data["data"]["updated_user_ids"], [self.user1.id])
        self.assertEqual(response.data["data"]["missing_user_ids"], [missing_user_id])

    def test_force_logout_requires_user_ids(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.post("/api/users/force-logout/", {
            "user_ids": [],
        }, format="json")

        self.assertEqual(response.status_code, 400)

    def test_force_logout_invalidates_user_access_token(self):
        login_client = APIClient()
        login_response = login_client.post("/api/token/", {
            "username": "force_logout_user1",
            "password": "123456",
        }, format="json")
        self.assertEqual(login_response.status_code, 200)

        access = login_response.data["access"]

        admin_client = APIClient()
        admin_client.force_authenticate(user=self.admin)

        force_response = admin_client.post("/api/users/force-logout/", {
            "user_ids": [self.user1.id],
        }, format="json")
        self.assertEqual(force_response.status_code, 200)

        old_client = APIClient()
        old_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = old_client.get("/api/logs/")
        self.assertEqual(response.status_code, 401)

class BanUsersTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="ban_target_user",
            password="123456",
        )
        self.normal_user = User.objects.create_user(
            username="ban_normal_user",
            password="123456",
        )
        self.admin = User.objects.create_superuser(
            username="ban_admin_user",
            password="123456",
            email="ban-admin@example.com",
        )
        self.client = APIClient()

    def test_normal_user_cannot_ban_users(self):
        self.client.force_authenticate(user=self.normal_user)

        response = self.client.post("/api/users/ban/", {
            "user_ids": [self.user.id],
            "reason": "测试封禁",
        }, format="json")

        self.assertEqual(response.status_code, 403)

    def test_admin_can_ban_user(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.post("/api/users/ban/", {
            "user_ids": [self.user.id],
            "ban_reason": "异常请求",
        }, format="json")

        self.assertEqual(response.status_code, 200)

        profile = UserProfile.objects.get(user=self.user)

        self.assertTrue(profile.is_banned)
        self.assertEqual(profile.ban_reason, "异常请求")
        self.assertIsNotNone(profile.banned_at)

    def test_ban_invalidates_access_token(self):
        login_response = self.client.post("/api/token/", {
            "username": "ban_target_user",
            "password": "123456",
        }, format="json")
        self.assertEqual(login_response.status_code, 200)

        access = login_response.data["access"]

        # 模拟管理员登录
        admin_client = APIClient()
        admin_client.force_authenticate(user=self.admin)

        response = admin_client.post("/api/users/ban/", {
            "user_ids": [self.user.id],
            "ban_reason": "异常请求",
        }, format="json")
        self.assertEqual(response.status_code, 200)

        user_client = APIClient()
        user_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = user_client.get("/api/logs/")
        # 被封禁后，旧 access token 不能再访问业务接口，应该返回 401。
        self.assertEqual(response.status_code, 401)

    def test_banned_user_cannot_refresh_token(self):
        login_response = self.client.post("/api/token/", {
            "username": "ban_target_user",
            "password": "123456",
        }, format="json")
        self.assertEqual(login_response.status_code, 200)

        refresh = login_response.data["refresh"]

        admin_client = APIClient()
        admin_client.force_authenticate(user=self.admin)
        ban_response = admin_client.post("/api/users/ban/", {
            "user_ids": [self.user.id],
            "ban_reason": "异常请求",
        }, format="json")
        self.assertEqual(ban_response.status_code, 200)

        response = self.client.post("/api/token/refresh/", {
            "refresh": refresh,
        }, format="json")
        self.assertEqual(response.status_code, 401)

    def test_admin_can_unban_user(self):
        self.user.profile.is_banned = True
        self.user.profile.ban_reason = "异常请求"
        self.user.profile.banned_at = timezone.now()
        self.user.profile.save(update_fields=["is_banned", "ban_reason", "banned_at"])

        self.client.force_authenticate(user=self.admin)

        response = self.client.post("/api/users/unban/", {
            "user_ids": [self.user.id],
        }, format="json")

        self.assertEqual(response.status_code, 200)

        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.is_banned)
        self.assertEqual(self.user.profile.ban_reason, "")
        self.assertIsNone(self.user.profile.banned_at)

    def test_unbanned_user_can_login_again(self):
        self.user.profile.is_banned = True
        self.user.profile.ban_reason = "异常请求"
        self.user.profile.banned_at = timezone.now()
        self.user.profile.save(update_fields=["is_banned", "ban_reason", "banned_at"])

        self.client.force_authenticate(user=self.admin)
        response = self.client.post("/api/users/unban/", {
            "user_ids": [self.user.id],
        }, format="json")
        self.assertEqual(response.status_code, 200)

        login_response = self.client.post("/api/token/", {
            "username": "ban_target_user",
            "password": "123456",
        }, format="json")

        self.assertEqual(login_response.status_code, 200)
        self.assertIn("access", login_response.data)

    def test_banned_user_cannot_login(self):
        self.user.profile.is_banned = True
        self.user.profile.ban_reason = "异常请求"
        self.user.profile.banned_at = timezone.now()
        self.user.profile.save(update_fields=["is_banned", "ban_reason", "banned_at"])

        response = self.client.post("/api/token/", {
            "username": "ban_target_user",
            "password": "123456",
        }, format="json")

        self.assertEqual(response.status_code, 401)

@override_settings(IP_BLOCK_EXEMPT_IPS=[])
class IPBlockRuleTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="ip_block_admin",
            password="123456",
            email="ip-block-admin@example.com",
        )
        self.user = User.objects.create_user(
            username="ip_block_user",
            password="123456",
        )
        self.client = APIClient()

    def test_normal_user_cannot_create_ip_block_rule(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post("/api/users/ip-block-rules/", {
            "ip_address": "8.8.8.8",
            "reason": "异常请求",
        }, format="json")

        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_ip_block_rule(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.post("/api/users/ip-block-rules/", {
            "ip_address": "8.8.8.8",
            "reason": "异常请求",
        }, format="json")

        self.assertEqual(response.status_code, 201)

        rule = IPBlockRule.objects.get(ip_address="8.8.8.8")
        self.assertTrue(rule.is_active)
        self.assertEqual(rule.reason, "异常请求")
        self.assertEqual(rule.blocked_by, self.admin)

    def test_admin_can_filter_active_ip_block_rules(self):
        IPBlockRule.objects.create(
            ip_address="8.8.8.8",
            reason="异常请求",
            is_active=True,
            blocked_by=self.admin,
        )
        IPBlockRule.objects.create(
            ip_address="1.1.1.1",
            reason="已解除",
            is_active=False,
            blocked_by=self.admin,
        )

        self.client.force_authenticate(user=self.admin)

        response = self.client.get("/api/users/ip-block-rules/?is_active=true")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["ip_address"], "8.8.8.8")

    def test_blocked_ip_is_rejected_by_middleware(self):
        IPBlockRule.objects.create(
            ip_address="8.8.8.8",
            reason="异常请求",
            is_active=True,
            blocked_by=self.admin,
        )

        response = self.client.get(
            "/api/users/register/",
            REMOTE_ADDR="8.8.8.8",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["message"], "当前 IP 已被限制访问")

    def test_inactive_blocked_ip_is_allowed(self):
        IPBlockRule.objects.create(
            ip_address="8.8.8.8",
            reason="已解除",
            is_active=False,
            blocked_by=self.admin,
        )

        response = self.client.get(
            "/api/users/register/",
            REMOTE_ADDR="8.8.8.8",
        )

        self.assertNotEqual(response.status_code, 403)

    @override_settings(IP_BLOCK_EXEMPT_IPS=["8.8.8.8"])
    def test_exempt_ip_is_allowed_even_when_blocked(self):
        IPBlockRule.objects.create(
            ip_address="8.8.8.8",
            reason="管理员 IP 豁免",
            is_active=True,
            blocked_by=self.admin,
        )

        response = self.client.get(
            "/healthy/",
            REMOTE_ADDR="8.8.8.8",
        )

        self.assertNotEqual(response.status_code, 403)

    def test_x_forwarded_for_blocked_ip_is_rejected(self):
        IPBlockRule.objects.create(
            ip_address="8.8.8.8",
            reason="代理后的真实 IP 被封",
            is_active=True,
            blocked_by=self.admin,
        )

        response = self.client.get(
            "/healthy/",
            REMOTE_ADDR="10.0.0.1",
            HTTP_X_FORWARDED_FOR="8.8.8.8, 10.0.0.1",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["message"], "当前 IP 已被限制访问")

@override_settings(
    SECURITY_RISK_EVENT_ENABLED=True,
    SECURITY_RISK_WINDOW_SECONDS=60,
    SECURITY_RISK_THRESHOLD=3,
    IP_BLOCK_EXEMPT_IPS=[],
)
class RequestRiskEventTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def tearDown(self):
        cache.clear()

    def test_records_auth_failed_risk_event_after_threshold(self):
        for _ in range(3):
            self.client.get(
                "/api/ai-trace-step-logs/",
                REMOTE_ADDR="8.8.8.8",
            )

        event = RequestRiskEvent.objects.get(
            ip_address="8.8.8.8",
            risk_type="auth_failed"
        )

        self.assertEqual(event.status_code, 401)
        self.assertEqual(event.count, 3)
        self.assertEqual(event.path, "/api/ai-trace-step-logs/")
        self.assertEqual(event.method, "GET")

    def test_does_not_record_before_threshold(self):
        for _ in range(2):
            self.client.get(
                "/api/ai-trace-step-logs/",
                REMOTE_ADDR="8.8.8.8",
            )

        self.assertEqual(RequestRiskEvent.objects.count(), 0)

    def test_records_rate_limited_risk_event(self):
        response = self.client.get(
            "/api/ai-trace-step-logs/",
            REMOTE_ADDR="8.8.8.8",
        )
        response.status_code = 429

        from users.utils import record_request_risk_event

        """
        record_request_risk_event(request, response)
        但你没有 request 对象。
        Django 测试响应里会保存原始请求：
        拿刚才 self.client.get(...) 产生的那个请求对象，假装它对应一个 429 响应，用来测试风险记录函数。
        主要是为了测 429 rate_limited，不用真的触发限流
        """
        fake_request = response.wsgi_request

        for _ in range(3):
            record_request_risk_event(fake_request, response)

        event = RequestRiskEvent.objects.get(risk_type="rate_limited")
        self.assertEqual(event.status_code, 429)
        self.assertEqual(event.count, 3)

    def test_request_risk_event_disabled(self):
        with override_settings(SECURITY_RISK_EVENT_ENABLED=False):
            for _ in range(3):
                self.client.get(
                    "/api/ai-trace-step-logs/",
                    REMOTE_ADDR="8.8.8.8",
                )

        self.assertEqual(RequestRiskEvent.objects.count(), 0)

        
            

    



