from rest_framework.throttling import UserRateThrottle

class AICallThrottle(UserRateThrottle):
    # 只针对 create 和 stream 接口
    rate = '20/minute' # 每分钟最多2次