import logging

from django.http import Http404
from rest_framework.exceptions import APIException, Throttled
from rest_framework.response import Response
from rest_framework.views import exception_handler
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if isinstance(exc, Throttled):
        wait = getattr(exc, "wait", None)
        message = "请求过于频繁，请稍后再试"
        if wait:
            message = f"请求过于频繁，请 {int(wait)} 秒后再试"
        return Response({
            "code": 429,
            "message": message,
            "data": {"wait": wait},
        }, status=429)

    if isinstance(exc, (InvalidToken, TokenError)):
        return Response({
            "code": 401,
            "message": "登录已过期，请重新登录",
            "data": None,
        }, status=401)

    if response is not None:
        detail = response.data.get("detail") if isinstance(response.data, dict) else response.data
        return Response({
            "code": response.status_code,
            "message": detail or "请求失败",
            "data": None,
        }, status=response.status_code)

    if isinstance(exc, APIException):
        status_code = getattr(exc, "status_code", 500)
        return Response({
            "code": status_code,
            "message": getattr(exc, "detail", "请求失败"),
            "data": None,
        }, status=status_code)

    if isinstance(exc, Http404):
        return Response({
            "code": 404,
            "message": "资源不存在",
            "data": None,
        }, status=404)

    logger.exception("Unhandled API exception")
    return Response({
        "code": 500,
        "message": "服务器内部错误，请稍后重试",
        "data": None,
    }, status=500)
