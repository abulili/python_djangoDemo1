import os
from celery import Celery

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myweb.settings.dev')

# 创建Celery应用
app = Celery('myweb')

# 从Django settings 加载配置
app.config_from_object('django.conf:settings',namespace='CELERY')

# 自动发现任务（在ai_log/tasks.py写任务）
app.autodiscover_tasks()
