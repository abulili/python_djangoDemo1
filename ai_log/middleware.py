import time
import logging
from django.utils.timezone import now
import uuid

logger = logging.getLogger(__name__)

# 包在所有接口外面的一层公共处理逻辑。前端从这里进入再到view接口处理
# 改了要重启
"""
所以适合：
    登录校验
    trace_id
    请求日志
    跨域
    异常捕获
    耗时统计
    限流
    响应头处理
"""

class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.time()
        response = self.get_response(request)
        duration = time.time() - start_time

        # 记录耗时超过1秒的慢请求
        if duration > 1:
            logger.warning(f'满请求：{request.method} {request.path} - {duration:.2f}秒')
        # 在响应中添加耗时信息（方便前端/调试）
        response['X-Response-Time'] = f'{duration:.2f}秒'
        return response


class TraceIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        """
        如果前端传了 X-Trace-Id，就沿用前端的, 如果没传，就后端生成一个
        挂到 request.trace_id
        接口处理完后，把 trace_id 放到响应头返回
        """
        start_time = time.time()

        trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex

        request.trace_id = trace_id
        # 把请求继续往后传, 让后面的 middleware 和真正的 view 去处理, 然后等它们处理完，把 response 返回回来
        response = self.get_response(request)
        duration = time.time() - start_time

        response['X-Trace-Id'] = trace_id
        # 耗时统计
        response["X-Response-Time"] = str(round(duration, 3))
        return response