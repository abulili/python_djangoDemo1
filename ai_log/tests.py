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
    AiTraceStepLog,
)
from .views import split_text_to_chunks, simple_keyword_score
from .services import calculate_cost

from unittest.mock import patch

from ai_log.tasks import call_ai_task4, get_ai_retry_countdown

from django.test import override_settings
from unittest.mock import patch
import unittest

from django.core.cache import cache

from ai_log.throttles import AICallThrottle, TaskStatusThrottle

from celery.exceptions import Retry, SoftTimeLimitExceeded

from django.utils import timezone
from datetime import timedelta

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

        trace_logs = AiTraceStepLog.objects.filter(
            trace_id=trace_id,
            conversation_id=conversation_id,
            user=self.user
        ).order_by("created_at")

        steps = [item.step for item in trace_logs]

        self.assertIn("rag_start", steps)
        self.assertIn("retrieve_chunks", steps)
        self.assertIn("build_prompt", steps)
        self.assertIn("rag_done", steps)

        retrieve_log = AiTraceStepLog.objects.filter(
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

        no_hit_log = AiTraceStepLog.objects.filter(
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
        -> AiTraceStepLog 里记录 step=call_model 且 success=False
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
        
        failed_log = AiTraceStepLog.objects.filter(
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="call_model",
            user=self.user
        ).first()

        self.assertIsNotNone(failed_log)
        self.assertFalse(failed_log.success)
        self.assertEqual(failed_log.error_message, "模型调用失败")
        self.assertEqual(failed_log.detail["model"], "deepseek")

class AiTraceStepLogApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ragtraceuser", password="123456")
        self.other_user = User.objects.create_user(username="otherragtraceuser", password="123456")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_filter_rag_trace_logs_by_trace_id(self):
        AiTraceStepLog.objects.create(
            user=self.user,
            trace_id="trace-aaa-001",
            conversation_id="conv-001",
            step="retrieve_chunks",
            query="stream3",
            # 命中数量，找到几个chunk就是几
            detail={"hit_count": 1},
        )

        AiTraceStepLog.objects.create(
            user=self.other_user,
            trace_id="trace-bbb-002",
            conversation_id="conv-002",
            step="rag_done",
            query="别的问题",
            detail={"hit_count": 2},
        )

        response = self.client.get('/api/ai-trace-step-logs/', {
            "trace_id": "aaa"
        })
        self.assertEqual(response.status_code, 200)
        
        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["trace_id"], "trace-aaa-001")
        self.assertEqual(results[0]["step"], "retrieve_chunks")

    def test_user_can_only_see_own_rag_trace_logs(self):
        AiTraceStepLog.objects.create(
            user=self.user,
            trace_id="same-trace",
            conversation_id="conv-001",
            step="rag_done",
            query="自己的问题",
            detail={},
        )

        AiTraceStepLog.objects.create(
            user=self.other_user,
            trace_id="same-trace",
            conversation_id="conv-002",
            step="rag_done",
            query="别人的问题",
            detail={},
        )

        response = self.client.get("/api/ai-trace-step-logs/", {
            "trace_id": "same-trace",
        })

        self.assertEqual(response.status_code, 200)

        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["query"], "自己的问题")

    def test_filter_rag_trace_logs_by_step(self):
        # 验证 GET /api/ai-trace-step-logs/?step=retrieve_chunks
        # 只返回步骤
        AiTraceStepLog.objects.create(
            user=self.user,
            trace_id="trace-001",
            conversation_id="conv-001",
            step="retrieve_chunks",
            query="stream3",
            detail={"hit_count": 1},
        )

        AiTraceStepLog.objects.create(
            user=self.user,
            trace_id="trace-001",
            conversation_id="conv-001",
            step="rag_done",
            query="stream3",
            detail={"answer_length": 20},
        )

        response = self.client.get('/api/ai-trace-step-logs/', {
            "step": "retrieve_chunks"
        })
        self.assertEqual(response.status_code, 200)

        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["step"], "retrieve_chunks")

    def test_filter_rag_trace_logs_by_failed_status(self):
        AiTraceStepLog.objects.create(
            user=self.user,
            trace_id="trace-success",
            conversation_id="conv-001",
            step="rag_done",
            query="成功的问题",
            detail={},
            success=True,
        )

        AiTraceStepLog.objects.create(
            user=self.user,
            trace_id="trace-failed",
            conversation_id="conv-002",
            step="call_model",
            query="失败的问题",
            detail={"model": "deepseek"},
            success=False,
            error_message="模型调用失败",
        )

        response = self.client.get("/api/ai-trace-step-logs/", {
            "success": "false",
        })

        self.assertEqual(response.status_code, 200)

        results = response.data["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["trace_id"], "trace-failed")
        self.assertEqual(results[0]["success"], False)
        self.assertEqual(results[0]["error_message"], "模型调用失败")

    def test_get_trace_detail_returns_ai_log_and_trace_steps(self):
        trace_id = "trace-detail-001"

        AICallLog.objects.create(
            user=self.user,
            prompt="stream3 是怎么实现上下文会话的？",
            response="stream3 使用 conversation_id。",
            model_name="deepseek",
            success=True,
            trace_id=trace_id,
            duration=1.2,
        )

        AiTraceStepLog.objects.create(
            user=self.user,
            trace_id=trace_id,
            conversation_id="conv-001",
            step="retrieve_chunks",
            query="stream3",
            detail={"hit_count": 1},
            success=True,
        )

        AiTraceStepLog.objects.create(
            user=self.user,
            trace_id=trace_id,
            conversation_id="conv-001",
            step="rag_done",
            query="stream3",
            detail={"answer_length": 20},
            success=True,
        )

        response = self.client.get(f"/api/logs/trace/{trace_id}/")

        self.assertEqual(response.status_code, 200)
        
        data = response.data["data"]
        self.assertEqual(data["trace_id"], trace_id)
        self.assertEqual(len(data["logs"]), 1)
        self.assertEqual(len(data["steps"]), 2)
        self.assertEqual(data["steps"], data["rag_steps"])
        self.assertEqual(data["steps"][0]["step"], "retrieve_chunks")
        self.assertEqual(data["summary"]["log_count"], 1)
        self.assertEqual(data["summary"]["step_count"], 2)
        self.assertFalse(data["summary"]["has_failed_step"])
        self.assertEqual(data["summary"]["stream_step_count"], 0)
        self.assertEqual(data["summary"]["rag_step_count"], 2)
        self.assertEqual(data["summary"]["task_step_count"], 0)

    def test_trace_detail_only_returns_current_user_data(self):
        other_user = User.objects.create_user(username="traceother", password="123456")
        trace_id = "same-trace-detail"

        AICallLog.objects.create(
            user=self.user,
            prompt="自己的问题",
            response="自己的回答",
            model_name="deepseek",
            success=True,
            trace_id=trace_id,
        )

        AICallLog.objects.create(
            user=other_user,
            prompt="别人的问题",
            response="别人的回答",
            model_name="deepseek",
            success=True,
            trace_id=trace_id,
        )

        AiTraceStepLog.objects.create(
            user=self.user,
            trace_id=trace_id,
            conversation_id="conv-own",
            step="rag_done",
            query="自己的问题",
            detail={},
        )

        AiTraceStepLog.objects.create(
            user=other_user,
            trace_id=trace_id,
            conversation_id="conv-other",
            step="rag_done",
            query="别人的问题",
            detail={},
        )

        response = self.client.get(f"/api/logs/trace/{trace_id}/")

        self.assertEqual(response.status_code, 200)

        data = response.data["data"]

        self.assertEqual(len(data["logs"]), 1)
        self.assertEqual(len(data["steps"]), 1)
        self.assertEqual(data["steps"], data["rag_steps"])
        self.assertEqual(data["logs"][0]["prompt"], "自己的问题")
        self.assertEqual(data["steps"][0]["query"], "自己的问题")

    @patch("ai_log.views.OpenAI")
    def test_stream3_creates_ai_trace_steps(self, mock_openai):
        # 普通流式产生追踪日志
        """
        请求 stream3
        -> mock 模型返回 “你好”
        -> 消费 streaming_content
        -> 后端保存 AICallLog
        -> 后端保存 AiTraceStepLog
        -> 检查步骤链路完整
        """
        trace_id = "test-stream3-trace-001"


        # 这些class模拟流式chunk chunk.choices[0].delta.content
        class FakeDelta:
            content = "你好"

        class FakeChoice:
            delta = FakeDelta()

        class FakeUsage:
            prompt_tokens = 10
            completion_tokens = 5
            total_tokens = 15

        class FakeChunk:
            choices = [FakeChoice()]
            usage = None

        class FakeUsageChunk:
            choices = []
            usage = FakeUsage()

        mock_client = mock_openai.return_value
        mock_client.chat.completions.create.return_value = [
            FakeChunk(),
            FakeUsageChunk(),
        ]

        conversation_id = "test-stream3-conversation-001"
        response = self.client.post("/api/logs/stream3/",
            {
                "prompt": "你好",
                "model": "deepseek",
                "conversation_id": conversation_id,
            },
            HTTP_X_TRACE_ID=trace_id,
            format="json"
        )
        self.assertEqual(response.status_code, 200)
        
        # StreamingHttpResponse主动执行，yield生成器中的代码才会真正执行
        # bytes，字节串，拼起来
        content = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("你好",content)

        steps = AiTraceStepLog.objects.filter(trace_id=trace_id).order_by("created_at")
        step_names = [item.step for item in steps]

        self.assertIn("stream_start", step_names)
        self.assertIn("load_history", step_names)
        self.assertIn("build_messages", step_names)
        self.assertIn("call_model_start", step_names)
        self.assertIn("stream_done", step_names)

        trace_response = self.client.get(f"/api/logs/trace/{trace_id}/")
        trace_data = trace_response.data["data"]

        log = AICallLog.objects.filter(trace_id=trace_id).first()
        self.assertIsNotNone(log)
        self.assertTrue(log.success)

        trace_response = self.client.get(f"/api/logs/trace/{trace_id}/")
        self.assertEqual(trace_response.status_code, 200)
        trace_data = trace_response.data["data"]
        self.assertGreater(trace_data["summary"]["stream_step_count"], 0)
        self.assertEqual(trace_data["summary"]["rag_step_count"], 0)

        log = AICallLog.objects.filter(
            trace_id=trace_id,
            conversation_id=conversation_id,
        ).first()

        self.assertIsNotNone(log)
        self.assertTrue(log.success)
        self.assertEqual(log.prompt, "你好")
        self.assertEqual(log.response, "你好")
        self.assertEqual(log.total_tokens, 15)

        done_step = steps.filter(step="stream_done").first()
        self.assertIsNotNone(done_step)
        self.assertGreaterEqual(done_step.duration, 0)

    @patch("ai_log.tasks.call_ai_service")
    def test_call_ai_task4_creates_trace_steps_when_success(self, mock_call_ai_service):
        trace_id = "test-task4-trace-success"
        conversation_id = "test-task4-conversation-success"

        mock_call_ai_service.return_value = (
            {
                "reply": "这是非流式回答",
                "duration": 1.23,
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "cost": 0.001,
            },
            True,
        )

        result = call_ai_task4(
            "非流式测试问题",
            self.user.id,
            "deepseek",
            conversation_id,
            None,
            None,
            trace_id,
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["response"], "这是非流式回答")

        log = AICallLog.objects.filter(trace_id=trace_id).first()
        self.assertIsNotNone(log)
        self.assertTrue(log.success)
        self.assertEqual(log.conversation_id, conversation_id)
        self.assertEqual(log.total_tokens, 15)

        steps = AiTraceStepLog.objects.filter(trace_id=trace_id).order_by("created_at")
        step_names = [item.step for item in steps]

        self.assertEqual(step_names, [
            "task_start",
            "call_model_start",
            "task_done",
        ])

        done_step = steps.filter(step="task_done").first()
        self.assertIsNotNone(done_step)
        self.assertEqual(done_step.duration, 1.23)
        self.assertTrue(done_step.success)
        self.assertEqual(done_step.detail["duration"], 1.23)
        self.assertEqual(done_step.detail["total_tokens"], 15)

        mock_call_ai_service.assert_called_once()

    @patch("ai_log.tasks.call_ai_service")
    def test_call_ai_task4_creates_trace_steps_when_service_returns_failed(self, mock_call_ai_service):
        trace_id = "test-task4-trace-failed"
        conversation_id = "test-task4-conversation-failed"

        mock_call_ai_service.return_value = (
            {
                "reply": "Agnes 返回未知状态",
                "duration": 0.8,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost": 0,
            },
            False,
        )

        result = call_ai_task4(
            "非流式失败测试",
            self.user.id,
            "agnes",
            conversation_id,
            None,
            None,
            trace_id,
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["response"], "Agnes 返回未知状态")

        log = AICallLog.objects.filter(trace_id=trace_id).first()
        self.assertIsNotNone(log)
        self.assertFalse(log.success)
        self.assertEqual(log.model_name, "agnes")

        steps = AiTraceStepLog.objects.filter(trace_id=trace_id).order_by("created_at")
        step_names = [item.step for item in steps]

        self.assertEqual(step_names, [
            "task_start",
            "call_model_start",
            "task_failed",
        ])

        failed_step = steps.filter(step="task_failed").first()
        self.assertEqual(failed_step.duration, 0.8)
        self.assertIsNotNone(failed_step)
        self.assertFalse(failed_step.success)
        self.assertEqual(failed_step.error_message, "Agnes 返回未知状态")

        mock_call_ai_service.assert_called_once()

    @patch("ai_log.tasks.call_ai_service")
    def test_call_ai_task4_creates_trace_steps_when_service_raises_exception(self, mock_call_ai_service):
        mock_call_ai_service.side_effect = Exception("模型接口超时")

        with self.assertRaises(Retry):
            call_ai_task4.apply(
                args=[
                    "非流式异常测试",
                    self.user.id,
                    "deepseek",
                    "test-task4-conversation-exception",
                    None,
                    {},
                    "test-task4-trace-exception",
                ],
                throw=True,
            )

        retry_step = AiTraceStepLog.objects.filter(
            user=self.user,
            trace_id="test-task4-trace-exception",
            step="task_retry",
        ).first()

        self.assertIsNotNone(retry_step)
        self.assertFalse(retry_step.success)
        self.assertEqual(retry_step.error_message, "模型接口超时")

        failed_log = AICallLog.objects.filter(
            user=self.user,
            trace_id="test-task4-trace-exception",
        ).first()

        self.assertIsNone(failed_log)

    @patch("ai_log.tasks.call_ai_service")
    def test_call_ai_task4_creates_failed_log_when_soft_time_limit_exceeded(self, mock_call_ai_service):
        # 只要代码里调用 call_ai_service(...)，不去真的请求，立刻抛出 SoftTimeLimitExceeded 这个异常
        mock_call_ai_service.side_effect = SoftTimeLimitExceeded()

        trace_id = "test-soft-time-limit-trace"
        conversation_id = "test-soft-time-limit-conversation"

        result = call_ai_task4.apply(
            args=[
                "软超时测试问题",
                self.user.id,
                "deepseek",
                conversation_id,
                None,
                {},
                trace_id,
            ]
        ).get()

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "AI任务执行超时")
        self.assertEqual(result["trace_id"], trace_id)

        failed_step = AiTraceStepLog.objects.filter(
            trace_id=trace_id,
            step="task_failed",
        ).first()

        self.assertIsNotNone(failed_step)
        self.assertFalse(failed_step.success)
        self.assertEqual(failed_step.error_message, "AI任务执行超时")
        self.assertEqual(failed_step.detail["reason"], "soft_time_limit_exceeded")

        log = AICallLog.objects.filter(trace_id=trace_id).first()

        self.assertIsNotNone(log)
        self.assertFalse(log.success)
        self.assertEqual(log.response, "AI任务执行超时")


    @patch("ai_log.views.call_ai_task4.delay")
    def test_call_company_ai4_creates_enqueue_trace_step(self, mock_delay):
        trace_id = "test-call-company-ai4-enqueue"
        conversation_id = "test-call-company-ai4-conversation"

        class FakeTask:
            id = "fake-task-id-001"

        mock_delay.return_value = FakeTask()

        response = self.client.post(
            "/api/logs/call_company_ai4/",
            {
                "prompt": "非流式接口测试",
                "model": "deepseek",
                "conversation_id": conversation_id,
            },
            HTTP_X_TRACE_ID=trace_id,
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["task_id"], "fake-task-id-001")
        self.assertEqual(response.data["data"]["conversation_id"], conversation_id)

        enqueue_step = AiTraceStepLog.objects.filter(
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="enqueue_task",
        ).first()

        self.assertIsNotNone(enqueue_step)
        self.assertEqual(enqueue_step.query, "非流式接口测试")
        self.assertEqual(enqueue_step.detail["model"], "deepseek")
        self.assertEqual(enqueue_step.detail["has_template_vars"], False)

        mock_delay.assert_called_once_with(
            "非流式接口测试",
            self.user.id,
            "deepseek",
            conversation_id,
            None,
            {},
            trace_id,
        )

    @override_settings(AI_TASK_OWNER_CACHE_SECONDS=234)
    @patch("ai_log.views.cache.set")
    @patch("ai_log.views.call_ai_task4.delay")
    def test_call_company_ai4_uses_owner_cache_timeout_setting(self, mock_delay, mock_cache_set):
        class FakeTask:
            id = "owner-cache-timeout-task-id"

        mock_delay.return_value = FakeTask()

        response = self.client.post(
            "/api/logs/call_company_ai4/",
            {
                "prompt": "owner cache timeout 测试",
                "model_key": "deepseek",
                "conversation_id": "owner-cache-timeout-conversation",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        
        owner_cache_calls = [
            call for call in mock_cache_set.call_args_list
            if call.args[0] == "ai_task_owner:owner-cache-timeout-task-id"
        ]

        self.assertEqual(len(owner_cache_calls), 1)

        cache_key, cache_value = owner_cache_calls[0].args

        self.assertEqual(cache_key, "ai_task_owner:owner-cache-timeout-task-id")
        self.assertEqual(cache_value["user_id"], self.user.id)
        self.assertEqual(cache_value["conversation_id"], "owner-cache-timeout-conversation")
        self.assertTrue(cache_value["trace_id"])
        self.assertEqual(owner_cache_calls[0].kwargs["timeout"], 234)

    def test_trace_detail_counts_task_steps(self):
        trace_id = "trace-task-summary-001"
        conversation_id = "conv-task-summary-001"

        AICallLog.objects.create(
            user=self.user,
            prompt="非流式任务测试",
            response="非流式任务回答",
            model_name="deepseek",
            success=True,
            trace_id=trace_id,
            conversation_id=conversation_id,
            duration=1.2,
        )

        AiTraceStepLog.objects.create(
            user=self.user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="enqueue_task",
            query="非流式任务测试",
            detail={},
            success=True,
        )

        AiTraceStepLog.objects.create(
            user=self.user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="task_start",
            query="非流式任务测试",
            detail={},
            success=True,
        )

        AiTraceStepLog.objects.create(
            user=self.user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="call_model_start",
            query="非流式任务测试",
            detail={"stream": False},
            success=True,
        )

        AiTraceStepLog.objects.create(
            user=self.user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="task_done",
            query="非流式任务测试",
            detail={},
            success=True,
        )

        response = self.client.get(f"/api/logs/trace/{trace_id}/")
        self.assertEqual(response.status_code, 200)

        data = response.data["data"]

        """
        item["step"].startswith("task_") or item["step"] in ["enqueue_task", "call_model_start"]

        enqueue_task       算
        task_start         算
        call_model_start   算
        task_done          算
        """
        self.assertEqual(data["summary"]["task_step_count"], 4)
        self.assertEqual(data["summary"]["stream_step_count"], 0)
        self.assertEqual(data["summary"]["rag_step_count"], 0)
        self.assertEqual(data["summary"]["step_count"], 4)

    @patch("ai_log.tasks.call_ai_service")
    def test_call_ai_task4_retries_when_service_raises_exception(self, mock_call_ai_service):
        mock_call_ai_service.side_effect = Exception("模型接口超时")

        with self.assertRaises(Retry):
            call_ai_task4.apply(
                args=[
                    "重试测试问题",
                    self.user.id,
                    "deepseek",
                    "test-retry-conversation",
                    None,
                    {},
                    "test-retry-trace",
                ],
                throw=True,
            )

        retry_step = AiTraceStepLog.objects.filter(
            user=self.user,
            trace_id="test-retry-trace",
            step="task_retry",
        ).first()

        self.assertIsNotNone(retry_step)
        self.assertFalse(retry_step.success)
        self.assertEqual(retry_step.error_message, "模型接口超时")
        self.assertEqual(retry_step.detail["retry_count"], 1)
        self.assertEqual(retry_step.detail["max_retries"], 3)

        failed_log = AICallLog.objects.filter(
            user=self.user,
            trace_id="test-retry-trace",
        ).first()

        self.assertIsNone(failed_log)

    @patch("ai_log.tasks.call_ai_service")
    def test_call_ai_task4_creates_failed_log_when_max_retries_exceeded(self, mock_call_ai_service):
        mock_call_ai_service.side_effect = Exception("模型接口连续超时")

        result = call_ai_task4.apply(
            args=[
                "最大重试失败测试",
                self.user.id,
                "deepseek",
                "test-max-retry-conversation",
                None,
                {},
                "test-max-retry-trace",
            ],
            retries=3,
            throw=False,
        ).result

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "模型接口连续超时")
        self.assertEqual(result["trace_id"], "test-max-retry-trace")

        failed_step = AiTraceStepLog.objects.filter(
            user=self.user,
            trace_id="test-max-retry-trace",
            step="task_failed",
        ).first()

        self.assertIsNotNone(failed_step)
        self.assertFalse(failed_step.success)
        self.assertEqual(failed_step.error_message, "模型接口连续超时")
        self.assertEqual(failed_step.detail["reason"], "max_retries_exceeded")

        failed_log = AICallLog.objects.filter(
            user=self.user,
            trace_id="test-max-retry-trace",
            success=False,
        ).first()

        self.assertIsNotNone(failed_log)
        self.assertEqual(failed_log.response, "模型接口连续超时")

    @patch("ai_log.tasks.call_ai_service")
    def test_call_ai_task4_succeeds_after_retries(self, mock_call_ai_service):
        mock_call_ai_service.side_effect = [
            Exception("第一次超时"),# 第一次抛异常超时
            Exception("第二次超时"),
            ({
                "reply": "第三次成功回答",
                "duration": 0.3,
                "prompt_tokens": 10,
                "completion_tokens": 8,
                "total_tokens": 18,
                "cost": 0.001,
            }, True),
        ]

        # 用三次同步执行模拟 Celery 的三次尝试
        # with 的意思是：进入一个上下文环境。
        # 里面这段代码必须抛出 Retry 异常，测试才算通过。
        # 我预期接下来这段代码会报 Retry。如果真的报 Retry，就通过。如果没报 Retry，就失败
        with self.assertRaises(Retry):
            # 这个apply表示同步指定celery任务，现在就执行这个task
            call_ai_task4.apply(
                args=[
                    "重试后成功测试",
                    self.user.id,
                    "deepseek",
                    "test-retry-success-conversation",
                    None,
                    {},
                    "test-retry-success-trace",
                ],
                retries=0,
                throw=True,
            )

        with self.assertRaises(Retry):
            call_ai_task4.apply(
                args=[
                    "重试后成功测试",
                    self.user.id,
                    "deepseek",
                    "test-retry-success-conversation",
                    None,
                    {},
                    "test-retry-success-trace",
                ],
                retries=1,
                throw=True,
            )

        result = call_ai_task4.apply(
            args=[
                "重试后成功测试",
                self.user.id,
                "deepseek",
                "test-retry-success-conversation",
                None,
                {},
                "test-retry-success-trace",
            ],
            retries=2,
            throw=False,
        ).result

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["response"], "第三次成功回答")
        self.assertEqual(result["trace_id"], "test-retry-success-trace")

        retry_steps = AiTraceStepLog.objects.filter(
            user=self.user,
            trace_id="test-retry-success-trace",
            step="task_retry",
        )

        self.assertEqual(retry_steps.count(), 2)

        done_step = AiTraceStepLog.objects.filter(
            user=self.user,
            trace_id="test-retry-success-trace",
            step="task_done",
        ).first()

        self.assertIsNotNone(done_step)
        self.assertTrue(done_step.success)

        log = AICallLog.objects.filter(
            user=self.user,
            trace_id="test-retry-success-trace",
            success=True,
        ).first()

        self.assertIsNotNone(log)
        self.assertEqual(log.response, "第三次成功回答")

        self.assertEqual(mock_call_ai_service.call_count, 3)

    @patch("ai_log.tasks.call_ai_service")
    def test_call_ai_task4_does_not_retry_non_retryable_error(self, mock_call_ai_service):
        mock_call_ai_service.side_effect = Exception("401 unauthorized")

        result = call_ai_task4.apply(
            args=[
                "不可重试错误测试",
                self.user.id,
                "deepseek",
                "test-non-retryable-conversation",
                None,
                {},
                "test-non-retryable-trace",
            ],
            retries=0,
            throw=False,
        ).result

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "401 unauthorized")

        retry_step = AiTraceStepLog.objects.filter(
            user=self.user,
            trace_id="test-non-retryable-trace",
            step="task_retry",
        ).first()

        self.assertIsNone(retry_step)

        failed_step = AiTraceStepLog.objects.filter(
            user=self.user,
            trace_id="test-non-retryable-trace",
            step="task_failed",
        ).first()

        self.assertIsNotNone(failed_step)
        self.assertFalse(failed_step.success)
        self.assertEqual(failed_step.detail["reason"], "non_retryable_error")
        self.assertFalse(failed_step.detail["retryable"])

        self.assertEqual(mock_call_ai_service.call_count, 1)

    def test_get_ai_retry_countdown_for_rate_limit(self):
        self.assertEqual(get_ai_retry_countdown("429 rate limit"), 10)

    def test_get_ai_retry_countdown_for_temporarily_unavailable(self):
        self.assertEqual(get_ai_retry_countdown("503 temporarily unavailable"), 5)

    def test_get_ai_retry_countdown_default(self):
        self.assertEqual(get_ai_retry_countdown("connection timeout"), 2)

    @patch("ai_log.tasks.call_ai_service")
    def test_call_ai_task4_records_retry_countdown(self, mock_call_ai_service):
        mock_call_ai_service.side_effect = Exception("429 rate limit")

        with self.assertRaises(Retry):
            call_ai_task4.apply(
                args=[
                    "限流重试测试",
                    self.user.id,
                    "deepseek",
                    "test-countdown-conversation",
                    None,
                    {},
                    "test-countdown-trace",
                ],
                retries=0,
                throw=True,
            )

        retry_step = AiTraceStepLog.objects.filter(
            user=self.user,
            trace_id="test-countdown-trace",
            step="task_retry",
        ).first()

        self.assertIsNotNone(retry_step)
        self.assertEqual(retry_step.detail["countdown"], 10)
        

