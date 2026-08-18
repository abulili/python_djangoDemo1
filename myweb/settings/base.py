"""
基础路径与环境变量
"""
# 导入 Python 内置的 os 模块，用于操作文件路径和环境变量
import os
# 导入 pathlib 模块的 Path 类，用于处理文件路径（更现代的方式）
from pathlib import Path
# 导入 dotenv 库的 load_dotenv 函数，用于加载 .env 文件中的环境变量
from dotenv import load_dotenv

# 获取项目根目录的绝对路径：当前文件(base.py) → 上一级(settings) → 上一级(myweb) → 上一级(python_djangoDemo1)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
# 加载项目根目录下的 .env 文件，把文件中的环境变量读取到系统中
load_dotenv(BASE_DIR / '.env')

# 项目的安全密钥，用于加密会话、密码、CSRF token等
# 优先从 .env 文件读取，如果没读到就用默认值（生产环境必须改！）
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-default-key-change-me')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', '')

"""
已有的应用
"""
# 配置项目已安装的应用列表，Django 会加载这些应用的功能
INSTALLED_APPS = [
    'django.contrib.admin',      # Django 自带的后台管理系统
    'django.contrib.auth',       # Django 自带的用户认证系统（用户、权限、组）
    'django.contrib.contenttypes',# 内容类型框架，用于跟踪模型与权限的关联
    'django.contrib.sessions',   # 会话管理，用于保存用户登录状态
    'django.contrib.messages',   # 消息提示系统，用于在页面间传递消息
    'django.contrib.staticfiles',# 静态文件管理（CSS、JS、图片等）
    'rest_framework',            # Django REST Framework，用于构建 API
    'rest_framework_simplejwt',  # SimpleJWT 库，用于 JWT 认证
    'ai_log',                    # 我们自己创建的 AI 日志应用
    'users',                     # 我们自己创建的用户应用
    'corsheaders',               # 跨域请求中间件，用于处理跨域请求
]

# 中间件列表，请求会按顺序经过这些中间件处理，响应会按相反顺序返回
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # 放在最前面 处理跨域
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.security.SecurityMiddleware',  # 安全相关，如 HTTPS 重定向、安全头
    'django.contrib.sessions.middleware.SessionMiddleware',  # 会话管理，给 request 添加 session 对象
    'django.middleware.common.CommonMiddleware',  # 通用中间件，处理 URL 规范化、语言设置等
    'django.middleware.csrf.CsrfViewMiddleware',  # CSRF 防护，防止跨站请求伪造
    'django.contrib.auth.middleware.AuthenticationMiddleware',  # 用户认证，给 request 添加 user 对象
    'django.contrib.messages.middleware.MessageMiddleware',  # 消息中间件，处理 messages
    'django.middleware.clickjacking.XFrameOptionsMiddleware',  # 防止点击劫持攻击
]

# 指定项目的根 URL 配置文件，Django 从这里开始匹配 URL
ROOT_URLCONF = 'myweb.urls'

# 模板配置，用于渲染 HTML 页面,配置 Django 模板引擎，这里保持默认设置
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',  # 使用 Django 自带的模板引擎
        'DIRS': [],  # 额外的模板目录（留空表示只在各应用的 templates 目录找）
        'APP_DIRS': True,  # 是否自动在各应用的 templates 目录查找模板
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',  # 把 request 对象传入模板
                'django.contrib.auth.context_processors.auth',  # 把 user 对象和权限传入模板
                'django.contrib.messages.context_processors.messages',  # 把 messages 传入模板
            ],
        },
    },
]

# 指定 WSGI 应用入口，生产环境部署时使用（如 Gunicorn、uWSGI）
# Django 设置中指向项目 WSGI 入口点的路径。简单说，它告诉 Django 和 Web 服务器：
# “当有人访问我的网站时，该通过哪个文件来启动和响应请求。”
"""
场景	是否用到
开发时 python manage.py runserver	❌ 不会用到（开发服务器自己处理）
生产环境用 Gunicorn	✅ 会用到
生产环境用 uWSGI	✅ 会用到
部署到 Apache + mod_wsgi	✅ 会用到
"""
WSGI_APPLICATION = 'myweb.wsgi.application'

# 密码验证规则，用户设置密码时会按这些规则校验强度
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},  # 检查密码是否与用户名太相似
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},  # 检查密码最小长度（默认8位）
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},  # 检查密码是否在常见密码列表中
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},  # 检查密码不能全是数字
]

"""
国际化设置
"""
# 语言设置为中文（简体）
LANGUAGE_CODE = 'zh-hans'
# 时区设置为上海时区
TIME_ZONE = 'Asia/Shanghai'
# 启用国际化支持
USE_I18N = True
# 使用时区（开启后 datetime 会带时区信息）
USE_TZ = True

