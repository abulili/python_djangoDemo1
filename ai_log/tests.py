from django.test import TestCase

# Create your tests here. 写自动化测试 自动模拟请求、检查结果
# python manage.py test ai_log

from django.contrib.auth.models import User
from rest_framework.test import APIClient

from .models import KnowledgeChunk, KnowledgeDocument
from .views import split_text_to_chunks, simple_keyword_score
from .services import calculate_cost

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

