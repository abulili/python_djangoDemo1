建议优先在本地确认以下步骤无误之后再去服务器部署

构建镜像
docker compose build

启动 MySQL 和 Redis
docker compose up -d db redis
查看状态
docker compose ps

数据库迁移
docker compose run --rm web python manage.py migrate

启动 Web 和 Celery Worker
docker compose up -d web worker

查看日志
docker compose logs -f web
docker compose logs -f worker

验证接口
http://localhost:8000/healthy/
