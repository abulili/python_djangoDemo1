# 使用 Python 3.11 官方镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=myweb.settings.prod

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    default-libmysqlclient-dev \
    gcc \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 创建日志目录
RUN mkdir -p /app/logs

# 收集静态文件
# RUN python manage.py collectstatic --noinput

# 暴露端口
EXPOSE 8000

# 启动命令（直接用 Django 开发服务器）
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"] # 开发环境
# 生产模式（新） --workers 3 表示启动 3 个 worker 进程处理请求，可以根据服务器 CPU 核心数调整（一般是 2 * CPU核数 + 1）。
# CMD ["gunicorn", "myweb.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]