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

---

## AI 日志接口区分说明

本项目后端通过 `DefaultRouter` 注册 `AICallLogViewSet`，所以日志相关接口统一挂在：

```text
/api/logs/
```

前端实际会把 `.env` 中的 `VITE_API_URL=https://api.abulili.top/api` 和下面路径拼起来，例如 `/logs/stream2/` 对应完整地址：

```text
https://api.abulili.top/api/logs/stream2/
```

### 1. 标准日志 CRUD

#### `GET /api/logs/`

用途：获取 AI 调用日志列表。

特点：

- 由 `ModelViewSet` 自动提供。
- 实际数据范围受 `get_queryset()` 控制。
- 普通用户只能看到自己的日志。
- 超级管理员可以看到全部日志。

适合前端页面：日志列表页 `LogList.jsx`。

#### `POST /api/logs/`

用途：创建一次 AI 调用任务。

当前实现：

- 对应 `AICallLogViewSet.create()`。
- 读取 `prompt`。
- 调用 `call_ai_task.delay(prompt, request.user.id)`。
- 返回 `task_id`，需要前端继续轮询任务结果。

注意：

- 这个接口不是专门用来创建 `conversation_id` 的。
- 当前版本没有处理 `conversation_id`。
- 当前版本会触发一次 Celery AI 调用任务。
- 如果流式模式下先调它、再调 `/stream2/`，可能导致一次提问触发两次 AI 调用。

推荐用途：老版本普通异步 AI 调用，不推荐作为流式对话的前置请求。

### 2. 异步 AI 调用接口

这类接口不是直接返回 AI 最终回答，而是先提交 Celery 任务，再返回 `task_id`。

前端后续需要调用：

```text
GET /api/logs/task/{task_id}/
```

来查询任务状态和结果。

#### `POST /api/logs/call_company_ai3/`

call_company_ai4 基本覆盖了 call_company_ai3 的能力，而且比它多。
对应后端方法：`create2()`。

用途：支持模型选择的异步 AI 调用。

请求示例：

```json
{
  "prompt": "帮我解释一下 SSE",
  "model": "deepseek"
}
```

特点：

- 调用 `call_ai_task2.delay(...)`。
- 支持 `model` 参数。
- 返回 `task_id`。
- 不支持 `conversation_id`。
- 不支持 Prompt 模板。
- 不走完整上下文逻辑。

适合用途：普通非流式、可选模型的异步调用。

#### `POST /api/logs/call_company_ai4/`

对应后端方法：`create4()`。

用途：增强版异步 AI 调用。

请求示例：

```json
{
  "prompt": "帮我优化这段简历描述",
  "model": "deepseek",
  "conversation_id": "可选，不传则后端生成",
  "template_name": "resume_polish",
  "template_vars": {
    "role": "前端工程师"
  }
}
```

特点：

- 如果没有传 `conversation_id`，后端会用 `uuid.uuid4()` 自动生成。
- 调用 `call_ai_task4.delay(...)`。
- 内部复用 `call_ai_service(...)`。
- 支持模型选择。
- 支持 Prompt 模板。
- 支持 `conversation_id` 会话追踪。
- 支持 Redis 会话历史。
- 支持记录 token、cost、duration、success。
- 返回 `task_id` 和 `conversation_id`。

适合用途：非流式、带上下文、带模板、需要完整日志记录的 AI 调用。

### 3. Celery 任务查询接口

#### `GET /api/logs/task/{task_id}/`

对应后端方法：`get_task_result()`。

用途：查询 Celery 异步任务状态。

可能返回状态：

- `pending`：任务排队中。
- `failed`：任务失败。
- `success`：任务完成。
- `unknown`：未知状态。

前端用法：

- 提交 `/logs/`、`/call_company_ai3/` 或 `/call_company_ai4/` 后拿到 `task_id`。
- 用 `setInterval` 轮询 `/task/{task_id}/`。
- 成功后展示返回的 AI 结果。

### 4. SSE 流式接口

