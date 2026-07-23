from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from .serializers import UserRegisterSerializer
from rest_framework.authentication import SessionAuthentication, BasicAuthentication 

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