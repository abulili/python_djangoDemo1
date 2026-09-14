# 中间件 请求进入 view 之前，先经过的一层处理。
"""
浏览器请求
-> TraceIdMiddleware
-> IPBlockMiddleware
-> CorsMiddleware
-> AuthenticationMiddleware
-> 你的 view
-> 返回响应
"""
from django.http import JsonResponse

from .models import IPBlockRule
from .utils import get_client_ip, record_request_risk_event

from django.conf import settings




class IPBlockMiddleware:
    # 初始化时执行一次
    def __init__(self, get_response):
        # 保存下来，后面请求来了继续往后传。
        self.get_response = get_response

    # 每次请求来了都会执行
    def __call__(self, request):
        client_ip = get_client_ip(request)
    
        if client_ip in getattr(settings, "IP_BLOCK_EXEMPT_IPS", []):
            return self.get_response(request)

        if client_ip and IPBlockRule.objects.filter(
            ip_address=client_ip,
            is_active=True,
        ).exists():
            return JsonResponse({
                "code": 403,
                "message": "当前 IP 已被限制访问",
                "data": None,
            }, status=403)

        return self.get_response(request)

class RequestRiskEventMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        try:
            record_request_risk_event(request, response)
        except Exception:
            pass

        return response

    