这类接口会直接返回 `StreamingHttpResponse`，前端用 `fetch + response.body.getReader() + TextDecoder` 逐块读取。

它们和 Celery 异步接口不同：

- 不返回 `task_id`。
- 不需要轮询。
- 后端一边调用 AI，一边把内容通过 SSE 推给前端。

#### `POST /api/logs/stream/`

对应后端方法：`stream_chat()`。

用途：基础流式 AI 对话。

请求示例：

```json
{
  "prompt": "写一段自我介绍"
}
```

特点：

- 调用 `stream_ai_response(prompt)`。
- 使用 `StreamingHttpResponse` 直接流式返回。
- 返回格式类似：`data:{"content":"..."}`。
- 不支持 `conversation_id`。
- 不支持上下文历史。
- 不写入完整 `AICallLog` 日志。
- 当前代码里尝试缓存 `StreamingHttpResponse`，这类响应本身不适合直接缓存，后续建议不用这个版本作为主接口。

适合用途：早期基础 SSE Demo。

#### `POST /api/logs/stream2/`

对应后端方法：`stream_chat2()`。

用途：带缓存结果复用的流式 AI 对话。

请求示例：

```json
{
  "prompt": "帮我解释 Django ViewSet"
}
```

当前特点：

- 调用 `stream_ai_response_with_cache(prompt, cache_key)`。
- 如果缓存命中，会用 `fake_stream()` 把缓存结果按字符重新流式返回。
- 如果缓存未命中，会实时调用 AI 并流式返回。
- 流结束后会把完整回答写入 cache。
- 当前 cache key 主要基于 `prompt`。

当前不支持的点：

- 当前没有读取 `conversation_id = request.data.get('conversation_id')`。
- 当前没有自动生成 `conversation_id`。
- 当前没有读取 Redis 会话历史。
- 当前没有保存当前轮对话到 Redis 历史。
- 当前没有把完整回答写入 `AICallLog`。

所以，当前版本的 `/stream2/` **不需要 `conversation_id`**，因为后端没有使用它。

但如果后续要做“流式输出 + 上下文续聊”，就应该让 `stream_chat2()` 支持 `conversation_id`：

1. 接收前端传来的 `conversation_id`。
2. 如果没传，后端自动生成一个新的 `conversation_id`。
3. SSE 第一条先返回 `conversation_id` 给前端。
4. 根据 `conversation_id` 从 Redis 读取历史 messages。
5. 把当前 prompt 加入 messages。
6. 流式调用 AI。
7. 流结束后保存 user prompt 和 assistant response 到 Redis 历史。
8. 写入 `AICallLog`，记录 token、cost、duration、success、conversation_id。
9. cache key 应该包含 user、model、conversation_id、prompt，避免不同用户或不同会话串缓存。

推荐用途：当前作为主要流式输出接口；后续应升级为“支持上下文的流式接口”。

### 5. 会话历史接口

#### `GET /api/logs/conversation/{conversation_id}/`

对应后端方法：`get_conversation()`。

用途：根据 `conversation_id` 获取 Redis 中保存的会话历史。

特点：

- 调用 `get_coversation_history(conversation_id)`。
- 返回指定会话的 messages 列表。
- 当前依赖 `call_ai_service(...)` 保存历史。
- 因此，主要和 `/call_company_ai4/` 这条增强异步链路配合。
- 当前 `/stream2/` 还没有接入这套历史保存逻辑。

后续建议：

- 增加会话列表接口，按 `conversation_id` 分组返回最近会话。
- 让 `stream2` 也保存历史，这样流式对话也能被这个接口查到。

### 6. 统计接口

#### `GET /api/logs/stats/`

对应后端方法：`get_stats()`。

用途：获取 AI 调用统计。

当前返回：

- `total`：总调用次数。
- `success_count`：成功次数。
- `fail_count`：失败次数。
- `success_rate`：成功率。
- `avg_duration`：平均耗时。

特点：