# 测@throttle_classes([AICallThrottle])
# 在当前测试类里临时把限流改成 2/minute
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "test-throttle-cache",
        }
    },
    REST_FRAMEWORK={
        "DEFAULT_THROTTLE_RATES": {
            "ai_call": "2/minute",
            "user": "100/minute",
            "anon": "100/minute",
        },
    }
)
class AICallThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        # 强行把 AICallThrottle 的限流表改成 2/minute。
        self.old_throttle_rates = AICallThrottle.THROTTLE_RATES
        AICallThrottle.THROTTLE_RATES = {
            "ai_call": "2/minute",
            "user": "100/minute",
            "anon": "100/minute",
        }

        self.user = User.objects.create_user(
            username="throttle_user",
            password="123456"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        AICallThrottle.THROTTLE_RATES = self.old_throttle_rates
        cache.clear()

    @patch("ai_log.views.call_ai_task4.delay")
    def test_call_company_ai4_is_throttled(self, mock_delay):
        mock_delay.return_value.id = "test-task-id"

        response1 = self.client.post("/api/logs/call_company_ai4/", {
            "prompt": "第一次请求",
            "model": "deepseek",
        }, format="json")

        response2 = self.client.post("/api/logs/call_company_ai4/", {
            "prompt": "第二次请求",
            "model": "deepseek",
        }, format="json")

        response3 = self.client.post("/api/logs/call_company_ai4/", {
            "prompt": "第三次请求",
            "model": "deepseek",
        }, format="json")

        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response3.status_code, 429)
        self.assertEqual(mock_delay.call_count, 2)

