# ai_log/utils.py
from rest_framework.response import Response

def success_response(data=None, message="success", code=200):
    """统一成功响应"""
    return Response({
        "code": code,
        "message": message,
        "data": data
    })

def error_response(message="请求失败", code=400, data=None):
    """统一错误响应"""
    return Response({
        "code": code,
        "message": message,
        "data": data
    }, status=code)