- 代码上标了 `permission_classes=[]`，但方法内部仍然检查 `request.user.is_authenticated`。
- 普通用户统计自己的日志。
- 超级管理员统计全部日志。

后续建议增强：

- 今日调用量。
- 总 token。
- 总 cost。
- 按模型分布。
- 近 7 天趋势。
- 平均 token / 平均费用。

### 7. 批量更新接口

#### `PUT /api/logs/batch-update/`

对应后端方法：`batch_update()`。

用途：批量更新日志字段。

请求示例：

```json
{
  "ids": [1, 2, 3],
  "update_data": {
    "success": false
  }
}
```

特点：

- 只更新当前用户自己的日志。
- 使用 `id__in` 做批量筛选。
- 适合后台批量标记或修正数据。

### 8. 推荐前端调用策略

#### 普通非流式对话

推荐用：

```text
POST /api/logs/call_company_ai4/
GET  /api/logs/task/{task_id}/
```

原因：

- 支持模型。
- 支持 Prompt 模板。
- 支持 `conversation_id`。
- 支持 token、cost、duration、success 日志字段。
- 支持上下文历史。

#### 流式对话

当前用：

```text
POST /api/logs/stream2/
```

但要注意：

- 当前它只是流式输出 + 缓存。
- 当前没有真正支持 `conversation_id` 上下文。

后续推荐升级为：

```text
POST /api/logs/stream2/
```

并让它内部支持：

- 自动生成或接收 `conversation_id`。
- SSE 返回 `conversation_id`。
- 读取和保存 Redis 会话历史。
- 写入 `AICallLog`。

#### 不推荐的流式写法

不推荐在一次流式提问里这样做：

```text
先 POST /api/logs/
再 POST /api/logs/stream2/
```

原因：

- `/api/logs/` 会触发 Celery AI 任务。
- `/api/logs/stream2/` 又会触发一次流式 AI 调用。
- 这样可能导致用户问一次，后端实际调用两次 AI。

如果只是为了拿 `conversation_id`，应该让 `/stream2/` 自己生成并通过 SSE 返回，而不是额外调用 `/logs/`。

### 9. 面试讲法

可以这样总结：

> 这个项目里 AI 调用接口分成两类：一类是 Celery 异步接口，提交后返回 task_id，前端轮询任务结果；另一类是 SSE 流式接口，后端用 StreamingHttpResponse 直接把模型输出逐段推给前端。当前 `/call_company_ai4/` 是功能最完整的异步接口，支持 conversation_id、Prompt 模板、上下文、token 和费用记录；`/stream2/` 是当前主要流式接口，但还需要继续升级，把 conversation_id、会话历史和日志记录接进去，避免流式模式下为了拿会话 ID 额外调用 `/logs/` 造成重复 AI 调用。

---

## AI 调用相关接口速查

这一节只区分“会触发或服务于 AI 调用”的接口，不包含普通日志 CRUD、统计、批量更新等后台管理接口。

### 总览

| 接口                                            | 类型         | 是否直接返回 AI 内容 | 是否流式 | 是否返回 task_id | 当前是否支持 conversation_id | 主要用途                             |
| ----------------------------------------------- | ------------ | -------------------- | -------- | ---------------- | ---------------------------- | ------------------------------------ |
| `POST /api/logs/`                               | Celery 异步  | 否                   | 否       | 是               | 否                           | 老版本异步 AI 调用                   |
| `POST /api/logs/call_company_ai3/`              | Celery 异步  | 否                   | 否       | 是               | 否                           | 支持模型选择的异步 AI 调用           |
| `POST /api/logs/call_company_ai4/`              | Celery 异步  | 否                   | 否       | 是               | 是，不传会自动生成           | 增强版异步 AI 调用，支持上下文和模板 |
| `GET /api/logs/task/{task_id}/`                 | 任务查询     | 查询完成后返回       | 否       | 不生成，只查询   | 跟随任务结果                 | 查询 Celery AI 调用结果              |
| `POST /api/logs/stream/`                        | SSE 流式     | 是                   | 是       | 否               | 否                           | 基础流式 AI Demo                     |
| `POST /api/logs/stream2/`                       | SSE 流式     | 是                   | 是       | 否               | 当前否                       | 当前主要流式输出接口，带缓存复用     |
| `GET /api/logs/conversation/{conversation_id}/` | 会话历史查询 | 否                   | 否       | 否               | 是                           | 查询某个 conversation_id 的历史消息  |