class AICallIdempotentTests(TestCase):
    def setUp(self):
        cache.clear()

        self.user = User.objects.create_user(
            username="idempotent_user",
            password="123456"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        cache.clear()

    @patch("ai_log.views.call_ai_task4.delay")
    def test_call_company_ai4_reuses_task_when_request_id_repeated(self, mock_delay):
        class FakeTask:
            id = "same-task-id-001"

        mock_delay.return_value = FakeTask()

        payload = {
            "prompt": "测试幂等请求",
            "model": "deepseek",
            "conversation_id": "test-idempotent-conversation",
            "request_id": "request-001",
        }

        response1 = self.client.post(
            "/api/logs/call_company_ai4/",
            payload,
            format="json"
        )

        response2 = self.client.post(
            "/api/logs/call_company_ai4/",
            payload,
            format="json"
        )

        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response2.status_code, 200)

        self.assertEqual(response1.data["data"]["task_id"], "same-task-id-001")
        self.assertEqual(response2.data["data"]["task_id"], "same-task-id-001")

        self.assertFalse(response1.data["data"].get("idempotent", False))
        self.assertTrue(response2.data["data"]["idempotent"])

        self.assertEqual(mock_delay.call_count, 1)

        step = AiTraceStepLog.objects.filter(
            user=self.user,
            conversation_id="test-idempotent-conversation",
            step="idempotent_hit",
        ).first()

        self.assertIsNotNone(step)
        self.assertEqual(step.detail["request_id"], "request-001")
        self.assertEqual(step.detail["task_id"], "same-task-id-001")

    # 不同 request_id 不应该复用任务。
    @patch("ai_log.views.call_ai_task4.delay")
    def test_call_company_ai4_creates_new_task_when_request_id_different(self, mock_delay):
        class FakeTask1:
            id = "task-id-001"

        class FakeTask2:
            id = "task-id-002"

        mock_delay.side_effect = [FakeTask1(), FakeTask2()]

        response1 = self.client.post("/api/logs/call_company_ai4/", {
            "prompt": "第一次请求",
            "model": "deepseek",
            "conversation_id": "test-idempotent-conversation",
            "request_id": "request-001",
        }, format="json")

        response2 = self.client.post("/api/logs/call_company_ai4/", {
            "prompt": "第二次请求",
            "model": "deepseek",
            "conversation_id": "test-idempotent-conversation",
            "request_id": "request-002",
        }, format="json")

        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response2.status_code, 200)

        self.assertEqual(response1.data["data"]["task_id"], "task-id-001")
        self.assertEqual(response2.data["data"]["task_id"], "task-id-002")

        self.assertEqual(mock_delay.call_count, 2)

    @patch("ai_log.views.call_ai_service")
    def test_rag_ask_reuses_result_when_request_id_repeated(self, mock_call_ai_service):
        mock_call_ai_service.return_value = ({
            "reply": "stream3 通过 conversation_id、Redis 和 DB 实现上下文会话",
            "prompt_tokens": 10,
            "completion_tokens": 8,
            "total_tokens": 18,
            "cost": 0.001,
            "duration": 0.2,
        }, True)

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

        payload = {
            "query": "stream3 是怎么实现上下文会话的？",
            "top_k": 3,
            "model": "deepseek",
            "conversation_id": "test-rag-idempotent-conversation",
            "request_id": "rag-request-001",
        }

        response1 = self.client.post(
            "/api/knowledge-documents/ask/",
            payload,
            format="json"
        )

        response2 = self.client.post(
            "/api/knowledge-documents/ask/",
            payload,
            format="json"
        )

        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response2.status_code, 200)

        self.assertFalse(response1.data["data"]["idempotent"])
        self.assertTrue(response2.data["data"]["idempotent"])

        self.assertEqual(response1.data["data"]["answer"], response2.data["data"]["answer"])
        self.assertEqual(response1.data["data"]["conversation_id"], response2.data["data"]["conversation_id"])

        mock_call_ai_service.assert_called_once()

        hit_step = AiTraceStepLog.objects.filter(
            user=self.user,
            conversation_id="test-rag-idempotent-conversation",
            step="idempotent_hit",
        ).first()

        self.assertIsNotNone(hit_step)
        self.assertEqual(hit_step.detail["request_id"], "rag-request-001")
        self.assertEqual(hit_step.detail["type"], "rag_ask")

    @patch("ai_log.views.call_ai_service")
    def test_rag_ask_creates_new_result_when_request_id_different(self, mock_call_ai_service):
        mock_call_ai_service.side_effect = [
            ({
                "reply": "第一次 RAG 回答",
                "prompt_tokens": 10,
                "completion_tokens": 8,
                "total_tokens": 18,
                "cost": 0.001,
                "duration": 0.2,
            }, True),
            ({
                "reply": "第二次 RAG 回答",
                "prompt_tokens": 11,
                "completion_tokens": 9,
                "total_tokens": 20,
                "cost": 0.002,
                "duration": 0.3,
            }, True),
        ]

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

        response1 = self.client.post("/api/knowledge-documents/ask/", {
            "query": "stream3 是怎么实现上下文会话的？",
            "top_k": 3,
            "model": "deepseek",
            "conversation_id": "test-rag-idempotent-conversation",
            "request_id": "rag-request-001",
        }, format="json")

        response2 = self.client.post("/api/knowledge-documents/ask/", {
            "query": "stream3 是怎么实现上下文会话的？",
            "top_k": 3,
            "model": "deepseek",
            "conversation_id": "test-rag-idempotent-conversation",
            "request_id": "rag-request-002",
        }, format="json")

        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response2.status_code, 200)

        self.assertEqual(response1.data["data"]["answer"], "第一次 RAG 回答")
        self.assertEqual(response2.data["data"]["answer"], "第二次 RAG 回答")

        self.assertFalse(response1.data["data"]["idempotent"])
        self.assertFalse(response2.data["data"]["idempotent"])

        self.assertEqual(mock_call_ai_service.call_count, 2)

    @patch("ai_log.views.call_ai_service")
    def test_rag_ask_does_not_cache_failed_result(self, mock_call_ai_service):
        mock_call_ai_service.side_effect = [
            ({
                "reply": "AI调用失败",
                "duration": 0.1,
            }, False),
            ({
                "reply": "第二次调用成功",
                "prompt_tokens": 5,
                "completion_tokens": 5,
                "total_tokens": 10,
                "cost": 0.001,
                "duration": 0.2,
            }, True),
        ]

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

        payload = {
            "query": "stream3 是怎么实现上下文会话的？",
            "top_k": 3,
            "model": "deepseek",
            "conversation_id": "test-rag-failed-not-cache",
            "request_id": "rag-request-failed-001",
        }

        response1 = self.client.post(
            "/api/knowledge-documents/ask/",
            payload,
            format="json"
        )

        response2 = self.client.post(
            "/api/knowledge-documents/ask/",
            payload,
            format="json"
        )

        self.assertEqual(response1.status_code, 500)
        self.assertEqual(response2.status_code, 200)

        self.assertEqual(response2.data["data"]["answer"], "第二次调用成功")
        self.assertFalse(response2.data["data"]["idempotent"])

        self.assertEqual(mock_call_ai_service.call_count, 2)

