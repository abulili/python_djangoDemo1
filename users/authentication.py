from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed

from .models import UserProfile

class SingleSessionJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        
        token_version = validated_token.get('token_version')
        # 因为get_or_create会返回两个东西(profileUserProfile 对象, created这次是不是新建的)
        # 不关心第二个值，就用 _ 接住
        profile, _ = UserProfile.objects.get_or_create(user=user)

        if profile.is_banned:
            raise AuthenticationFailed("账号已被封禁，请联系管理员")

        if token_version is None:
            raise AuthenticationFailed("登录状态已失效，请重新登录")
        
        if token_version != profile.token_version:
            raise AuthenticationFailed("账号已在其他设备登录，请重新登录")

        return user

    