### 1. `POST /api/logs/`

对应后端：`AICallLogViewSet.create()`。

它会触发 AI 调用吗？会。

但它不是直接调用并返回结果，而是：

```text
前端提交 prompt -> 后端创建 Celery 任务 -> 返回 task_id -> 前端再轮询 task 接口
```

当前特点：

- 调用 `call_ai_task.delay(prompt, request.user.id)`。
- 返回 `task_id`。
- 不直接返回 AI 内容。
- 不流式。
- 当前不处理 `conversation_id`。
- 当前不支持 Prompt 模板。

结论：这是老版本异步 AI 调用入口，不适合在流式对话前“顺便拿 conversation_id”。

### 2. `POST /api/logs/call_company_ai3/`

对应后端：`create2()`。

它会触发 AI 调用吗？会。

链路：

```text
前端提交 prompt + model -> 后端创建 Celery 任务 -> 返回 task_id -> 前端轮询 task 接口
```

当前特点：

- 调用 `call_ai_task2.delay(...)`。
- 支持 `model` 参数。
- 返回 `task_id`。
- 不直接返回 AI 内容。
- 不流式。
- 不支持 `conversation_id`。
- 不支持 Prompt 模板。

结论：这是“支持模型选择”的异步 AI 调用，但还不是完整上下文版本。

### 3. `POST /api/logs/call_company_ai4/`

对应后端：`create4()`。

它会触发 AI 调用吗？会。

链路：

```text
前端提交 prompt / model / conversation_id / template -> 后端补齐 conversation_id -> 创建 Celery 任务 -> 返回 task_id + conversation_id -> 前端轮询 task 接口
```

当前特点：

- 调用 `call_ai_task4.delay(...)`。
- 支持 `model`。
- 支持 `conversation_id`。
- 如果不传 `conversation_id`，后端会自动 `uuid.uuid4()` 生成。
- 支持 `template_name` 和 `template_vars`。
- 内部复用 `call_ai_service(...)`。
- `call_ai_service(...)` 会根据 `conversation_id` 读取和保存 Redis 历史。
- 会记录 token、cost、duration、success、model_name、conversation_id。
- 不流式。
- 返回的是 `task_id`，不是最终 AI 内容。

结论：这是目前“非流式 AI 调用”里最完整、最适合保留和扩展的接口。

### 4. `GET /api/logs/task/{task_id}/`

对应后端：`get_task_result()`。

它会触发 AI 调用吗？不会。

它只是查询 Celery 任务结果。

用途：

- 配合 `/logs/`。
- 配合 `/call_company_ai3/`。
- 配合 `/call_company_ai4/`。

前端流程：

```text
先拿 task_id -> 每隔 1 秒查一次 task 接口 -> status 为 success 后展示 result
```

结论：这是异步 AI 调用链路的“结果查询接口”。

### 5. `POST /api/logs/stream/`

对应后端：`stream_chat()`。

它会触发 AI 调用吗？会。

它是流式吗？是。

链路：

```text
前端提交 prompt -> 后端 StreamingHttpResponse -> 一边调用 AI 一边 yield data -> 前端逐块读取
```

当前特点：

- 调用 `stream_ai_response(prompt)`。
- 直接返回 SSE 数据。
- 不返回 `task_id`。
- 不需要轮询。
- 不支持 `conversation_id`。
- 不支持上下文。
- 不支持 Prompt 模板。
- 当前不是最推荐主用接口。

结论：这是基础 SSE Demo 接口。

### 6. `POST /api/logs/stream2/`

对应后端：`stream_chat2()`。

