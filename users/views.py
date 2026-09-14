from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from .serializers import (
    UserRegisterSerializer,SingleSessionTokenObtainPairSerializer, SingleSessionTokenRefreshSerializer, 
    LoginEventSerializer, ForceLogoutUsersSerializer, BanUsersSerializer, IPBlockRuleSerializer
)
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication, BasicAuthentication 

from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .models import UserProfile, LoginEvent, IPBlockRule

from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser

from django.db import transaction
from django.contrib.auth.models import User

from django.utils import timezone

# Create your views here.
class UserRegisterView(APIView):
    # ✅ 关键：移除 JWT 认证，只保留 Session 认证
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [AllowAny] #允许任何人访问

    def post(self, request, format=None):
        serializer = UserRegisterSerializer(data=request.data)

        if(serializer.is_valid()):
            user = serializer.save()
            return Response({
                'code': 200,
                'message':'注册成功',
                'data':{
                    'id': user.id,
                    'username': user.username,
                    'email': user.email
                }
            }, status=status.HTTP_201_CREATED)
        return Response({
            'code': 400,
            'message': '注册失败',
            'data': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

class SingleSessionTokenObtainPairView(TokenObtainPairView):
    serializer_class = SingleSessionTokenObtainPairSerializer

class SingleSessionTokenRefreshView(TokenRefreshView):
    serializer_class = SingleSessionTokenRefreshSerializer

class LogoutView(APIView):
    # 这个接口必须登录后才能访问。
    permission_classes = [IsAuthenticated]

    def post(self, request, format=None):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.token_version += 1
        profile.save(update_fields=["token_version"])

        return Response({
            "code": 200,
            "message": "退出登录成功",
            "data": None,
        }, status=status.HTTP_200_OK)

class LoginEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LoginEventSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        queryset = LoginEvent.objects.select_related("user").all()

        user_id = self.request.query_params.get("user_id")
        username = self.request.query_params.get("username")
        ip_address = self.request.query_params.get("ip_address")
        success = self.request.query_params.get("success")

        if user_id:
            queryset = queryset.filter(user_id=user_id)

        if username:
            queryset = queryset.filter(user__username__icontains=username)

        if ip_address:
            queryset = queryset.filter(ip_address=ip_address)

        if success in ["true", "false"]:
            queryset = queryset.filter(success=success == "true")

        return queryset

class ForceLogoutUsersView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, format=None):
        serializer = ForceLogoutUsersSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user_ids = serializer.validated_data["user_ids"]

        users = User.objects.filter(id__in=user_ids)
        # users.values_list("id") --->  [(1,), (2,), (3,)]元组 ---> [1, 2, 3]flat=True
        existing_user_ids = list(users.values_list("id", flat=True))

        with transaction.atomic(): # 数据库事务
            # 逐个退出登录，更新 token_version
            for user in users:
                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.token_version += 1
                profile.save(update_fields=["token_version"])

        return Response({
            "code": 200,
            "message": "批量下线成功",
            "data": {
                "requested_count": len(user_ids),
                "updated_count": len(existing_user_ids),
                "updated_user_ids": existing_user_ids,
                "missing_user_ids": [
                    user_id for user_id in user_ids if user_id not in existing_user_ids
                ],
            },
        }, status=status.HTTP_200_OK)

class BanUsersView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, format=None):
        serializer = BanUsersSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_ids = serializer.validated_data["user_ids"]
        reason = serializer.validated_data.get("ban_reason", "")
        users = User.objects.filter(id__in=user_ids)
        existing_user_ids = list(users.values_list("id", flat=True))

        with transaction.atomic():
            for user in users:
                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.is_banned = True
                profile.ban_reason = reason
                profile.banned_at = timezone.now()
                profile.token_version += 1
                profile.save(update_fields=[
                    "is_banned",
                    "ban_reason",
                    "banned_at",
                    "token_version",
                ])

        return Response({
            "code": 200,
            "message": "用户封禁成功",
            "data": {
                "requested_count": len(user_ids),
                "updated_count": len(existing_user_ids),
                "updated_user_ids": existing_user_ids,
                "missing_user_ids": [
                    user_id for user_id in user_ids if user_id not in existing_user_ids
                ],
            },
        }, status=status.HTTP_200_OK)

class UnbanUsersView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, format=None):
        serializer = ForceLogoutUsersSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_ids = serializer.validated_data["user_ids"]
        users = User.objects.filter(id__in=user_ids)
        existing_user_ids = list(users.values_list("id", flat=True))

        with transaction.atomic():
            for user in users:
                profile,_ = UserProfile.objects.get_or_create(user=user)
                profile.is_banned = False
                profile.ban_reason = ""
                profile.banned_at = None
                profile.token_version += 1
                profile.save(update_fields=[
                    "is_banned",
                    "ban_reason",
                    "banned_at",
                    "token_version",
                ])

        return Response({
            "code": 200,
            "message": "用户解封成功",
            "data": {
                "requested_count": len(user_ids),
                "updated_count": len(existing_user_ids),
                "updated_user_ids": existing_user_ids,
                "missing_user_ids": [
                    user_id for user_id in user_ids if user_id not in existing_user_ids
                ],
            },
        }, status=status.HTTP_200_OK)

class IPBlockRuleViewSet(viewsets.ModelViewSet):
    """
    GET /api/users/ip-block-rules/
    POST /api/users/ip-block-rules/
    PATCH /api/users/ip-block-rules/{id}/
    DELETE /api/users/ip-block-rules/{id}/
    """
    permission_classes = [IsAdminUser]
    serializer_class = IPBlockRuleSerializer

    def get_queryset(self):
        # 查询所有 IPBlockRule，并且顺手把 blocked_by 这个管理员用户也一起查出来。因为 blocked_by 是外键
        queryset = IPBlockRule.objects.select_related("blocked_by").all()

        ip_address = self.request.query_params.get("ip_address")
        is_active = self.request.query_params.get("is_active")

        if ip_address:
            queryset = queryset.filter(ip_address=ip_address)

        if is_active in ["true", "false"]:
            queryset = queryset.filter(is_active=is_active == "true")

        return queryset

    # 当前端 POST 创建 IPBlockRule 时，保存前自动把 blocked_by 设置成当前管理员。
    def perform_create(self, serializer):
        serializer.save(blocked_by=self.request.user)

