# AI 调用日志与分析服务

一个基于 Django REST Framework 的 AI 调用日志记录、统计与流式交互后端服务。

---

## 核心功能

- **日志记录**：记录每次 AI 调用的用户输入、AI 回复、耗时、是否成功等信息
- **标准 CRUD 接口**：提供完整的增删改查 API，方便前端对接
- **统一响应格式**：所有接口返回统一的 JSON 结构，前端对接省心
- **数据统计**：支持总体/今日的调用次数、成功率、平均耗时统计
- **流式对话**：支持 Server-Sent Events (SSE) 流式输出，实时逐字返回 AI 回复
- **环境变量管理**：敏感信息通过 `.env` 文件管理，不硬编码在代码中
- **统一异常处理**：所有异常统一捕获，返回 JSON 格式错误信息

---

## 技术栈

- **Python**：3.11+
- **Django**：5.2
- **Django REST Framework**：3.15+
- **DeepSeek API**：兼容 OpenAI 协议
- **数据库**：SQLite (开发环境) / MySQL (生产环境)
- **其他**：python-dotenv, PyMySQL, OpenAI SDK

---

## 快速启动

### 1. 克隆项目

```bash
git clone <你的仓库地址>
cd django_test
```

### 2. 创建并激活虚拟环境

```
python -m venv venv

# Windows
venv\Scripts\activate

# Mac / Linux
source venv/bin/activate
```

### 3.安装依赖

```
pip install -r requirements.txt
```

### 4. 配置环境变量

在项目根目录创建 .env 文件：

```
DEEPSEEK_API_KEY=你的DeepSeek API密钥
```

### 5.执行数据库迁移

```
python manage.py migrate
```

### 6.创建超级管理员（可选）

```
python manage.py createsuperuser
```

### 7. 启动服务

```
python manage.py runserver
```

### 接口

调用AI

```
POST /api/logs/
Content-Type: application/json

{
    "prompt": "你好，请介绍一下自己"
}
```

获取统计数据

```
GET /api/logs/stats/
```

流式对话

```
POST /api/logs/stream/
Content-Type: application/json

{
    "prompt": "写一首关于夏天的诗"
}
```

### 项目结构

```
django_test/
├── ai_log/                 # 核心应用
│   ├── models.py           # 数据模型
│   ├── views.py            # 视图与接口
│   ├── serializers.py      # 序列化器
│   ├── utils.py            # 工具函数
│   ├── exceptions.py       # 异常处理
│   └── migrations/         # 数据库迁移文件
├── myweb/                  # 项目配置
│   ├── settings.py         # 配置文件
│   └── urls.py             # 路由配置
├── .env                    # 环境变量
├── manage.py               # Django 管理工具
└── README.md               # 项目文档
```

### 后续计划

1. 增加 JWT 用户认证
2. 对接 MySQL 生产数据库
3. 使用 Redis 缓存统计数据
4. 增加对话上下文功能
5. 部署到云服务器
