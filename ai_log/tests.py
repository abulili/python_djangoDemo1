from django.test import TestCase

# Create your tests here. 写自动化测试 自动模拟请求、检查结果
# python manage.py test ai_log

from django.contrib.auth.models import User
from rest_framework.test import APIClient

from .models import (
    AICallLog,
    Conversation,
    ConversationMessage,
    KnowledgeChunk,
    KnowledgeDocument,
    RagTraceLog,
)
from .views import split_text_to_chunks, simple_keyword_score
from .services import calculate_cost

from unittest.mock import patch

class RegServiceTests(TestCase):
    def test_aplit_text_to_chunks_with_overlap(self):
        # 测文档切片
        text = "a" * 1200

        chunks = split_text_to_chunks(text, chunk_size=500, overlap=100)

        """
        Django TestCase 里的断言。
        assertEqual(a, b) 意思是: 我期望 a 等于 b。如果不等，测试失败。
        """
        self.assertEqual(len(chunks), 3)
        self.assertEqual(len(chunks[0]), 500)
        self.assertEqual(len(chunks[1]), 500)
        self.assertEqual(len(chunks[2]), 400)

    def test_simple_keyword_score(self):
        # 测关键词打分
        query = "stream3 上下文 会话"
        text = "stram3 是带 conversation_id 的上下文流式接口，用来实现多轮会话"

        score = simple_keyword_score(query, text)

        # 期望score > 0，scroe <= 0，测试失败
        """
        assertEqual：检查两个值是否相等
        assertGreater：检查前一个值是否大于后一个值
        """
        self.assertGreater(score, 0)

    def test_calculate_cost_for_agnes(self):
        # 测agnes费用计算
        cost = calculate_cost(
            model_key="agnes",
            prompt_tokens=1000,
            completion_tokens=1000,
        )
        self.assertEqual(cost, 0.00)

class KnowledgeDocumentApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="123456")
        self.other_user = User.objects.create_user(username="testuser2", password="123456Ab")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_create_document_auto_create_chunks(self):
        """
        准备数据--执行动作--断言结果

        模拟创建知识库文档
        判断接口是否创建成功
        判断文档表是否增加一条
        判断切片是否自动生成了数据

        带test_ 可以自动执行，所以test_要验证的业务行为、
        setup会站在每个测试方法执行前自动运行一次

        这种测试会创建一个临时测试数据库，测试结束后销毁，不会污染真实开发数据库
        """
        response = self.client.post('/api/knowledge-documents/', {
            "title": "AI日志项目说明",
            "content": "stream3 是带 conversation_id 的上下文流式接口。" * 30,
        },format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(KnowledgeDocument.objects.count(), 1)
        # KnowledgeChunk表里的数据梳理
        # assertGreater(实际值, 期望下限)
        self.assertGreater(KnowledgeChunk.objects.count(), 0)

    def test_user_can_only_see_own_documents(self):
        # 测试：用户只能看到自己的文档 --用户数据隔离
        KnowledgeDocument.objects.create(
            user=self.user,
            title="自己的文档",
            content="stream3 上下文会话说明",
        )
        KnowledgeDocument.objects.create(
            user=self.other_user,
            title="别人的文档",
            content="其他用户的知识库",
        )

        response = self.client.get('/api/knowledge-documents/')
    
        self.assertEqual(response.status_code, 200)
        titles = [item["title"] for item in response.data['results']]

        self.assertIn('自己的文档', titles)
        # 我断言“别人的文档”不在 titles 这个列表里。
        self.assertNotIn('别人的文档', titles)

    def test_search_only_current_user_chunks(self):
        # 测用户只能检索到自己的chunk
        own_doc = KnowledgeDocument.objects.create(
            user=self.user,
            title="自己的文档",
            content="stream3 上下文会话说明"
        )
        KnowledgeChunk.objects.create(
            document=own_doc,
            content="stream3 使用 conversation_id 实现上下文会话",
            chunk_index=0
        )

        other_doc = KnowledgeDocument.objects.create(
            user=self.other_user,
            title="别人的文档",
            content="stream3 其它资料"
        )
        KnowledgeChunk.objects.create(
            document=other_doc,
            content="stream3 这是其他用户的资料",
            chunk_index=0
        )

        response = self.client.post('/api/knowledge-documents/search/', {
            "query": 'stream3',
            "top_k": 10,
        }, format="json")

        self.assertEqual(response.status_code, 200)

        chunks = response.data["data"]["scored_chunks"]
        document_titles = [item['document_title'] for item in chunks]

        self.assertIn('自己的文档', document_titles)
        self.assertNotIn('别人的文档', document_titles)

    @patch("ai_log.views.call_ai_service") # 把view.py里用到的call_ai_service临时替换成假的函数
    # 如果还有其它的接口，加新的patch
    def test_ask_uses_rag_chunks_and_returns_refrences(self, mock_call_ai_service):
        # mock外部AI调用，实际不调用，因为要花钱
        doc = KnowledgeDocument.objects.create(
            user=self.user,
            title="AI日志项目说明",
            content="stream3 上下文会话说明"
        )
        KnowledgeChunk.objects.create(
            document=doc,
            content="stream3 使用 conversation_id、Redis 和 ConversationMessage 实现上下文会话。",
            chunk_index=0
        )

        # 当 ask 接口调用 call_ai_service 时，不要真的调 AI，直接返回我指定的结果。
        mock_call_ai_service.return_value = (
            {
                "reply": "stream3 通过 conversation_id 读取历史上下文，并在流式结束后保存会话消息。"
            },
            True
        )

        # 这里不会真的取请求，因为有@patch
        # 因为ask里面会调用call_ai_service
        response = self.client.post("/api/knowledge-documents/ask/", {
            "query": "stream3 是怎么实现上下文会话的？",
            "top_k": 3,
            "model": "deepseek",
        }, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["answer"], "stream3 通过 conversation_id 读取历史上下文，并在流式结束后保存会话消息。")
        self.assertEqual(len(response.data["data"]["references"]), 1)
        self.assertEqual(response.data["data"]["references"][0]["document_title"], "AI日志项目说明")

        # 断言 call_ai_service 这个函数在本次测试中刚好被调用了一次。
        # 如果要调用两次不是twice，是self.assertEqual(mock_call_ai_service.call_count, 2)
        mock_call_ai_service.assert_called_once()

        # prompt拼接
        # 拿到 fake call_ai_service 被调用时传进去的参数
        args, kwargs = mock_call_ai_service.call_args

        self.assertIn("stream3", kwargs["prompt"])
        self.assertIn("conversation_id", kwargs["prompt"])
        self.assertIn("知识库资料", kwargs["prompt"])
        self.assertEqual(kwargs["model_key"], "deepseek")
        self.assertEqual(kwargs["user"], self.user)
       
    def test_ask_requires_query(self):
        """
        模拟前端传了空问题
        期望后端返回 400
        证明接口有参数校验
        """
        response = self.client.post('/api/knowledge-documents/ask/', {
            "query": "",
            "top_k": 3,
            "model": "deepseek",
        }, format="json")

        self.assertEqual(response.status_code, 400)

    @patch("ai_log.views.call_ai_service")
    def test_ask_without_matched_chunks_does_not_call_ai(self, mock_call_ai_service):
        """
        没有检索到 chunk
        -> 不应该调用大模型
        -> 不浪费 token 和费用
        """
        response = self.client.post('/api/knowledge-documents/ask/', {
             "query": "完全不存在的问题",
            "top_k": 3,
            "model": "deepseek",
        }, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["answer"], "知识库中没有检索到相关内容。")
        self.assertEqual(response.data["data"]["references"], [])

        # 断言这个假的 call_ai_service 一次都没有被调用
        # mock_call_ai_service代表的就是在patch中使用的call_ai_service
        mock_call_ai_service.assert_not_called()

    @patch("ai_log.views.call_ai_service")
    def test_ask_returns_error_when_ai_service_failed(self, mock_call_ai_service):

        doc = KnowledgeDocument.objects.create(
            user=self.user,
            title="自己的文档",
            content="stream3 使用 conversation_id 实现上下文会话"
        )

        KnowledgeChunk.objects.create(
            document=doc,
            content="stream3 使用 conversation_id 实现上下文会话",
            chunk_index=0
        )

        mock_call_ai_service.return_value = ({
            "reply": "AI 调用失败"
        }, False)

        response = self.client.post("/api/knowledge-documents/ask/", {
            "query": "stream3 上下文",
            "top_k": 3,
            "model": "deepseek",
        }, format="json")

        self.assertEqual(response.status_code, 500)

    @patch("ai_log.views.call_ai_service")
    def test_ask_saves_conversation_history(self, mock_call_ai_service):
        conversation_id = "test-rag-conversation-001"

        doc = KnowledgeDocument.objects.create(
            user=self.user,
            title="AI日志项目说明",
            content="stream3 使用 conversation_id 实现上下文会话"
        )

        KnowledgeChunk.objects.create(
            document=doc,
            content="stream3 使用 conversation_id 实现上下文会话",
            chunk_index=0
        )

        mock_call_ai_service.return_value = ({
            "reply": "stream3 通过 conversation_id 关联上下文。",
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
            "cost": 0.001,
            "duration": 1.2,
        }, True)

        response = self.client.post("/api/knowledge-documents/ask/", {
            "query": "stream3 是怎么实现上下文会话的？",
            "top_k": 3,
            "model": "deepseek",
            "conversation_id": conversation_id,
        }, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["conversation_id"], conversation_id)

        # 真实查询
        log = AICallLog.objects.filter(conversation_id=conversation_id).first()
        # 期望log不是None  因为对测试数据库来说是一个正常字符串 ask调用成功后会调用save_conversation_messages_to_db
        self.assertIsNotNone(log)
        self.assertEqual(log.prompt, "stream3 是怎么实现上下文会话的？")
        self.assertEqual(log.response, "stream3 通过 conversation_id 关联上下文。")

        # 这里的self.user来自setup   .first()只取第一条
        conversation = Conversation.objects.filter(conversation_id=conversation_id, user=self.user).first()
        self.assertIsNotNone(conversation)

        messages = ConversationMessage.objects.filter(conversation=conversation).order_by("created_at")
        # count()：数据库数数量，适合只关心数量
        # len()：把数据取出来再数，适合后面本来就要遍历/使用数据
        self.assertEqual(len(messages), 2)
        self.assertEqual((messages[0].role), "user")
        self.assertEqual(messages[0].content, "stream3 是怎么实现上下文会话的？")
        self.assertEqual(messages[1].role, "assistant")
        self.assertEqual(messages[1].content, "stream3 通过 conversation_id 关联上下文。")

    @patch("ai_log.views.call_ai_service")
    def test_ask_creates_conversation_id_when_missing(self, mock_call_ai_service):
        doc = KnowledgeDocument.objects.create(
            user=self.user,
            title="AI日志项目说明",
            content="stream3 使用 conversation_id 实现上下文会话"
        )

        KnowledgeChunk.objects.create(
            document=doc,
            content="stream3 使用 conversation_id 实现上下文会话",
            chunk_index=0
        )

        mock_call_ai_service.return_value = ({
            "reply": "stream3 会在没有 conversation_id 时自动创建会话。",
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
            "cost": 0.001,
            "duration": 1.2,
        }, True)

        response = self.client.post("/api/knowledge-documents/ask/", {
            "query": "stream3 会不会自动创建会话？",
            "top_k": 3,
            "model": "deepseek",
        }, format="json")

        self.assertEqual(response.status_code, 200)
        
        conversation_id = response.data["data"]["conversation_id"]
        # 断言为真 =》 这个conversation_id有值
        self.assertTrue(conversation_id)

        conversation = Conversation.objects.filter(
            conversation_id=conversation_id,
            user=self.user
        ).first()

        self.assertIsNotNone(conversation)
        
        """
        conversation=conversation 是django orm常见的写法
        因为ConversationMessage中的Conversation是外键
        class ConversationMessage(models.Model):
            conversation = models.ForeignKey(
                Conversation,
                on_delete=models.CASCADE,
                related_name="messages"
            )
        """
        message = list(
            ConversationMessage.objects.filter(
                conversation=conversation
            ).order_by("created_at")
        )

        self.assertEqual(len(message), 2)
        self.assertEqual(message[0].role, "user")
        self.assertEqual(message[1].role, "assistant")

        log = AICallLog.objects.filter(
            conversation_id=conversation_id,
            user=self.user
        ).first()

        self.assertIsNotNone(log)

    @patch("ai_log.views.call_ai_service")
    def test_ask_saves_trace_id_to_ai_call_log(self, mock_call_ai_service):
        trace_id = "test-trace-id-001"

        doc = KnowledgeDocument.objects.create(
            user=self.user,
            title="AI日志项目说明",
            content="stream3 使用 conversation_id 实现上下文会话"
        )

        KnowledgeChunk.objects.create(
            document=doc,
            content="stream3 使用 conversation_id 实现上下文会话",
            chunk_index=0
        )

        mock_call_ai_service.return_value = ({
            "reply": "根据知识库资料，stream3 使用 conversation_id 保存上下文。",
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
            "cost": 0.001,
            "duration": 1.2,
        }, True)

        response = self.client.post("/api/knowledge-documents/ask/",{
                "query": "stream3 是怎么实现上下文会话的？",
                "top_k": 3,
                "model": "deepseek",
            },
            format="json",
            # django测试里面写这样模拟真实请求头： HTTP_ + 大写请求头名 + 横杠变下划线
            HTTP_X_TRACE_ID=trace_id,
        )

        self.assertEqual(response.status_code, 200)

        log = AICallLog.objects.filter(trace_id=trace_id, user=self.user).first()

        self.assertIsNotNone(log)
        self.assertEqual(log.trace_id, trace_id)
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.prompt, "stream3 是怎么实现上下文会话的？")

class AICallLogApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="loguser",
            password="123456"
        )
        # DRF 专门给测试用的假前端，模拟发请求
        self.client = APIClient()
        # 强制让后面的请求都当成 self.user 已登录
        self.client.force_authenticate(user=self.user)

    def test_filter_logs_by_trace_id(self):
        AICallLog.objects.create(
            user=self.user,
            prompt="问题1",
            response="回答1",
            model_name="deepseek",
            success=True,
            trace_id="test-aaa-001",
        )

        AICallLog.objects.create(
            user=self.user,
            prompt="问题2",
            response="回答2",
            model_name="deepseek",
            success=True,
            trace_id="test-bbb-002",
        )

        # 模拟：GET /api/logs/?trace_id=aaa
        # 因为后端用了 queryset = queryset.filter(trace_id__icontains=trace_id) 匹配test-aaa-001
        # 这个走的是真实接口
        response = self.client.get("/api/logs/", {
            "trace_id": "aaa",
        })

        self.assertEqual(response.status_code, 200)

        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["trace_id"], "test-aaa-001")
        self.assertEqual(results[0]["prompt"], "问题1")

    def test_filter_logs_by_trace_id_only_current_user(self):
        # 用户隔离测试
        other_user = User.objects.create_user(username="otherloguser", password="123456")

        AICallLog.objects.create(
            user=self.user,
            prompt="自己的问题",
            response="自己的回答",
            model_name="deepseek",
            success=True,
            trace_id="same-trace-id",
        )

        AICallLog.objects.create(
            user=other_user,
            prompt="别人的问题",
            response="别人的回答",
            model_name="deepseek",
            success=True,
            trace_id="same-trace-id",
        )

        response = self.client.get("/api/logs/", {
            "trace_id": "same-trace-id",
        })

        self.assertEqual(response.status_code, 200)

        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["prompt"], "自己的问题")

    @patch("ai_log.views.call_ai_service")
    def test_ask_creates_rag_trace_logs(self, mock_call_ai_service):
        trace_id = "test-rag-trace-001"
        conversation_id = "test-rag-conversation-trace-001"

        doc = KnowledgeDocument.objects.create(
            user=self.user,
            title="AI日志项目说明",
            content="stream3 使用 conversation_id 实现上下文会话"
        )

        KnowledgeChunk.objects.create(
            document=doc,
            content="stream3 使用 conversation_id 实现上下文会话",
            chunk_index=0
        )

        mock_call_ai_service.return_value = ({
            "reply": "stream3 使用 conversation_id 实现上下文会话。",
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
            "cost": 0.001,
            "duration": 1.2,
        }, True)

        response = self.client.post("/api/knowledge-documents/ask/",{
            "query": "stream3 是怎么实现上下文会话的？",
            "top_k": 3,
            "model": "deepseek",
            "conversation_id": conversation_id,
        }, format="json",HTTP_X_TRACE_ID=trace_id)

        self.assertEqual(response.status_code, 200)

        trace_logs = RagTraceLog.objects.filter(
            trace_id=trace_id,
            conversation_id=conversation_id,
            user=self.user
        ).order_by("created_at")

        steps = [item.step for item in trace_logs]

        self.assertIn("rag_start", steps)
        self.assertIn("retrieve_chunks", steps)
        self.assertIn("build_prompt", steps)
        self.assertIn("rag_done", steps)

        retrieve_log = RagTraceLog.objects.filter(
            trace_id=trace_id,
            step="retrieve_chunks",
            user=self.user
        ).first()

        self.assertIsNotNone(retrieve_log)
        self.assertEqual(retrieve_log.detail["hit_count"], 1)
        self.assertEqual(retrieve_log.detail["top_k"], 3)
        self.assertEqual(len(retrieve_log.detail["chunk_ids"]), 1)

    @patch("ai_log.views.call_ai_service")
    def test_ask_creates_no_hit_trace_log(self, mock_call_ai_service):
        trace_id = "test-rag-no-hit-trace-001"

        response = self.client.post("/api/knowledge-documents/ask/",
            {
                "query": "完全不存在的问题",
                "top_k": 3,
                "model": "deepseek",
            },
            format="json",
            HTTP_X_TRACE_ID=trace_id,
        )

        self.assertEqual(response.status_code, 200)
        mock_call_ai_service.assert_not_called()

        no_hit_log = RagTraceLog.objects.filter(
            trace_id=trace_id,
            step="rag_no_hit",
            user=self.user
        ).first()

        self.assertIsNotNone(no_hit_log)
        self.assertEqual(no_hit_log.detail["answer"], "知识库中没有检索到相关内容。")

    @patch("ai_log.views.call_ai_service")
    def test_ask_creates_failed_call_model_trace_log(self, mock_call_ai_service):
        """
        知识库命中了
        -> call_ai_service 被调用
        -> call_ai_service 返回 success=False
        -> ask 返回 500
        -> RagTraceLog 里记录 step=call_model 且 success=False
        """
        trace_id="test-rag-call-model-failed-001"
        conversation_id="test-rag-call-model-conversation-001"

        doc = KnowledgeDocument.objects.create(
            user=self.user,
            title="AI日志项目说明",
            content="stream3 使用 conversation_id 实现上下文会话"
        )

        KnowledgeChunk.objects.create(
            document=doc,
            content="stream3 使用 conversation_id 实现上下文会话",
            chunk_index=0
        )

        mock_call_ai_service.return_value = ({
            "reply": "模型调用失败",
            "duration": 0.5,
        }, False)

        response = self.client.post("/api/knowledge-documents/ask/",
            {
                "query": "stream3 是怎么实现上下文会话的？",
                "top_k": 3,
                "model": "deepseek",
                "conversation_id": conversation_id,
            },
            format="json",
            HTTP_X_TRACE_ID=trace_id,
        )
        self.assertEqual(response.status_code, 500)
        
        failed_log = RagTraceLog.objects.filter(
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="call_model",
            user=self.user
        ).first()

        self.assertIsNotNone(failed_log)
        self.assertFalse(failed_log.success)
        self.assertEqual(failed_log.error_message, "模型调用失败")
        self.assertEqual(failed_log.detail["model"], "deepseek")

class RagTraceLogApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ragtraceuser", password="123456")
        self.other_user = User.objects.create_user(username="otherragtraceuser", password="123456")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_filter_rag_trace_logs_by_trace_id(self):
        RagTraceLog.objects.create(
            user=self.user,
            trace_id="trace-aaa-001",
            conversation_id="conv-001",
            step="retrieve_chunks",
            query="stream3",
            # 命中数量，找到几个chunk就是几
            detail={"hit_count": 1},
        )

        RagTraceLog.objects.create(
            user=self.other_user,
            trace_id="trace-bbb-002",
            conversation_id="conv-002",
            step="rag_done",
            query="别的问题",
            detail={"hit_count": 2},
        )

        response = self.client.get('/api/rag-trace-logs/', {
            "trace_id": "aaa"
        })
        self.assertEqual(response.status_code, 200)
        
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["trace_id"], "trace-aaa-001")
        self.assertEqual(results[0]["step"], "retrieve_chunks")

    def test_user_can_only_see_own_rag_trace_logs(self):
        RagTraceLog.objects.create(
            user=self.user,
            trace_id="same-trace",
            conversation_id="conv-001",
            step="rag_done",
            query="自己的问题",
            detail={},
        )

        RagTraceLog.objects.create(
            user=self.other_user,
            trace_id="same-trace",
            conversation_id="conv-002",
            step="rag_done",
            query="别人的问题",
            detail={},
        )

        response = self.client.get("/api/rag-trace-logs/", {
            "trace_id": "same-trace",
        })

        self.assertEqual(response.status_code, 200)

        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["query"], "自己的问题")

    def test_filter_rag_trace_logs_by_step(self):
        # 验证 GET /api/rag-trace-logs/?step=retrieve_chunks
        # 只返回步骤
        RagTraceLog.objects.create(
            user=self.user,
            trace_id="trace-001",
            conversation_id="conv-001",
            step="retrieve_chunks",
            query="stream3",
            detail={"hit_count": 1},
        )

        RagTraceLog.objects.create(
            user=self.user,
            trace_id="trace-001",
            conversation_id="conv-001",
            step="rag_done",
            query="stream3",
            detail={"answer_length": 20},
        )

        response = self.client.get('/api/rag-trace-logs/', {
            "step": "retrieve_chunks"
        })
        self.assertEqual(response.status_code, 200)

        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["step"], "retrieve_chunks")

    def test_filter_rag_trace_logs_by_failed_status(self):
        RagTraceLog.objects.create(
            user=self.user,
            trace_id="trace-success",
            conversation_id="conv-001",
            step="rag_done",
            query="成功的问题",
            detail={},
            success=True,
        )

        RagTraceLog.objects.create(
            user=self.user,
            trace_id="trace-failed",
            conversation_id="conv-002",
            step="call_model",
            query="失败的问题",
            detail={"model": "deepseek"},
            success=False,
            error_message="模型调用失败",
        )

        response = self.client.get("/api/rag-trace-logs/", {
            "success": "false",
        })

        self.assertEqual(response.status_code, 200)

        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["trace_id"], "trace-failed")
        self.assertEqual(results[0]["success"], False)
        self.assertEqual(results[0]["error_message"], "模型调用失败")










