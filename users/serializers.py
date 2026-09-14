from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from django.utils import timezone
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from .models import UserProfile, LoginEvent, IPBlockRule, RequestRiskEvent
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken
from .utils import get_client_ip


class UserRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, validators=[
        validate_password
    ]) # 密码强度验证
    """
    # 1. 密码不能与用户信息太相似（如用户名、邮箱）
    # 2. 密码长度至少 8 位（可配置）
    # 3. 密码不能是常见密码（如 '12345678'、'password'）
    # 4. 密码不能全是数字
    
    # 5. 密码不能全是字母 （需配置）
    """
    password2 = serializers.CharField(write_only=True, required=True, label='确认密码')

    # 内部配置类，定义模型行为和元数据
    class Meta:
        model = User # 指定使用的模型
        fields = ['id','username','email', 'password', 'password2'] # 序列化哪些字段
        extra_kwargs = { # 额外参数配置 Meta带的，为字段添加额外验证
            'email':{'required':True}, # 约等于直接定义字段 email = serializers.EmailField(required=True, max_length=100)
            'username':{'required':True},
        }
    
    def validate(self, attrs):
        # 验证密码是否一致 Python 会自动进行类型转换和比较，类型不同不相等
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({'password2':'密码不一致'})
        return attrs
    
    def create(self, validated_data):
        # 创建用户
        # 移除password2,不保存到数据库
        # validated_data 是一个字典（dict 对象），支持 pop() 方法。 pop 移除指定键，并返回其值
        validated_data.pop('password2')

        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
        )
        return user

class SingleSessionTokenObtainPairSerializer(TokenObtainPairSerializer):
    # 生成 refresh token 时，往 token 里额外塞 token_version。
    """
    SimpleJWT的逻辑：
    校验 username/password
    生成 refresh/access token
    返回给前端

    1. 先调用 super().validate(attrs)，让 SimpleJWT 校验账号密码。
    2. 找到当前用户 self.user。
    3. 拿到或创建 UserProfile。
    4. token_version + 1，表示这是一次新登录。
    5. 记录 IP、User-Agent、登录时间。
    6. 重新生成带 token_version 的 refresh/access。
    7. 返回给前端。
    """
    @classmethod
    def get_token(cls, user):
        # cls 是 SingleSessionTokenObtainPairSerializer
        # SimpleJWT 原本的 get_token 就是类方法，所以我们重写它时也要写 @classmethod
        token = super().get_token(user)
        profile,_ = UserProfile.objects.get_or_create(user=user)
        token['token_version'] = profile.token_version
        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        request = self.context.get("request")
        profile, _ = UserProfile.objects.get_or_create(user=self.user)

        if profile.is_banned:
            raise AuthenticationFailed("账号已被封禁，请联系管理员")

        profile.token_version += 1

        ip_address = None
        user_agent = ""

        if request:
            # 用户浏览器 -> Nginx -> Django Nginx 会把用户真实 IP 放到HTTP_X_FORWARDED_FOR
            # forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            # if forwarded_for:
            #     profile.last_login_ip = forwarded_for.split(',')[0].strip()
            # else:
            #     # REMOTE_ADDR 可能是 Nginx 的 IP，不是用户真实 IP
            #     profile.last_login_ip = request.META.get('REMOTE_ADDR')
            ip_address = get_client_ip(request)
            user_agent = request.META.get("HTTP_USER_AGENT", "")

            profile.last_login_ip = ip_address
            profile.last_login_user_agent = user_agent

        profile.last_login_at = timezone.now()


        profile.save(
            update_fields=['token_version', 'last_login_ip', 'last_login_user_agent', 'last_login_at']
        )
        LoginEvent.objects.create(
            user=self.user,
            ip_address=ip_address,
            user_agent=user_agent,
            token_version=profile.token_version,
            success=True,
            reason="login_success",
        )

        refresh = self.get_token(self.user)
        data["refresh"] = str(refresh)
        data["access"] = str(refresh.access_token)
        return data

class SingleSessionTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        refresh = RefreshToken(attrs['refresh'])
        
        user_id = refresh.get("user_id")
        token_version = refresh.get("token_version")

        if token_version is None:
            raise AuthenticationFailed("登录状态已失效，请重新登录")

        try:
            # 新用户注册时已经创建了UserProfile
            profile = UserProfile.objects.get(user_id=user_id)
        except UserProfile.DoesNotExist:
            # 兜底：refresh token 里说有这个用户，但数据库里找不到对应的安全状态记录。
            # 历史脏数据
            # UserProfile 被误删
            # token 是旧版本系统签发的
            # token 是伪造/异常来源
            raise AuthenticationFailed("登录状态已失效，请重新登录")

        if profile.is_banned:
            raise AuthenticationFailed("账号已被封禁，请联系管理员")

        if token_version != profile.token_version: # 版本号的累加
            raise AuthenticationFailed("账号已在其他设备登录，请重新登录")

        return super().validate(attrs)

class LoginEventSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = LoginEvent
        fields = [
            "id",
            "user",
            "username",
            "ip_address",
            "user_agent",
            "token_version",
            "success",
            "reason",
            "created_at",
        ]
        read_only_fields = fields

class ForceLogoutUsersSerializer(serializers.Serializer):
    # 校验请求体
    """
    user_ids 必须是一个列表
    列表里的每一项必须是整数
    每个整数最小是 1
    这个列表不能为空
    """
    user_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )

class BanUsersSerializer(serializers.Serializer):
    user_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )
    ban_reason = serializers.CharField(max_length=255, allow_null=False, allow_blank=True,default="")
        
class IPBlockRuleSerializer(serializers.ModelSerializer):
    blocked_by_username = serializers.CharField(source='blocked_by.username', read_only=True)

    class Meta:
        model = IPBlockRule
        fields = [
            "id",
            "ip_address",
            "reason",
            "is_active",
            "blocked_at",
            "blocked_by",
            "blocked_by_username",
        ]
        read_only_fields = [
            "id",
            "blocked_at",
            "blocked_by",
            "blocked_by_username",
        ]

class IPBlockRuleSerializer(serializers.ModelSerializer):
    blocked_by_username = serializers.CharField(
        source='blocked_by.username',
        read_only=True,
    )

    class Meta:
        model = IPBlockRule
        fields = [
            "id",
            "ip_address",
            "reason",
            "is_active",
            "blocked_at",
            "blocked_by",
            "blocked_by_username",
        ]
        read_only_fields = [
            "id",
            "blocked_at",
            "blocked_by",
            "blocked_by_username",
        ]

class RequestRiskEventSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = RequestRiskEvent
        fields = [
            "id",
            "user",
            "username",
            "ip_address",
            "path",
            "method",
            "status_code",
            "risk_type",
            "count",
            "window_seconds",
            "detail",
            "created_at",
        ]
        read_only_fields = fields

    

