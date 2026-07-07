
import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from django.http import Http404

logger = logging.getLogger(__name__)

def custom_exception_handler(exc, context):
    print(">>> 异常处理器被调用了！")
    """
    自定义异常处理：统一返回JSON格式的错误信息
    """
    # 先调用DRF默认的异常处理
    response = exception_handler(exc, context)

    # 如果DRF能处理，就用它的结果
    if response is not None:
        return Response({
            "code": response.status_code,
            "message":response.data.get("detail") or "请求失败",# str(response.data)
            "data": None
        }, status=response.status_code)
    
    # 如果 DRF 处理不了，再判断是不是 Http404
    if isinstance(exc, Http404):
        return Response({
            "code":404,
            "message": "资源不存在",
            "data": None
        },status=404)
    
    # DRF 处理不了的异常，统一返回500
    logger.error(f"未捕获的异常：{exc}")
    return Response({
        "code":500,
        "message":"服务器内部错误，请稍后重试",
        "data": None
    },status=500)