# 静态文件的 URL 前缀，访问静态文件时用 /static/ 开头
STATIC_URL = 'static/'
# 模型主键字段的默认类型，BigAutoField 是自增的大整数（支持更大范围的 ID）
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# DRF（Django REST Framework）的专属配置
REST_FRAMEWORK = {
    # 默认的认证方式，这里配置为 JWT 认证
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    # 自定义异常处理器，覆盖默认的异常处理，返回统一格式的错误响应
    'EXCEPTION_HANDLER': 'ai_log.exceptions.custom_exception_handler',
    # 默认的限流类，用于限制 API 请求频率
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.UserRateThrottle',
    ],
    # 限流速率配置，'user': '60/minute' 表示每个用户每分钟最多请求 60 次
    'DEFAULT_THROTTLE_RATES': {
        'user': '60/minute',
    },
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
}

"""
日志
"""
# myweb/settings/base.py（在 base.py 末尾加上这段）

# 日志配置字典，定义了 Django 项目的日志记录行为
LOGGING = {
    # 日志配置版本号，固定为 1（目前只有一个版本）
    'version': 1,
    # 是否禁用已存在的日志记录器，设为 False 表示保留默认的日志记录器
    'disable_existing_loggers': False,
    
    # 日志格式化器，定义日志输出的格式
    'formatters': {
        # 详细格式（verbose）：包含更多信息，适合生产环境
        'verbose': {
            # 格式模板：日志级别 时间 模块名 进程ID 线程ID 日志消息
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            # 格式风格：使用大括号 {} 作为占位符
            'style': '{',
        },
        # 简单格式（simple）：只包含关键信息，适合开发调试
        'simple': {
            # 格式模板：日志级别 时间 模块名 日志消息
            'format': '{levelname} {asctime} {module} {message}',
            # 格式风格：使用大括号 {} 作为占位符
            'style': '{',
        },
    },
    
    # 日志处理器，定义日志输出的目标（文件、控制台等）
    'handlers': {
        # 文件处理器（file）：将日志写入文件
        'file': {
            # 日志级别：只记录 INFO 及以上级别的日志（INFO, WARNING, ERROR, CRITICAL）
            'level': 'INFO',
            # 使用 RotatingFileHandler，支持日志文件自动轮转（防止单个文件过大）
            'class': 'logging.handlers.RotatingFileHandler',
            # 日志文件路径：项目根目录下的 logs/django.log
            'filename': os.path.join(BASE_DIR, 'logs', 'django.log'),
            # 单个日志文件最大大小：1024*1024*10 = 10MB
            'maxBytes': 1024 * 1024 * 10,
            # 保留的历史日志文件数量：30个（超过后自动删除最旧的）
            'backupCount': 30,
            # 使用 verbose 格式化器，输出详细格式
            'formatter': 'verbose',
        },
        # 控制台处理器（console）：将日志输出到终端
        'console': {
            # 日志级别：记录 DEBUG 及以上级别的日志（最详细，适合开发）
            'level': 'DEBUG',
            # 使用 StreamHandler，输出到标准输出（控制台）
            'class': 'logging.StreamHandler',
            # 使用 simple 格式化器，输出简单格式
            'formatter': 'simple',
        },
    },
    
    # 根日志记录器，所有未匹配到特定 logger 的日志都会使用这个配置
    'root': {
        # 使用的处理器：同时输出到控制台和文件
        'handlers': ['console', 'file'],
        # 日志级别：INFO 及以上
        'level': 'INFO',
    },
    
    # 特定模块的日志记录器配置，可以为不同模块设置不同的日志行为
    'loggers': {
        # Django 框架本身的日志记录器
        'django': {
            # 使用的处理器：只输出到文件
            'handlers': ['file'],
            # 日志级别：INFO 及以上
            'level': 'INFO',
            # 是否向上传递日志到父级记录器，设为 False 表示不再传递
            'propagate': False,
        },
        # ai_log 应用的日志记录器
        'ai_log': {
            # 使用的处理器：同时输出到文件和控制台
            'handlers': ['file', 'console'],
            # 日志级别：DEBUG 及以上（最详细，方便开发调试）
            'level': 'DEBUG',
            # 是否向上传递日志，设为 False 表示不再传递
            'propagate': False,
        },
    },
}

# 模型列表
AI_MODELS = {
    'deepseek': {
        'name': 'DeepSeek',
        'api_key': os.getenv('DEEPSEEK_API_KEY'),
        'base_url': 'https://api.deepseek.com',
        'default_model': 'deepseek-v4-flash',
    },
    'agnes':{
        'name': 'Agnes',
        'api_key': os.getenv('AGNES_API_KEY'),
        'base_url': 'https://apihub.agnes-ai.com/v1',
        'default_model': 'agnes-2.0-flash',
    }
}
DEFAULT_AI_MODEL = 'deepseek'

# 允许所有源（开发阶段用）
# CORS_ALLOW_ALL_ORIGINS = True

# 或者只允许特定源（更安全）
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://abulili.top",
    "https://api.abulili.top",
    "https://chat.abulili.top",
]

# 允许携带凭证（如 cookies、authorization headers）
CORS_ALLOW_CREDENTIALS = True