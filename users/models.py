from django.db import models
from django.conf import settings
# Create your models here.
from django.db.models.signals import post_save
from django.dispatch import receiver

class UserProfile(models.Model):
    # UserProfile 一对一绑定当前项目正在使用的用户模型
    user = models.OneToOneField(
        # Django 配置里的用户模型名, 到时候需要改就：AUTH_USER_MODEL = "users.CustomUser"
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    token_version = models.PositiveIntegerField(default=0)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    last_login_user_agent = models.TextField(blank=True, default="")
    last_login_at = models.DateTimeField(null=True, blank=True)

    is_banned = models.BooleanField(default=False)
    ban_reason = models.CharField(max_length=255, blank=True, default="")
    banned_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user_id} token_version={self.token_version}"

    # Django signal 的接收器：当某件事发生后，自动执行这个函数。
    # 每次 User 保存之后，自动调用 create_user_profile。
    @receiver(post_save, sender=settings.AUTH_USER_MODEL)
    def create_user_profile(sender, instance, created, **kwargs):
        # sender：谁触发的信号，这里是指 User 模型
        # instance：触发信号的实例，这里是指 User 实例
        # created：是否是创建操作，这里是指创建 User 实例
        if created: # 老用户
            UserProfile.objects.create(user=instance)

class LoginEvent(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='login_events',
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    token_version = models.PositiveIntegerField(default=0)
    success = models.BooleanField(default=True)
    reason = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user_id} success={self.success} ip={self.ip_address}"

class IPBlockRule(models.Model):
    ip_address = models.GenericIPAddressField(unique=True)
    reason = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)
    blocked_at = models.DateTimeField(auto_now_add=True)
    # 这条 IP 黑名单是谁创建的
    blocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_ip_block_rules",
    )

    class Meta:
        ordering = ["-blocked_at"]

    def __str__(self):
        return f"{self.ip_address} reason={self.reason}"