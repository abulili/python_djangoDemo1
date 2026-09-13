from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from .serializers import UserRegisterSerializer
from rest_framework.authentication import SessionAuthentication, BasicAuthentication 

from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .serializers import SingleSessionTokenObtainPairSerializer, SingleSessionTokenRefreshSerializer
from django.utils import timezone
from .models import UserProfile

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

