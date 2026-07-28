import time
import logging
from django.utils.timezone import now

logger = logging.getLogger(__name__)

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