class ConcurrencyProtectionTests(TestCase):
    def setUp(self):
        cache.clear()

        self.user = User.objects.create_user(
            username="concurrency_user",
            password="123456"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        cache.clear()

    @patch("ai_log.views.call_ai_task4.delay")
    def test_same_request_id_reuses_one_task_under_repeated_submit(self, mock_delay):
        class FakeTask:
            id = "concurrency-task-001"

        mock_delay.return_value = FakeTask()

        payload = {
            "prompt": "并发重复提交测试",
            "model": "deepseek",
            "conversation_id": "concurrency-conversation-001",
            "request_id": "same-request-id-001",
        }

        responses = [
            self.client.post("/api/logs/call_company_ai4/", payload, format="json")
            for _ in range(20)
        ]
        print([response.status_code for response in responses])

        self.assertTrue(all(response.status_code == 200 for response in responses))
        # 同一个 request_id,连续提交 20 次, 后端只创建 1 个 Celery 任务
        # mock_delay代替了call_ai_task4.delay(...)
        self.assertEqual(mock_delay.call_count, 1)

        task_ids = [
            response.data["data"]["task_id"]
            for response in responses
        ]
        self.assertEqual(set(task_ids), {"concurrency-task-001"})

        idempotent_hits = AiTraceStepLog.objects.filter(
            user=self.user,
            conversation_id="concurrency-conversation-001",
            step="idempotent_hit",
        ).count()

        # 后面 19 次都复用旧 task_id，trace 步骤日志
        # 第一次请求：没有缓存，后续走cache.get
        self.assertEqual(idempotent_hits, 19)

    @patch("ai_log.views.call_ai_task4.delay")
    def test_different_request_id_is_limited_under_repeated_submit(self, mock_delay):
        class FakeTask:
            def __init__(self, task_id):
                self.id = task_id

        mock_delay.side_effect = [
            FakeTask(f"concurrency-task-{index}")
            for index in range(20)
        ]

        responses = [
            self.client.post("/api/logs/call_company_ai4/", {
                "prompt": f"并发新请求测试 {index}",
                "model": "deepseek",
                "conversation_id": "concurrency-conversation-002",
                "request_id": f"different-request-id-{index}",
            }, format="json")
            for index in range(20)
        ]

        status_codes = [response.status_code for response in responses]

        self.assertEqual(status_codes.count(200), 10)
        self.assertEqual(status_codes.count(429), 10)
        self.assertEqual(mock_delay.call_count, 10)

    @patch("ai_log.views.AsyncResult")
    def test_same_task_status_query_is_limited_under_repeated_polling(self, mock_async_result):
        task_id = "concurrency-poll-task-001"

        cache.set(f"ai_task_owner:{task_id}", {
            "user_id": self.user.id,
            "conversation_id": "concurrency-conversation-003",
            "trace_id": "concurrency-trace-003",
        }, timeout=3600)

        mock_task = mock_async_result.return_value
        mock_task.state = "PENDING"
        mock_task.result = None

        responses = [
            self.client.get(f"/api/logs/task/{task_id}/")
            for _ in range(130)
        ]

        status_codes = [response.status_code for response in responses]

        self.assertEqual(status_codes.count(200), 120)
        self.assertEqual(status_codes.count(429), 10)
        # 因为"task_status": "120/minute"
        self.assertEqual(mock_async_result.call_count, 120)

    @patch("ai_log.views.AsyncResult")
    def test_trace_detail_still_available_when_task_owner_cache_missing(self, mock_async_result):
        trace_id = "concurrency-trace-recover-001"

        AiTraceStepLog.objects.create(
            user=self.user,
            trace_id=trace_id,
            conversation_id="concurrency-conversation-recover",
            step="enqueue_task",
            query="恢复机制测试",
            detail={
                "task_id": "expired-task-id-001",
            },
            success=True,
        )

        response = self.client.get("/api/logs/task/expired-task-id-001/")
        self.assertEqual(response.status_code, 404)
        mock_async_result.assert_not_called()

        trace_response = self.client.get(f"/api/logs/trace/{trace_id}/")
        self.assertEqual(trace_response.status_code, 200)
        self.assertEqual(trace_response.data["data"]["trace_id"], trace_id)
        self.assertEqual(trace_response.data["data"]["summary"]["step_count"], 1)

    @unittest.skip("真实 HTTP 并发行为用 scripts/light_load_test.py 验证，Django TestCase 多线程 client 不稳定")
    @patch("ai_log.views.call_ai_task4.delay")
    def test_same_request_id_reuses_one_task_under_parallel_submit(self, mock_delay):
        import time
        from concurrent.futures import ThreadPoolExecutor, as_completed

        class FakeTask:
            id = "parallel-task-001"

        def slow_delay(*args, **kwargs):
            time.sleep(0.2)
            return FakeTask()

        mock_delay.side_effect = slow_delay

        payload = {
            "prompt": "并发同时提交测试",
            "model": "deepseek",
            "conversation_id": "parallel-conversation-001",
            "request_id": "parallel-request-id-001",
        }

        def submit_once():
            client = APIClient()
            client.force_authenticate(user=self.user)
            return client.post(
                "/api/logs/call_company_ai4/",
                payload,
                format="json"
            )

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(submit_once)
                for _ in range(20)
            ]
            responses = [
                future.result()
                for future in as_completed(futures)
            ]

        status_codes = [response.status_code for response in responses]
        task_ids = [
            response.data["data"].get("task_id")
            for response in responses
            if response.status_code == 200
        ]

        status_codes = [response.status_code for response in responses]

        print("parallel submit status_codes:", status_codes)
        print("parallel submit bodies:", [
            getattr(response, "data", None)
            for response in responses[:5]
        ])
        print("mock_delay.call_count:", mock_delay.call_count)

        self.assertEqual(status_codes.count(200), 20, status_codes)
        self.assertEqual(mock_delay.call_count, 1)
        self.assertEqual(set(task_ids), {"parallel-task-001"})

    @patch("ai_log.views.AsyncResult")
    def test_task_status_query_is_strictly_limited_under_parallel_polling(self, mock_async_result):
        from concurrent.futures import ThreadPoolExecutor, as_completed

        task_id = "parallel-poll-task-001"

        cache.set(f"ai_task_owner:{task_id}", {
            "user_id": self.user.id,
            "conversation_id": "parallel-poll-conversation-001",
            "trace_id": "parallel-poll-trace-001",
        }, timeout=3600)

        mock_task = mock_async_result.return_value
        mock_task.state = "PENDING"
        mock_task.result = None

        def poll_once():
            return self.client.get(f"/api/logs/task/{task_id}/")

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [
                executor.submit(poll_once)
                for _ in range(130)
            ]
            responses = [
                future.result()
                for future in as_completed(futures)
            ]

        status_codes = [response.status_code for response in responses]

        self.assertEqual(status_codes.count(200), 120)
        self.assertEqual(status_codes.count(429), 10)
        self.assertEqual(mock_async_result.call_count, 120)