它会触发 AI 调用吗？会，除非缓存命中。

它是流式吗？是。

链路：

```text
前端提交 prompt -> 后端检查缓存 -> 命中则 fake_stream 返回缓存 -> 未命中则流式调用 AI -> 流结束后缓存完整回答
```

当前特点：

- 调用 `stream_ai_response_with_cache(prompt, cache_key)`。
- 直接返回 SSE 数据。
- 不返回 `task_id`。
- 不需要轮询。
- 支持缓存复用。
- 当前没有读取 `conversation_id`。
- 当前没有自动生成 `conversation_id`。
- 当前没有读取/保存 Redis 会话历史。
- 当前没有写入完整 `AICallLog`。

所以回答你的问题：

> 当前版本的 `stream_chat2()` 不需要 `conversation_id`，因为它没有使用这个字段。

但如果你后续要做“流式输出 + 上下文续聊”，`stream_chat2()` 就应该升级为需要或自动生成 `conversation_id`。

推荐升级方向：

```text
如果前端传了 conversation_id -> 继续这个会话
如果前端没传 conversation_id -> 后端生成新的 conversation_id
SSE 第一条返回 conversation_id
读取 Redis 历史 messages
拼入当前 prompt
流式调用 AI
流结束后保存本轮 user/assistant 到 Redis
写入 AICallLog
```

结论：这是当前主要流式接口，但还没有接入上下文。后续最值得改的就是它。

### 7. `GET /api/logs/conversation/{conversation_id}/`

对应后端：`get_conversation()`。

它会触发 AI 调用吗？不会。

它只查询会话历史。

当前特点：

- 从 Redis 读取 `conversation_id` 对应的历史 messages。
- 主要服务于已经使用 `call_ai_service(...)` 保存过历史的接口。
- 目前最匹配的是 `/call_company_ai4/`。
- 因为 `/stream2/` 当前还没保存会话历史，所以流式对话暂时不一定能通过这个接口查到完整历史。

结论：这是 AI 上下文链路的辅助查询接口，不直接调用 AI。

### 最重要的区分

#### 异步 AI 调用

这些接口会返回 `task_id`：

```text
POST /api/logs/
POST /api/logs/call_company_ai3/
POST /api/logs/call_company_ai4/
```

它们的共同点：

- 不直接返回最终 AI 内容。
- 不流式。
- 需要前端轮询 `/api/logs/task/{task_id}/`。

其中最完整的是：

```text
POST /api/logs/call_company_ai4/
```

#### 流式 AI 调用

这些接口直接返回 SSE：

```text
POST /api/logs/stream/
POST /api/logs/stream2/
```

它们的共同点：

- 直接返回 AI 内容片段。
- 不返回 `task_id`。
- 不需要轮询。
- 前端用 `fetch + getReader()` 读取。

其中当前更推荐继续改造的是：

```text
POST /api/logs/stream2/
```

### 当前项目里的关键结论

1. 只有 `/call_company_ai4/` 当前会自动生成 `conversation_id`。
2. `/stream2/` 当前不会自动生成 `conversation_id`，也没有使用上下文。
3. `stream_chat` 和 `stream_chat2` 是当前直接返回 AI 内容的流式接口。
4. `/logs/`、`/call_company_ai3/`、`/call_company_ai4/` 是异步任务接口，需要轮询 `/task/{task_id}/`。
5. 后续要做流式上下文，应该优先改 `stream_chat2()`，而不是在前端先调 `/logs/` 再调 `/stream2/`。

### 面试一句话

> 我把 AI 调用接口分成两类：异步任务型和 SSE 流式型。异步任务型会返回 task_id，前端轮询任务结果，适合耗时任务和完整日志记录；SSE 流式型直接用 StreamingHttpResponse 推送模型输出，适合对话体验。当前 `/call_company_ai4/` 是最完整的异步上下文接口，`/stream2/` 是主要流式接口，后续需要把 conversation_id、Redis 历史和日志记录接进去，实现流式上下文对话。
