#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

# 这里是管理工具，myweb是主项目，ai_log是创建的App（业务模块），db.splite3是数据库文件
# migration是数据库迁移记录
# venv 专门给这个项目隔离的python虚拟环境

# 管理项目的“遥控器”
# python manage.py runserver   # 启动服务
# python manage.py startapp    # 创建App
# python manage.py migrate     # 数据库迁移


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myweb.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
