from .base import *
DEBUG = True
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']

DATABASES = {
    'default': {
        # 'ENGINE': 'django.db.backends.sqlite3',
        # 'NAME': BASE_DIR / 'db.sqlite3',
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': os.getenv('DB_PORT', '3306'),
    }
}


CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        # 如果 WSL2 用这个：'LOCATION': 'redis://172.x.x.x:6379/1‘
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# ========== Celery 配置 ==========
# Celery 消息代理（Broker）的地址，用于发送和接收任务消息
# /0 表示使用 Redis 的 0 号数据库（默认数据库）
CELERY_BROKER_URL = 'redis://127.0.0.1:6379/1'
# Celery 任务结果后端（Backend）的地址，用于存储任务执行结果
# 这里同样使用 Redis 的 0 号数据库存储结果
CELERY_RESULT_BACKEND = 'redis://127.0.0.1:6379/1'
# 允许接收的内容类型，这里设置为只接受 JSON 格式的数据
CELERY_ACCEPT_CONTENT = ['json']
# 任务序列化方式，将任务参数序列化的格式，这里使用 JSON
CELERY_TASK_SERIALIZER = 'json'
# 任务结果序列化方式，将任务返回结果序列化的格式，这里使用 JSON
CELERY_RESULT_SERERIALIZER = 'json'
# Celery 使用的时区，设置为上海时区（东八区）
CELERY_TIMEZONE = 'Asia/Shanghai'
