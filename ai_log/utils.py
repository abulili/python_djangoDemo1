# ai_log/utils.py
from rest_framework.response import Response
from django.core.cache import cache

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

def check_user_ai_rate_limit(user_id, limit=10, window_seconds=60):
    """
    AI请求限流
    user_id: 当前用户 ID
    limit: 时间窗口内最多请求次数
    window_seconds: 时间窗口，单位秒，“统计请求次数的时间范围”

    throttles和base里面也有限流，但是这个是业务自定义限流，适合后续想做更细的限流
    比如不同人不同模型不同限流规则，失败不计入限流

    drf里面带的限流不管成功还是失败都算一次，如果用户正常点一次，但 AI 服务超时了，这次也会占用额度
    但在系统里面也是可以接受的，因为限流主要保护
    接口入口压力
    服务器压力
    数据库压力
    模型调用成本风险
    """
    cache_key = f"ai_rate_limit:{user_id}"

    # 给每个用户生成一个独立计数 key
    current_count = cache.get(cache_key)
    # 从 Redis 里取这个用户当前 60 秒内已经请求了几次
    if current_count is None:
        # 创建key
        cache.set(cache_key, 1, timeout=window_seconds)
        return True, 1
    if current_count >= limit:
        return False, current_count
    
    cache.incr(cache_key)
    
    return True, current_count + 1