@override_settings(
    CACHES={
        "default":{
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "test-task-status-throttle-cache",
        }
    },
    REST_FRAMEWORK={
        "EXCEPTION_HANDLER": "ai_log.exceptions.custom_exception_handler",
        "DEFAULT_THROTTLE_RATES": {
            "task_status": "2/minute",
            "ai_call": "100/minute",
            "user": "100/minute",
            "anon": "100/minute",
        },
    }
)
class TaskStatusThrottleTestCase(TestCase):
    def setUp(self):
        cache.clear()
        # THROTTLE_RATES继承自DRF
        self.old_throttle_rates = TaskStatusThrottle.THROTTLE_RATES
        TaskStatusThrottle.THROTTLE_RATES = {
            "task_status": "2/minute",
            "ai_call": "100/minute",
            "user": "100/minute",
            "anon": "100/minute", 
        }

        self.user = User.objects.create_user(
            username="task_status_user",
            password="123456"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    # 重写方法 setup -> 测试1 -> tearDown  setup -> 测试2 -> tearDown
    # 每一个 test 方法执行前都会跑一次 setUp，执行后都会跑一次 tearDown。
    def tearDown(self):
        # 将当前测试类跑完后把限流配置恢复原来的样子
        # 旧配置
        TaskStatusThrottle.THROTTLE_RATES = self.old_throttle_rates
        cache.clear()

    @patch("ai_log.views.AsyncResult")
    def test_task_status_is_throttled(self, mock_async_result):
        # 让这个假任务一直处于排队中
        mock_task = mock_async_result.return_value
        mock_task.state = "PENDING"
        mock_task.result = None

        cache.set("ai_task_owner:test-task-id", {
            "user_id": self.user.id,
            "conversation_id": "conversation-throttle",
            "trace_id": "trace-throttle",
        }, timeout=3600)

        response1 = self.client.get("/api/logs/task/test-task-id/")
        response2 = self.client.get("/api/logs/task/test-task-id/")
        response3 = self.client.get("/api/logs/task/test-task-id/")

        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response3.status_code, 429)

        self.assertEqual(mock_async_result.call_count, 2)

    @patch("ai_log.views.AsyncResult")
    def test_task_status_throttle_response_format(self, mock_async_result):
        task_id = "throttle-format-task-id"

        cache.set(f"ai_task_owner:{task_id}", {
            "user_id": self.user.id,
            "conversation_id": "throttle-format-conversation",
            "trace_id": "throttle-format-trace",
        }, timeout=300)

        mock_task = mock_async_result.return_value
        mock_task.state = "PENDING"
        mock_task.result = None

        response1 = self.client.get(f"/api/logs/task/{task_id}/")
        response2 = self.client.get(f"/api/logs/task/{task_id}/")
        response3 = self.client.get(f"/api/logs/task/{task_id}/")

        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response3.status_code, 429)

        self.assertEqual(response3.data["code"], 429)
        self.assertIn("请求过于频繁", response3.data["message"])
        self.assertIn("wait", response3.data["data"])

class TaskStatusResultTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="task_result_user",
            password="123456"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch("ai_log.views.AsyncResult")
    def test_task_status_pending(self, mock_async_result):
        mock_task = mock_async_result.return_value
        mock_task.state = "PENDING"
        mock_task.result = None

        cache.set("ai_task_owner:task-pending-id", {
            "user_id": self.user.id,
            "conversation_id": "conversation-pending",
            "trace_id": "trace-pending",
        }, timeout=3600)

        response = self.client.get("/api/logs/task/task-pending-id/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], "processing")
        self.assertEqual(response.data["data"]["status_text"], "排队中")
        self.assertEqual(response.data["data"]["result"], None)
        self.assertEqual(response.data["data"]["error"], "")

    # 把超时时间临时改成 1 分钟；
    @override_settings(AI_TASK_TIMEOUT_MINUTES=1)
    @patch("ai_log.views.AsyncResult")
    def test_task_status_pending_timeout_uses_settings_value(self, mock_async_result):
        mock_task = mock_async_result.return_value
        mock_task.state = "PENDING"
        mock_task.result = None

        trace_id = "task-timeout-settings-trace-001"

        cache.set("ai_task_owner:task-timeout-settings-id", {
            "user_id": self.user.id,
            "conversation_id": "conversation-timeout-settings",
            "trace_id": trace_id,
        }, timeout=3600)

        start_step = AiTraceStepLog.objects.create(
            user=self.user,
            trace_id=trace_id,
            conversation_id="conversation-timeout-settings",
            step="task_start",
            query="配置超时测试",
        )
        start_step.created_at = timezone.now() - timedelta(minutes=2)
        start_step.save(update_fields=["created_at"])

        response = self.client.get("/api/logs/task/task-timeout-settings-id/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], "failed")
        self.assertEqual(response.data["data"]["status_text"], "任务超时")

        timeout_step = AiTraceStepLog.objects.get(
            trace_id=trace_id,
            step="task_timeout",
        )

        self.assertEqual(timeout_step.detail["timeout_minutes"], 1)

    @patch("ai_log.views.AsyncResult")
    def test_task_status_pending_timeout(self, mock_async_result):
        mock_task = mock_async_result.return_value
        mock_task.state = "PENDING"
        mock_task.result = None

        trace_id = "task-timeout-trace-001"

        cache.set("ai_task_owner:task-timeout-id", {
            "user_id": self.user.id,
            "conversation_id": "conversation-timeout",
            "trace_id": trace_id,
        }, timeout=3600)

        start_step = AiTraceStepLog.objects.create(
            user=self.user,
            trace_id=trace_id,
            conversation_id="conversation-timeout",
            step="task_start",
            query="超时测试问题",
        )

        start_step.created_at = timezone.now() - timedelta(minutes=10)
        start_step.save(update_fields=["created_at"])

        response = self.client.get("/api/logs/task/task-timeout-id/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], "failed")
        self.assertEqual(response.data["data"]["status_text"], "任务超时")
        self.assertIn("任务超过", response.data["data"]["error"])

        timeout_step = AiTraceStepLog.objects.filter(
            trace_id=trace_id,
            step="task_timeout",
        ).first()

        self.assertIsNotNone(timeout_step)
        self.assertFalse(timeout_step.success)
        self.assertEqual(timeout_step.detail["task_id"], "task-timeout-id")

    @patch("ai_log.views.AsyncResult")
    def test_task_status_pending_timeout_only_records_once(self, mock_async_result):
        mock_task = mock_async_result.return_value
        mock_task.state = "PENDING"
        mock_task.result = None

        trace_id = "task-timeout-once-trace-001"

        cache.set("ai_task_owner:task-timeout-once-id", {
            "user_id": self.user.id,
            "conversation_id": "conversation-timeout-once",
            "trace_id": trace_id,
        }, timeout=3600)

        start_step = AiTraceStepLog.objects.create(
            user=self.user,
            trace_id=trace_id,
            conversation_id="conversation-timeout-once",
            step="task_start",
            query="超时只记录一次测试",
        )
        start_step.created_at = timezone.now() - timedelta(minutes=10)
        start_step.save(update_fields=["created_at"])

        self.client.get("/api/logs/task/task-timeout-once-id/")
        self.client.get("/api/logs/task/task-timeout-once-id/")

        timeout_count = AiTraceStepLog.objects.filter(
            trace_id=trace_id,
            step="task_timeout",
        ).count()

        self.assertEqual(timeout_count, 1)

    @patch("ai_log.views.AsyncResult")
    def test_task_status_success_with_result(self, mock_async_result):
        mock_task = mock_async_result.return_value
        mock_task.state = "SUCCESS"
        mock_task.result = {
            "status": "success",
            "response": "AI 回答内容",
            "conversation_id": "task-conversation-001",
            "trace_id": "task-trace-001",
            "total_tokens": 20,
            "cost": 0.002,
        }

        cache.set("ai_task_owner:task-success-id", {
            "user_id": self.user.id,
            "conversation_id": "task-conversation-001",
            "trace_id": "task-trace-001",
        }, timeout=3600)

        response = self.client.get("/api/logs/task/task-success-id/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], "success")
        self.assertEqual(response.data["data"]["status_text"], "处理成功")
        self.assertEqual(response.data["data"]["trace_id"], "task-trace-001")
        self.assertEqual(response.data["data"]["result"]["response"], "AI 回答内容")
        self.assertEqual(response.data["data"]["result"]["conversation_id"], "task-conversation-001")
        self.assertEqual(response.data["data"]["result"]["total_tokens"], 20)
        self.assertEqual(response.data["data"]["result"]["cost"], 0.002)

    @patch("ai_log.views.AsyncResult")
    def test_task_status_success_with_error_result(self, mock_async_result):
        mock_task = mock_async_result.return_value
        mock_task.state = "SUCCESS"
        mock_task.result = {
            "status": "error",
            "message": "AI 调用失败",
            "trace_id": "task-trace-error",
        }

        cache.set("ai_task_owner:task-error-id", {
            "user_id": self.user.id,
            "conversation_id": "conversation-error",
            "trace_id": "task-trace-error",
        }, timeout=3600)

        response = self.client.get("/api/logs/task/task-error-id/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], "failed")
        self.assertEqual(response.data["data"]["status_text"], "处理失败")
        self.assertEqual(response.data["data"]["trace_id"], "task-trace-error")
        self.assertEqual(response.data["data"]["error"], "AI 调用失败")

    @patch("ai_log.views.AsyncResult")
    def test_task_status_failure(self, mock_async_result):
        mock_task = mock_async_result.return_value
        mock_task.state = "FAILURE"
        mock_task.result = Exception("Celery 任务异常")

        cache.set("ai_task_owner:task-failure-id", {
            "user_id": self.user.id,
            "conversation_id": "conversation-failure",
            "trace_id": "trace-failure",
        }, timeout=3600)

        response = self.client.get("/api/logs/task/task-failure-id/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], "failed")
        self.assertEqual(response.data["data"]["status_text"], "任务异常")
        self.assertIn("Celery 任务异常", response.data["data"]["error"])

    @patch("ai_log.views.AsyncResult")
    def test_task_status_unknown(self, mock_async_result):
        mock_task = mock_async_result.return_value
        mock_task.state = "SOME_UNKNOWN_STATUS"
        mock_task.result = None

        cache.set("ai_task_owner:task-unknown-id", {
            "user_id": self.user.id,
            "conversation_id": "conversation-unknown",
            "trace_id": "trace-unknown",
        }, timeout=3600)

        response = self.client.get("/api/logs/task/task-unknown-id/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], "unknown")
        self.assertEqual(response.data["data"]["status_text"], "未知状态")
        self.assertEqual(response.data["data"]["result"], None) 

    def test_task_status_recovers_success_result_when_owner_cache_missing(self):
        AICallLog.objects.create(
            user=self.user,
            task_id="recovered-success-task-id",
            trace_id="recovered-success-trace",
            conversation_id="recovered-success-conversation",
            prompt="恢复成功测试",
            response="这是数据库恢复出来的回答",
            success=True,
            model_name="deepseek",
            total_tokens=12,
            cost=0.001,
        )

        response = self.client.get("/api/logs/task/recovered-success-task-id/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["celery_status"], "RECOVERED")
        self.assertEqual(response.data["data"]["status"], "success")
        self.assertEqual(response.data["data"]["result"]["response"], "这是数据库恢复出来的回答")
        self.assertEqual(response.data["data"]["trace_id"], "recovered-success-trace")

    def test_task_status_recovers_failed_result_when_owner_cache_missing(self):
        AICallLog.objects.create(
            user=self.user,
            task_id="recovered-failed-task-id",
            trace_id="recovered-failed-trace",
            conversation_id="recovered-failed-conversation",
            prompt="恢复失败测试",
            response="AI任务执行超时",
            success=False,
            model_name="deepseek",
        )

        response = self.client.get("/api/logs/task/recovered-failed-task-id/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["celery_status"], "RECOVERED")
        self.assertEqual(response.data["data"]["status"], "failed")
        self.assertEqual(response.data["data"]["error"], "AI任务执行超时")
        self.assertEqual(response.data["data"]["trace_id"], "recovered-failed-trace")

    def test_task_status_recovered_result_still_checks_owner(self):
        other_user = User.objects.create_user(
            username="task_result_other_user",
            password="123456",
        )

        AICallLog.objects.create(
            user=other_user,
            task_id="other-user-task-id",
            trace_id="other-user-trace",
            conversation_id="other-user-conversation",
            prompt="别人的任务",
            response="别人的回答",
            success=True,
            model_name="deepseek",
        )

        response = self.client.get("/api/logs/task/other-user-task-id/")

        self.assertEqual(response.status_code, 404)

    def test_task_status_recovered_result_allows_superuser(self):
        other_user = User.objects.create_user(
            username="task_result_owner_user",
            password="123456",
        )

        admin_user = User.objects.create_superuser(
            username="task_result_admin",
            password="123456",
            email="admin@example.com",
        )

        AICallLog.objects.create(
            user=other_user,
            task_id="admin-recovered-task-id",
            trace_id="admin-recovered-trace",
            conversation_id="admin-recovered-conversation",
            prompt="管理员恢复查询测试",
            response="管理员可以看到的回答",
            success=True,
            model_name="deepseek",
            total_tokens=18,
            cost=0.002,
        )

        self.client.force_authenticate(user=admin_user)

        response = self.client.get("/api/logs/task/admin-recovered-task-id/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["celery_status"], "RECOVERED")
        self.assertEqual(response.data["data"]["status"], "success")
        self.assertEqual(response.data["data"]["trace_id"], "admin-recovered-trace")
        self.assertEqual(response.data["data"]["result"]["response"], "管理员可以看到的回答")

    def test_task_status_recovered_result_restores_owner_cache(self):
        AICallLog.objects.create(
            user=self.user,
            task_id="restore-owner-cache-task-id",
            trace_id="restore-owner-cache-trace",
            conversation_id="restore-owner-cache-conversation",
            prompt="恢复缓存测试",
            response="恢复缓存回答",
            success=True,
            model_name="deepseek",
        )

        response = self.client.get("/api/logs/task/restore-owner-cache-task-id/")

        self.assertEqual(response.status_code, 200)

        task_owner = cache.get("ai_task_owner:restore-owner-cache-task-id")

        self.assertIsNotNone(task_owner)
        self.assertEqual(task_owner["user_id"], self.user.id)
        self.assertEqual(task_owner["conversation_id"], "restore-owner-cache-conversation")
        self.assertEqual(task_owner["trace_id"], "restore-owner-cache-trace")

    def test_task_status_recovered_result_creates_trace_step(self):
        AICallLog.objects.create(
            user=self.user,
            task_id="trace-recovered-task-id",
            trace_id="trace-recovered-trace",
            conversation_id="trace-recovered-conversation",
            prompt="恢复 trace 测试",
            response="恢复 trace 回答",
            success=True,
            model_name="deepseek",
        )

        response = self.client.get("/api/logs/task/trace-recovered-task-id/")

        self.assertEqual(response.status_code, 200)

        recovered_step = AiTraceStepLog.objects.filter(
            trace_id="trace-recovered-trace",
            step="task_recovered",
        ).first()

        self.assertIsNotNone(recovered_step)
        self.assertTrue(recovered_step.success)
        self.assertEqual(recovered_step.detail["task_id"], "trace-recovered-task-id")
        self.assertEqual(recovered_step.detail["source"], "AICallLog")
        self.assertTrue(recovered_step.detail["restored_owner_cache"])

    def test_task_status_recovered_result_creates_trace_step_once(self):
        AICallLog.objects.create(
            user=self.user,
            task_id="trace-recovered-once-task-id",
            trace_id="trace-recovered-once-trace",
            conversation_id="trace-recovered-once-conversation",
            prompt="恢复 trace 只记录一次测试",
            response="恢复 trace 回答",
            success=True,
            model_name="deepseek",
        )

        self.client.get("/api/logs/task/trace-recovered-once-task-id/")

        cache.delete("ai_task_owner:trace-recovered-once-task-id")

        self.client.get("/api/logs/task/trace-recovered-once-task-id/")

        recovered_count = AiTraceStepLog.objects.filter(
            trace_id="trace-recovered-once-trace",
            step="task_recovered",
        ).count()

        self.assertEqual(recovered_count, 1)

    @override_settings(AI_TASK_RECOVERED_OWNER_CACHE_SECONDS=123)
    @patch("ai_log.views.cache.set")
    def test_task_status_recovered_result_uses_recovered_cache_timeout(self, mock_cache_set):
        AICallLog.objects.create(
            user=self.user,
            task_id="recovered-cache-timeout-task-id",
            trace_id="recovered-cache-timeout-trace",
            conversation_id="recovered-cache-timeout-conversation",
            prompt="恢复缓存时间测试",
            response="恢复缓存时间回答",
            success=True,
            model_name="deepseek",
        )

        response = self.client.get("/api/logs/task/recovered-cache-timeout-task-id/")

        self.assertEqual(response.status_code, 200)

        mock_cache_set.assert_called_with(
            "ai_task_owner:recovered-cache-timeout-task-id",
            {
                "user_id": self.user.id,
                "conversation_id": "recovered-cache-timeout-conversation",
                "trace_id": "recovered-cache-timeout-trace",
            },
            timeout=123,
        )

class TaskStatusPermissionTests(TestCase):
    def setUp(self):
        cache.clear()

        self.user = User.objects.create_user(
            username="task_owner_user",
            password="123456"
        )
        self.other_user = User.objects.create_user(
            username="task_other_user",
            password="123456"
        )
        self.admin_user = User.objects.create_superuser(
            username="task_admin_user",
            password="123456",
            email="admin@example.com"
        )

        self.client = APIClient()

    def tearDown(self):
        cache.clear()

    @patch("ai_log.views.AsyncResult")
    def test_user_can_query_own_task(self, mock_async_result):
        cache.set("ai_task_owner:task-own-001", {
            "user_id": self.user.id,
            "conversation_id": "conversation-own-001",
            "trace_id": "trace-own-001",
        }, timeout=3600)

        mock_task = mock_async_result.return_value
        mock_task.state = "PENDING"
        mock_task.result = None

        self.client.force_authenticate(user=self.user)

        response = self.client.get("/api/logs/task/task-own-001/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["task_id"], "task-own-001")
        mock_async_result.assert_called_once_with("task-own-001")

    @patch("ai_log.views.AsyncResult")
    def test_user_cannot_query_other_users_task(self, mock_async_result):
        cache.set("ai_task_owner:task-other-001", {
            "user_id": self.other_user.id,
            "conversation_id": "conversation-other-001",
            "trace_id": "trace-other-001",
        }, timeout=3600)

        self.client.force_authenticate(user=self.user)

        response = self.client.get("/api/logs/task/task-other-001/")

        self.assertEqual(response.status_code, 404)
        mock_async_result.assert_not_called()

    @patch("ai_log.views.AsyncResult")
    def test_admin_can_query_any_task(self, mock_async_result):
        cache.set("ai_task_owner:task-admin-001", {
            "user_id": self.other_user.id,
            "conversation_id": "conversation-admin-001",
            "trace_id": "trace-admin-001",
        }, timeout=3600)

        mock_task = mock_async_result.return_value
        mock_task.state = "PENDING"
        mock_task.result = None

        self.client.force_authenticate(user=self.admin_user)

        response = self.client.get("/api/logs/task/task-admin-001/")

        self.assertEqual(response.status_code, 200)
        mock_async_result.assert_called_once_with("task-admin-001")

    @patch("ai_log.views.AsyncResult")
    def test_task_status_returns_404_when_owner_cache_missing(self, mock_async_result):
        self.client.force_authenticate(user=self.user)

        response = self.client.get("/api/logs/task/missing-task-id/")

        self.assertEqual(response.status_code, 404)
        mock_async_result.assert_not_called()