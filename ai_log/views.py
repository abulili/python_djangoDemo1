from django.shortcuts import render
import requests
# Create your views here. 处理请求的函数，比如查询数据库、调用AI（业务逻辑）

from django.http import JsonResponse

from rest_framework import viewsets
from ai_log.models import AICallLog, PromptTemplate
from .serializers import AICallLogSerializer, PromptTemplateSerializer

from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView

import time
from openai import OpenAI

# import os
# from dotenv import load_dotenv
# # 加载 .env 文件
# load_dotenv()
from django.conf import settings

# ai_log/views.py
from .utils import success_response, error_response  # 导入工具函数

import logging
logger = logging.getLogger(__name__)

from django.db.models import Count, Sum, Avg, Max, Q
from django.utils import timezone
from datetime import datetime, timedelta

from django.http import StreamingHttpResponse
import json

from rest_framework.permissions import IsAuthenticated

from rest_framework.exceptions import PermissionDenied

from rest_framework.decorators import throttle_classes
from .throttles import AICallThrottle

from django.core.cache import cache

from .tasks import call_ai_task,call_ai_task2, call_ai_task4
from celery.result import AsyncResult

from django.db import connections
from django.db.utils import OperationalError

from django.db.models.functions import TruncDate # 把 call_time 截成日期

import uuid

from .models import AICallLog, PromptTemplate, Conversation, ConversationMessage, KnowledgeChunk, KnowledgeDocument
from .serializers import KnowledgeDocumentSerializer, KnowledgeChunkSerializer

from .services import (
    get_coversation_history,
    save_conversation_history,
    save_conversation_messages_to_db,
    calculate_cost,
    call_ai_service
)

import re

# 你想要一个完全自定义的接口，不遵循标准的 CRUD 模式
# 一个class只能一个post，定义什么请求就是什么，但是可以有很多不同功能的class
class MyCustomAPIView(APIView):
    """自定义APIView示例"""
    def get(self, request):
        data = {
            "message": "这是自定义APIViewGet请求",
            "total_logs": AICallLog.objects.count(),
        }
        return Response(data, status=status.HTTP_200_OK)
    
    def post(self, request):
        # 从请求里拿数据
        user_input = request.data.get("input", "")
        # 处理业务逻辑
        result = f"你输入了：{user_input}"

        return Response({
            "message":"这是自定义APIView的POST请求",
            "input": user_input,
            "result": result
        }, status=status.HTTP_201_CREATED)

# 这个就生成了5个接口 增删改查（查全部查单条）
# 需要对某个 Model 做标准的增删改查
class PromptTemplateViewSet(viewsets.ModelViewSet):
    """Prompt template management."""
    queryset = PromptTemplate.objects.all()
    serializer_class = PromptTemplateSerializer
    pagination_class = None

    # 方法重写
    def get_queryset(self):
        queryset = PromptTemplate.objects.all()
        keyword = self.request.query_params.get('keyword')
        is_active = self.request.query_params.get('is_active')
        if keyword:
            queryset = queryset.filter(name__icontains=keyword) # 名称__在其中（张 可能搜出 张三）
        if is_active in ['true', 'false']:
            queryset = queryset.filter(is_active=is_active == 'true') # 主要针对特殊的情况，比如说None
        return queryset

    # 预览模板渲染结果 
    @action(detail=True, methods=['post'], url_path='preview')
    def preview(self, request, pk=None):
        template = self.get_object()
        variables = request.data.get('variables') or {}
        try:
            content = template.content.format(**variables) # variables解包以后填充content里面的变量
        except KeyError as e: # 字典dict中不存在的键 {'name':'张三'}
            return error_response(f"缺少模板变量: {e.args[0]}", code=400)
        except Exception as e:
            return error_response(f"模板渲染失败: {str(e)}", code=400)
        return success_response({
            'template_id': template.id,
            'content': content,
        })

"""
RAG 质量决定因素
文档质量
-> 切片质量
-> 分词/关键词提取质量
-> 向量化质量
-> 检索排序质量
-> prompt 组织质量
-> 最后回答模型质量
"""

def split_text_to_chunks(text, chunk_size=500, overlap=100):
    """
    把长文本切成多个 chunk。
    第一版用固定长度 + overlap
    """
    text = (text or "").strip()
    chunks = []

    if not text:
        return chunks

    start = 0
    text_length = len(text)

    while start < text_length:
        end = start + chunk_size
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)
        if end >= text_length:
            break

        start = end - overlap

    return chunks

# 分词
def extract_keywords(query):
    """
    简单关键词提取：
    1. 提取英文、数字、下划线组合，比如 stream3、conversation_id
    2. 提取连续中文词
    3. 过滤太短和无意义的词
    """
    query = (query or "").strip().lower()

    if not query:
        return []

    # 提取英文/数字/下划线/连续中文
    words = re.findall(r'[a-zA-Z0-9_]+|[\u4e00-\u9fff]+', query)

    stop_words = {
        "的", "了", "是", "在", "和", "与", "及", "怎么", "如何",
        "什么", "为什么", "实现", "一下", "一个"
    }

    keywords = []

    for word in words:
        if word in stop_words:
            continue

        # 英文、数字、下划线保留，比如 stream3 / conversation_id
        if re.match(r'^[a-zA-Z0-9_]+$', word):
            keywords.append(word)
            continue

        # 简单拆分中文短剧
        if len(word) <= 2:
            keywords.append(word)
        else:
            # 先保留整段
            keywords.append(word)

            # 再按常见技术词补充
            common_terms = [
                "上下文", "会话", "流式", "接口", "缓存", "历史",
                "用户", "模型", "日志", "切片", "知识库", "检索",
                "向量", "模板", "刷新", "登录", "鉴权"
            ]

            for term in common_terms:
                if term in word:
                    keywords.append(term)

    # 去重+保持顺序
    result = []
    for word in keywords:
        if word and word not in result:
            result.append(word)

    return result    


def simple_keyword_score(query, text):
    """
    第一版关键词打分
    query中关键词在chunk中出现得越多，分数越高，目前简单匹配字词
    """
    query = (query or "").strip().lower()
    text = (text or "").strip().lower()

    if not query or not text:
        return 0
    
    keywords = extract_keywords(query)

    score = 0
    for keyword in keywords:
        if keyword in text:
            score += text.count(keyword)
    
    return score


class KnowledgeDocumentViewSet(viewsets.ModelViewSet):
    """知识库文档管理"""
    serializer_class = KnowledgeDocumentSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return KnowledgeDocument.objects.all()
        return KnowledgeDocument.objects.filter(user=user)

    def perform_create(self, serializer):
        document = serializer.save(user=self.request.user)
        chunks = split_text_to_chunks(document.content)
        # bulk_create = 一次性批量创建 chunks，比循环 create 更省数据库操作
        KnowledgeChunk.objects.bulk_create([
             KnowledgeChunk(
                document=document,
                content=chunk,
                chunk_index=index,
            )
            for index, chunk in enumerate(chunks)
        ])

    def perform_update(self, serializer):
        document = serializer.save()

        document.chunks.all().delete()

        chunks = split_text_to_chunks(document.content)

        KnowledgeChunk.objects.bulk_create([
            KnowledgeChunk(document=document, content=chunk, chunk_index=index)
            for index, chunk in enumerate(chunks)
        ])

    @action(detail=False, methods=['post'], url_path='search')
    def search(self, request):
        """
        有点像搜索框补全关键词，但是不是完全一样
        1. 前缀匹配：输入 tok，找 token、token refresh
        2. 包含匹配：输入 fresh，找 token refresh
        3. 拼音匹配：输入 dl，找 登录
        4. 历史热词：用户经常搜什么，就优先推荐什么
        5. 语义联想：用 embedding 找意思相近的词
        """

        query = request.data.get('query', '')
        top_k = int(request.data.get('top_k', 3)) # 没传默认取3条内容返回

        if not query.strip():
            return error_response('请提供query',400)

        
        """
        数据量超级大的时候可优化
        1. 数据库关键词过滤先缩小范围
        2. 给 content 加全文索引，MySQL / PostgreSQL 都有全文检索能力。
        3. 接 embedding + 向量库，这是 RAG 后续升级方向，比如 FAISS、Milvus、pgvector。
        4. 限制文档范围，比如只搜当前选择的知识库、当前项目文档。
        """
        if request.user.is_superuser:
            # select_related('document')： 提前把 chunk 对应的 document 一起查出来，避免循环里每次 chunk.document.title 都重新查数据库。
            chunks = KnowledgeChunk.objects.select_related('document').all()
        else:
            chunks = KnowledgeChunk.objects.select_related('document').filter(document__user=request.user)

        scored_chunks = []
        for chunk in chunks:
            score = simple_keyword_score(query, chunk.content)
            if score > 0:
                scored_chunks.append({
                    "id": chunk.id,
                    "document_id": chunk.document_id,
                    "document_title": chunk.document.title,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "score": score,
                })

        # key=xxx => key=lambda item: item['score']： 排序时按每一项里面的 score 字段来排, lambda是临时小函数，专门写匿名函数
        # reverse=True： 从大到小排
        scored_chunks.sort(key=lambda item: item['score'], reverse=True)

        return success_response({
            "query": query,
            "top_k": top_k,
            "scored_chunks": scored_chunks[:top_k],
        })

    @action(detail=False, methods=['post'], url_path='ask')
    def ask(self, request):
        query = request.data.get('query', '')
        top_k = int(request.data.get('top_k', 3)) 
        model_key = request.data.get('model', getattr(settings, 'DEFAULT_AI_MODEL', 'deepseek'))

        if not query.strip():
            return error_response('请提供query', code=400)

        if request.user.is_superuser:
            chunks = KnowledgeChunk.objects.select_related('document').all()
        else:
            chunks = KnowledgeChunk.objects.select_related('document').filter(document__user=request.user)

        scored_chunks = []

        for chunk in chunks:
            score = simple_keyword_score(query, chunk.content)
            if score > 0:
                scored_chunks.append({
                    "id": chunk.id,
                    "document_id": chunk.document_id,
                    "document_title": chunk.document.title,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "score": score,
                })
        scored_chunks.sort(key=lambda item: item['score'], reverse=True)
        top_chunks = scored_chunks[:top_k]

        if not top_chunks:
            return success_response({
                "query": query,
                "answer": "知识库中没有检索到相关内容。",
                "references": [],
            })

        context = "\n\n".join([
            f"资料{index + 1}：{item['content']}"
            for index, item in enumerate(top_chunks)
        ])
        
        rag_prompt = f"""
        你是一个知识库问答助手。请严格根据【知识库资料】回答【用户问题】。

        回答规则：
        1. 如果知识库资料中出现了和用户问题相关的内容，请直接总结资料中的答案。
        2. 如果资料只能回答一部分，请先回答能确定的部分，再说明缺少哪些信息。
        3. 只有当资料完全无关时，才回答“知识库资料中没有找到相关信息”。
        4. 不要使用知识库资料以外的信息。

        【知识库资料】
        {context}

        【用户问题】
        {query}
        """

        result, success = call_ai_service(
            prompt=rag_prompt,
            model_key=model_key,
            user=request.user
        )

        if not success:
            AICallLog.objects.create(
                prompt=query,
                response=result.get("reply", "AI调用失败"),
                duration=result.get("duration", 0.0),
                success=False,
                user=request.user,
                model_name=model_key,
                trace_id=getattr(request, "trace_id", ""),
            )
            return error_response(result.get('reply', 'AI调用失败'), code=500)

        AICallLog.objects.create(
            prompt=query,
            response=result.get("reply", ""),
            duration=result.get("duration", 0.0),
            success=True,
            user=request.user,
            model_name=model_key,
            prompt_tokens=result.get("prompt_tokens", 0),
            completion_tokens=result.get("completion_tokens", 0),
            total_tokens=result.get("total_tokens", 0),
            cost=result.get("cost", 0.0),
            trace_id=getattr(request, "trace_id", ""),
        )

        return success_response({
            "query": query,
            "answer": result.get("reply", ""),
            "references": top_chunks,
        })

class AICallLogViewSet(viewsets.ModelViewSet):
    """
    AI调用日志视图集
    提供标准的 CRUD 接口 + 自定义统计和流式接口
    """
    queryset = AICallLog.objects.all() # 查询所有数据
    serializer_class = AICallLogSerializer # 使用哪个序列化器
    # permission_classes = [IsAuthenticated] # 强制token登录

    
    # 
    def call_company_ai(self, prompt):
        """调用AI接口返回回答"""
        AI_URL = "https://api.deepseek.com"
        AI_API_KEY = "xxx"

        headers = {
            'Authorization': f"Bearer {AI_API_KEY}",
            'Content-Type': "application/json"
        }

        data = {
            "model": "deepseek-v4-flash",
            "messages": [{
                "role": "user",
                "content":prompt
            }]
        }

        try: 
            response = requests.post(f"{AI_URL}/chat/completions",headers=headers,json=data,timeout=30)
            response.raise_for_status()  # 如果状态码不是 200，会抛出异常
            # 解析响应（openAI协议格式）
            result = response.json()
            ai_reply = result['choices'][0]['message']['content']
            return ai_reply,True
        except Exception as e:
            return f"AI调用失败{str(e)}",False

    # 引入重试机制
    def call_company_ai2(self, prompt, retries = 3):
        """调用AI接口返回回答"""
        # 用 prompt 作为缓存 key（取前50个字符避免太长）
        cache_key = f"ai_response:{prompt[:50]}"
        
        # 查缓存
        cached_result = cache.get(cache_key)
        if cached_result:
            print(">>>> 命中 Redis 缓存！")
            return cached_result,True
        
        # 缓存里没有，调用AI接口
        logger.info(f"调用 DeepSeek API，prompt: {prompt[:50]}...")
        client = OpenAI(api_key=settings.DEEPSEEK_API_KEY,base_url="https://api.deepseek.com")
        # print(os.getenv("DEEPSEEK_API_KEY"))
        
        for attempt in range(retries):
            try: 
                response = client.chat.completions.create(
                    model="deepseek-v4-flash",
                    messages=[{
                        "role":"user",
                        "content": prompt
                    }],
                    stream=False
                )
                ai_reply = response.choices[0].message.content
                # 缓存结果(1小时过期)
                cache.set(cache_key, ai_reply, timeout=3600)
                print('>>>> 已缓存AI回复')
                logger.info(f"DeepSeek API 调用成功，返回长度: {len(ai_reply)}")
                return ai_reply,True
            except Exception as e:
                # print(f"第{attempt + 1}次AI调用失败{e}")
                # if attempt < retries - 1:
                #     time.sleep(1) # 等待1秒后重试
                # return f"AI调用失败{str(e)}",False
                # 日志里记录完整错误，方便排查
                logger.error(f"第 {attempt + 1} 次调用失败: {e}")  # ← 直接用
                if attempt < retries - 1:
                    time.sleep(1)
                return "AI 服务暂时不可用，请稍后重试", False
    
    # 引入模型选择
    @throttle_classes([AICallThrottle])
    @action(detail=False, methods=['post'],url_path='call_company_ai3')
    def create2(self, request):
        print(">>>> create 被调用了！")
        user_prompt = request.data.get('prompt')
        model_key = request.data.get('model',settings.DEFAULT_AI_MODEL)
        # logger.info(f"用户 {request.user.username} 发起 AI 调用，prompt: {user_prompt[:50]}...")
        if not user_prompt:
            return Response(
                {'error': '请提供prompt字段'},
                status=status.HTTP_400_BAD_REQUEST
            )

        trace_id = getattr(request, "trace_id", "")
         # 把任务丢给 Celery，不等待
        task = call_ai_task2.delay(user_prompt, request.user.id, model_key, trace_id)
        
        # 返回任务ID和状态
        return success_response({
            'task_id': task.id,
            'status': 'processing',
            'message': 'AI 正在处理中，请稍后通过 task_id 查询结果'
        }, message="任务已提交")
    
     # 引入模型选择
    
    @throttle_classes([AICallThrottle])
    @action(detail=False, methods=['post'],url_path='call_company_ai4')
    def create4(self, request):
        print(">>>> create 被调用了！")
        user_prompt = request.data.get('prompt')
        model_key = request.data.get('model',getattr(settings, 'DEFAULT_AI_MODEL', 'deepseek'))
        conversation_id = request.data.get('conversation_id')
        template_name = request.data.get('template_name')
        template_vars = request.data.get('template_vars') or {}
        # logger.info(f"用户 {request.user.username} 发起 AI 调用，prompt: {user_prompt[:50]}...")
        if not user_prompt:
            return Response(
                {'error': '请提供prompt字段'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 如果传了模板，用模板渲染
        if template_name:
            # 用户输入的prompt中作为变量之一
            template_vars['user_input'] = user_prompt

        # 如果没有传conversation_id，生成一个新的
        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        trace_id = getattr(request, "trace_id", "")
        # 把任务丢给 Celery，不等待
        task = call_ai_task4.delay(user_prompt, request.user.id, model_key, conversation_id, template_name, template_vars, trace_id)
        
        # 返回任务ID和状态
        return success_response({
            'task_id': task.id,
            'status': 'processing',
            'message': 'AI 正在处理中，请稍后通过 task_id 查询结果',
            'conversation_id': conversation_id
        }, message="任务已提交")
    


    # 流式sse
    def stream_ai_response(self, prompt):
        """流式调用逐字返回"""
       
        client = OpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )

        try:
            response = client.chat.completions.create(
                model="deepseek-v4-flash",
                messages=[{"role":"user","content": prompt}],
                stream=True
            )
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield f"data:{json.dumps({'content': content})}"
            yield f"data:{json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data:{json.dumps({'error':str(e)})}\n\n"

    # 多用户，重写DRF自动生成的接口
    def get_object(self):
        print(">>> get_object 被调用了！")
        # return super().get_object()
        obj = super().get_object()
        if self.request.user.is_superuser:
            return obj
        if obj.user != self.request.user:
            print(">>> 准备抛出 PermissionDenied！")
            # PermissionDenied drf的异常类，这样才能被识别
            raise PermissionDenied("你没有权限操作这条日志")
            """
            return error_response：主动返回，流程结束
            raise PermissionError：抛出异常，交给异常处理器

                在 get_object 方法里，你不能用 return error_response，
                因为 get_object 的调用方（DRF）期望它返回一个对象，而不是一个响应。
                如果你在 get_object 里返回响应，DRF 会报错。
                所以 get_object 里只能用 raise
            """
        return obj


    @throttle_classes([AICallThrottle])
    @action(detail=False, methods=['post'],url_path='stream')
    def stream_chat(self, request):
        prompt = request.data.get('prompt')
        if not prompt:
            return error_response("请提供prompt",code=400)
        cache_key = f"ai_response:{prompt[:50]}"
        # 查缓存
        cached_result = cache.get(cache_key)
        if cached_result:
            print(">>>> 命中 Redis 缓存！")
            return cached_result,True
        response = StreamingHttpResponse(self.stream_ai_response(prompt),content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        cache.set(cache_key, response, timeout=3600)
        print('>>>> 已缓存AI回复')
        """
        流式响应本身不适合缓存。
        流式响应的价值在于“实时生成”，而缓存的价值在于“复用结果”。这两个目标在流式场景下是矛盾的
        """
        return response
    
    def stream_ai_response_with_cache(self, prompt, cache_key):
        """流式调用逐字返回，缓存结果"""
        client = OpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )
        full_response = [] # 收集完整回复

        try:
            response = client.chat.completions.create(
                model="deepseek-v4-flash",
                messages=[{"role":"user", "content": prompt}],
                stream=True
            )
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response.append(content)
                    yield f"data:{json.dumps({'content': content})}"
            yield f"data:{json.dumps({'done': True})}\n\n"

            # 流式结束后，把完整回复存入缓存
            if full_response:
                complete_reply = ''.join(full_response)
                cache.set(cache_key, complete_reply, timeout=3600)
                print('>>>> 已缓存AI回复')
            yield f"data: {json.dumps({'done': True})}\n\n" 
        except Exception as e:
            yield f"data:{json.dumps({'error':str(e)})}\n\n"


    @throttle_classes([AICallThrottle])
    @action(detail=False, methods=['post'],url_path='stream2')
    def stream_chat2(self, request):
        """流式对话接口
        因为流式返回，所以不能用DRF的Response，要使用StreamingHttpResponse
        create只会对/ai_log/生效，只在DRF生效
        """
        prompt = request.data.get('prompt')
        if not prompt:
            return error_response("请提供prompt",code=400)
        cache_key = f"ai_response:{prompt[:50]}"
        # 查缓存
        cached_result = cache.get(cache_key)
        if cached_result:
            print(">>>> 命中 Redis 缓存！")
            def fake_stream():
                # 按字拆分
                for char in cached_result:
                    yield f"data:{json.dumps({'content': char})}\n\n"
                yield f"data:{json.dumps({'done': True})}\n\n"
            return StreamingHttpResponse(fake_stream(),content_type='text/event-stream')
        # 缓存未命中
        response = StreamingHttpResponse(self.stream_ai_response_with_cache(prompt,cache_key),content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        print('>>>> 已缓存AI回复')
        """
        流式响应本身不适合缓存。
        流式响应的价值在于“实时生成”，而缓存的价值在于“复用结果”。这两个目标在流式场景下是矛盾的
        """
        return response
    
    # 可以不加这个括号，因为只是 Python 的多行 import 写法
    def stream_ai_response_with_history(self, prompt, model_key, conversation_id, user, trace_id = ""):
        """
        带 conversation_id 的流式 AI 调用
        """
       

        if not model_key:
            model_key = getattr(settings, 'DEFAULT_AI_MODEL', 'deepseek')
        
        model_config = settings.AI_MODELS.get(model_key)
        if not model_config:
            model_key = settings.DEFAULT_AI_MODEL
            model_config = settings.AI_MODELS[model_key]
            
        history = get_coversation_history(conversation_id, user=user)
        messages = history.copy()
        messages.append({
            "role": "user",
            "content": prompt
        })

        client = OpenAI(
            api_key = model_config['api_key'],
            base_url = model_config['base_url']
        )

        start_time = time.time()
        full_response = []

        try: 
            response = client.chat.completions.create(
                model=model_config['default_model'],
                messages=messages,
                stream=True,
                stream_options={"include_usage": True}
            )

            usage = None
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0
            for chunk in response:
                """
                第 3 个 chunk：很高兴
                ...
                最后 1 个 chunk：usage 统计信息
                """
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = chunk.usage
                    prompt_tokens = usage.prompt_tokens or 0
                    completion_tokens = usage.completion_tokens or 0
                    total_tokens = usage.total_tokens or 0
                    continue

                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response.append(content)
                    """
                    json.dumps() 的作用是：
                    把 Python dict 转成前端能 JSON.parse() 的 JSON 字符串。
                    ensure_ascii=False 是为了中文不要变成：
                    \u4f60\u597d

                    \n\n: SSE 事件结束标志。SSE 一条消息通常用空行分隔。
                    """
                    yield f"data:{json.dumps({'content': content}, ensure_ascii=False)}\n\n"
            ai_reply = ''.join(full_response)
            duration = round(time.time() - start_time, 2)

            messages.append({
                "role": "assistant",
                "content": ai_reply,
            })

            save_conversation_history(conversation_id, messages)

            # 失败的不保存
            save_conversation_messages_to_db(
                conversation_id=conversation_id,
                user=user,
                user_content=prompt,
                assistant_content=ai_reply,
            )

            cost = calculate_cost(
                model_key,
                prompt_tokens,
                completion_tokens,
                usage=usage,
                real_model_name=model_config["default_model"],
            )
            AICallLog.objects.create(
                prompt=prompt,
                response=ai_reply,
                duration=duration,
                success=True,
                user=user,
                model_name=model_key,
                conversation_id=conversation_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost=cost,
                trace_id=trace_id,
            )

            yield f"data:{json.dumps({'done': True}, ensure_ascii=False)}\n\n"
        except Exception as e:
            duration = round(time.time() - start_time, 2)
            AICallLog.objects.create(
                prompt=prompt,
                response=str(e),
                duration=duration,
                success=False,
                user=user,
                model_name=model_key,
                conversation_id=conversation_id,
                trace_id=trace_id,
            )
            yield f"data:{json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
    
    @throttle_classes([AICallThrottle])
    @action(detail=False, methods=['post'], url_path='stream3')
    def stream_chat3(self, request):
        """
        支持 conversation_id 和上下文历史的流式对话
        """
        prompt = request.data.get('prompt')
        model_key = request.data.get('model', getattr(settings, 'DEFAULT_AI_MODEL', 'deepseek'))
        conversation_id = request.data.get('conversation_id')
        trace_id = getattr(request, "trace_id", "")
        
        if not prompt:
            return error_response("请提供 prompt", code=400)
        
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
        
        def event_stream():
            # 分成两次发，先发conversation_id
            yield f"data: {json.dumps({'conversation_id': conversation_id}, ensure_ascii=False)}\n\n"

            # 里面会不断 yield data:
            yield from self.stream_ai_response_with_history(
                prompt=prompt,
                model_key=model_key,
                conversation_id=conversation_id,
                user=request.user,
                trace_id=trace_id
            )
        response = StreamingHttpResponse(
            event_stream(),
            content_type='text/event-stream'
        )
        response['Cache-Control'] = 'no-cache'
        # 给 Nginx 看的响应头。 不要把后端流式内容攒一大坨再返回，尽量实时推给浏览器。
        # 如果 Nginx 开了 buffering，后端虽然在 yield，但浏览器可能等一会儿才看到一整段。加这个头，是为了 SSE 更像实时输出。
        response['X-Accel-Buffering'] = 'no'

        return response

    # 从 URL 里提取一个名为 task_id 的参数，匹配一段不包含 / 和 . 的连续字符。
    """
    Celery 的 task_id 是 UUID（比如 550e8400-e29b-41d4-a716-446655440000），它包含 -，所以不能用 \w+（只匹配字母数字下划线），也不能用 [a-zA-Z0-9]+（不匹配 -）。
    用 [^/.]+ 是“安全”的，因为它只排除了 / 和 .，其他字符都可以（包括 -、_、数字、字母）
    """
    @action(detail=False, methods=['get'],url_path='task/(?P<task_id>[^/.]+)')
    def get_task_result(self, request, task_id=None):
        task = AsyncResult(task_id)
        # 用 state 判断任务状态
        state = task.state

        print('state',state)

        if state == 'PENDING':
            return success_response({
                'task_id':task_id,
                'status': 'pending',
                'message':'任务正在排队中'
            })
        elif state == 'FAILED':
            return success_response({
                'task_id':task_id,
                'status': 'failed',
                'message': str(task.info)
            })
        elif state == 'SUCCESS':
            result=task.result
            return success_response({
                'task_id':task_id,
                'status': 'success',
                'message':result
            })
        else:
            return success_response({
                'task_id':task_id,
                'status': 'unknown',
                'message':'未知状态'
            })



    # ========== 标准 CRUD 接口（ModelViewSet 自动生成） ==========
    # 你要实现的代码（AI 自动填 response）
    @throttle_classes([AICallThrottle])
    def create(self, request):
        print(">>>> create 被调用了！")
        user_prompt = request.data.get('prompt')
        # logger.info(f"用户 {request.user.username} 发起 AI 调用，prompt: {user_prompt[:50]}...")
        if not user_prompt:
            return Response(
                {'error': '请提供prompt字段'},
                status=status.HTTP_400_BAD_REQUEST
            )

         # 把任务丢给 Celery，不等待
        trace_id = getattr(request, "trace_id", "")
        task = call_ai_task.delay(user_prompt, request.user.id, trace_id)

        return success_response({
            'task_id': task.id,
            'status': 'processing',
            'message': 'AI 正在处理中，请稍后通过 task_id 查询结果'
        }, message="任务已提交")

        """
        # 记录开始时间
        start_time = time.time()
        # 1. 调用公司 AI 接口
        ai_response,success = self.call_company_ai2(user_prompt)  # ← 核心改动
        
        # 🔥 计算耗时
        duration = time.time() - start_time

        # 2. 把 AI 返回的内容放进数据里
        # request.data['response'] = ai_responses
        # 要保存的数据
        log_data = {
            'prompt':user_prompt,
            'response':ai_response,
            'duration': duration,
            'success': success
        }

        
        # 3. 正常保存
        serializer = self.get_serializer(data=log_data)
        if serializer.is_valid():
            serializer.save(user=request.user) # user=request.user 自动绑定用户
        #     return Response(serializer.data,status=status.HTTP_201_CREATED)
        # return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            return success_response(serializer.data, message="创建成功")
        return error_response("数据校验失败", code=400, data=serializer.errors)
        # return Response(serializer.data)
        """
    
    def get_queryset(self):
        # return super().get_queryset() 原代码
        """
        用户只能看到自己的日志，管理员可以看到所有
        支持日志列表筛选
        """
        user = self.request.user
        if user.is_superuser:
            queryset = AICallLog.objects.all()
        else :
            queryset = AICallLog.objects.filter(user=user)

        keyword = self.request.query_params.get('keyword')
        model_name = self.request.query_params.get('model_name')
        success = self.request.query_params.get('success')
        conversation_id = self.request.query_params.get('conversation_id')
        trace_id = self.request.query_params.get('trace_id')

        if keyword:
            queryset = queryset.filter(
                # OR 查询 -逻辑运算符
                Q(prompt__icontains=keyword) | Q(response__icontains=keyword)
            )

        if model_name:
            queryset = queryset.filter(model_name__icontains=model_name)

        if success in ['true', 'false']:
            queryset = queryset.filter(success=success == 'true')
        
        if conversation_id:
            queryset = queryset.filter(conversation_id=conversation_id)

        if trace_id:
            queryset = queryset.filter(trace_id__icontains=trace_id)

        return queryset
        
        


    @action(detail=False, methods=['get'], url_path='stats', permission_classes=[]) # 这个接口不需要登录
    def get_stats(self, request):
        """
        获取调用统计信息
        """
        # 1. 总体统计
        """
        total = AICallLog.objects.count()
        success_count = AICallLog.objects.filter(success=True).count()
        fail_count = total - success_count
        success_rate = f"{(success_count / total * 100):.2f}%" if total > 0 else "0%"
        avg_duration = AICallLog.objects.aggregate(Avg('duration'))['duration__avg'] or 0
        """
        # 先处理匿名用户
        if not request.user.is_authenticated:
            return Response({
                'message': '请登录后查看统计信息'
            })
        # 分用户
        if request.user.is_superuser:
            queryset = AICallLog.objects.all()
        else:
            queryset = AICallLog.objects.filter(user=request.user) if not request.user.is_superuser else AICallLog.objects.all()
        
        total = queryset.count()
        success_count = queryset.filter(success=True).count()
        fail_count = total - success_count
        success_rate = f"{(success_count / total * 100):.2f}%" if total > 0 else "0%"
        avg_duration = queryset.aggregate(Avg('duration'))['duration__avg'] or 0
        today = timezone.now().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_logs = queryset.filter(call_time__gte=today_start)
        # 从数据库中计算 total_tokens 字段的总和，如果计算结果为 None，则返回 0
        """
        queryset.aggregate(Sum('total_tokens')) 
            aggregate() 是 Django 的聚合方法，对整个查询集进行计算
            Sum('total_tokens') 表示对 total_tokens 字段求和
            返回一个字典
        ['total_tokens__sum'] 
        """
        total_tokens = queryset.aggregate(Sum('total_tokens'))['total_tokens__sum'] or 0
        total_cost = queryset.aggregate(Sum('cost'))['cost__sum'] or 0
        avg_tokens = queryset.aggregate(Avg('total_tokens'))['total_tokens__avg'] or 0

       
        # 2. 今日统计
        today = timezone.now().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_logs =queryset.filter(call_time__gte=today_start)
        today_total = today_logs.count()
        today_success = today_logs.filter(success=True).count()
        today_cost = today_logs.aggregate(Sum('cost'))['cost__sum'] or 0
        today_tokens = today_logs.aggregate(Sum('total_tokens'))['total_tokens__sum'] or 0
        """
        today_total = today_logs.count()
        today_success = today_logs.filter(success=True).count()
        today_fail = today_total - today_success
        today_success_rate = f"{(today_success / today_total * 100):.2f}%" if today_total > 0 else "0%"
        today_avg_duration = today_logs.aggregate(Avg('duration'))['duration__avg'] or 0
        """

        # 按模型分布
        model_stats = list(
            queryset
            .values('model_name')
            .annotate(
                total=Count('id'),
                success_count=Count('id', filter=Q(success=True)),
                avg_duration=Avg('duration'),
                total_tokens=Sum('total_tokens'),
                total_cost=Sum('cost'),
            ).order_by('-total')
        )

        # 近7天趋势
        today = timezone.localdate()
        start_date = today - timedelta(days=6)

        start_datetime = timezone.make_aware(
            datetime.combine(start_date, datetime.min.time())
        )

        daily_rows = list( 
            queryset.exclude(call_time__isnull=True)
                    .filter(call_time__gte=start_datetime) # gte：查询类型，表示 Greater Than or Equal（大于等于）
                    .annotate(day=TruncDate('call_time')) # annotate给每条数据增加一个计算出来的新属性
                    .values('day')
                    .annotate(
                        total=Count('id'),
                        success_count=Count('id', filter=Q(success=True)),
                        total_tokens=Sum('total_tokens'),
                        total_cost=Sum('cost'),
                    ).order_by('day')
        )

        daily_map = {}
        for item in daily_rows:
            day = item.get('day')
            if not day:
                continue
            day_text = day.strftime("%Y-%m-%d")
            daily_map[day_text] = {
                "day": day_text,
                "total": item["total"],
                "success_count": item["success_count"],
                "total_tokens": item["total_tokens"] or 0,
                "total_cost": round(item["total_cost"] or 0, 4),
            }

        daily_list = []
        for i in range(7):
            current_tz = timezone.get_current_timezone()

            day = start_date + timedelta(days=i)
            day_text = day.strftime("%Y-%m-%d")

            day_start = timezone.make_aware(
                datetime.combine(day, datetime.min.time()),
                current_tz
            )
            day_end = timezone.make_aware(
                datetime.combine(day, datetime.max.time()),
                current_tz
            )

            day_logs = queryset.filter(
                call_time__gte=day_start,
                call_time__lte=day_end
            )

            daily_list.append({
                "day": day.strftime("%Y-%m-%d"),
                "total": day_logs.count(),
                "success_count": day_logs.filter(success=True).count(),
                "total_tokens": day_logs.aggregate(Sum('total_tokens'))['total_tokens__sum'] or 0,
                "total_cost": day_logs.aggregate(Sum('cost'))['cost__sum'] or 0
            })

        # 3. 组装返回数据
        data = {
            "total": total,
            "success_count": success_count,
            "fail_count": fail_count,
            "success_rate": success_rate,
            "avg_duration": round(avg_duration, 2),
            "total_tokens": total_tokens,

            "total_cost": round(total_cost, 4),
            "avg_tokens": round(avg_tokens, 2),

            "today_total": today_total,
            "today_success": today_success,
            "today_cost": round(today_cost, 4),
            "today_tokens": today_tokens,

            "model_stats": [
                {
                    "model_name": item["model_name"] or "unknown",
                    "total": item["total"],
                    "success_count": item["success_count"],
                    "avg_duration": round(item["avg_duration"] or 0, 2),
                    "total_tokens": item["total_tokens"] or 0,
                    "total_cost": round(item["total_cost"] or 0, 4),
                }
                for item in model_stats
            ],

            "daily_stats": daily_list,
           # "today_count": today_total,
            #"today_success_count": today_success,
           # "today_fail_count": today_fail,
            #"today_success_rate": today_success_rate,
            #"today_avg_duration": round(today_avg_duration, 2),
        }

        return success_response(data)

    # 自定义路由 --现在是单条修改伪批量，因为detail=False 是区分“批量操作”和“单条操作”的核心开关
    """
    detail=True	操作单条数据	/api/logs/{id}/update/
    detail=False	操作数据集合	/api/logs/update/
    """
    """
    @action(detail=False,methods=['put'], url_path='update')
    def update_by_json(self,request):
        # 通过JSON里的id来更新 
        log_id = request.data.get("id")
        print(f"收到的 log_id: {log_id}, 类型: {type(log_id)}")  # ← 加这一行
        if not log_id:
            return Response({'error': '请提供 id'}, status=400)
        try: 
            log = AICallLog.objects.get(id=log_id, user=request.user)
        except AICallLog.DoesNotExist:
            return Response({'error':'日志不存在'}, status=404)
        # 更新字段
        serializer = self.get_serializer(log,data = request.data,partial=True)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return success_response(serializer.data, message="更新成功")
        return error_response("数据校验失败", code=400, data=serializer.errors)
    """
    @action(detail=False, methods=['put'],url_path='batch-update')
    def batch_update(self, request):
        ids = request.data.get('ids',[])
        update_data = request.data.get('update_data',{})
        # id__in 是 Django ORM 的字段查询语法，表示“ID 在某个列表里” 等价于 SQL 里的 IN 操作，用来批量筛选。
        # ** 是 Python 的字典解包操作符
        AICallLog.objects.filter(id__in=ids,user=request.user).update(**update_data)
        return success_response({"update_count":len(ids)})

    @action(detail=False, methods=['get'], url_path='conversation/(?P<conversation_id>[^/.]+)')
    def get_conversation(self, request, conversation_id):
        """
        获取指定对话话的所有调用记录
        已经知道某个 conversation_id 了，拿这个 ID 去查它的历史消息
        """
        # 当前用户的情况
        # 先在“当前用户可见的日志范围”里查有没有这个 conversation_id。
        logs = self.get_queryset().filter(conversation_id=conversation_id).order_by('call_time')
        if not logs.exists():
            return error_response("对话不存在或没有权限访问", code=404, data={'conversation_id': conversation_id})

        
        history = get_coversation_history(conversation_id, user=request.user)

        
        if not history:
            history = []
            for log in logs:
                history.append({
                    "role": "user",
                    "content": log.prompt,
                    "call_time": log.call_time
                })

                if log.response:
                    history.append({
                        "role": "assistant",
                        "content": log.response,
                        "call_time": log.call_time
                    })

        return success_response({
            'conversation_id': conversation_id,
            'history': history,
            'total': len(history)
        })
    
    @action(detail=False, methods=['get'], url_path='conversations')
    def get_conversations_ids(self, request):
        """
        获取所有对话话的 ID
        """
        # queryset = self.get_queryset().exclude(conversation_id__isnull=True).exclude(conversation_id='')
        # conversations = (
        #     queryset
        #         .values('conversation_id')
        #         .annotate(
        #             total=Count('id'),
        #             last_time = Max('call_time'))
        #         .order_by('-last_time')
        # )
        # return success_response(list(conversations))
        conversations = Conversation.objects.filter(
            user = request.user,
        ).order_by('-updated_at')

        data = [
            {
                "id": item.id,
                "conversation_id": item.conversation_id,
                "title": item.title or item.conversation_id,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
                "message_count": item.messages.count(),
            }
            for item in conversations
        ]
        return success_response(data)


def test_python(request):
    prompt_text = "帮我写个python计划"
    duration_value = 0.5
    is_success = True

    # 从数据库查数据
    all_prompts = [log.prompt for log in AICallLog.objects.all()]
    log = AICallLog(prompt="测试", duration=0.1)
    log.save()  # ← 这一行必须有
    # 返回结果给浏览器看
    return JsonResponse({
        "message":"测试成功",
        "prompt_text": prompt_text,
        "duration": duration_value,
        "all_prompts": all_prompts,
    })

def test_python1(request):
    # 变量和类型
    prompt_text = "帮我写个python计划"
    duration_value = 0.5
    is_success = True

    print(type(is_success))

    # 列表和字典

    return JsonResponse({
        "message":"测试成功",
        "prompt_text_type": str(type(prompt_text)),
        "duration_value_type": str(type(duration_value)),
        "is_success_type": str(type(is_success)),
    })

# 健康检查接口（项目运行状态和接口性能）
def health_check(request):
     # 检查数据库
    db_healthy = True
    try:
        # 数据库连接检查
        # ['default']：获取默认数据库（你在 settings.py 里配置的 DATABASES['default']）
        # .cursor()：创建一个数据库游标，用来执行 SQL 查询语句
        # 如果数据库连不上，.cursor() 会抛异常；如果连得上，就正常返回。所以用 try/except 包住这行，就能判断数据库是否可用。
        connections['default'].cursor()
    except OperationalError: # Django 数据库异常类，当数据库连接失败或操作出错时抛出。
        db_healthy = False
    # 检查redis缓存
    redis_healthy = True
    try:
        # cache.set(key, value, timeout)：往缓存里存一个键值对,5s后自动删除
        cache.set('health_check','ok',timeout=5)
        if cache.get('health_check') != 'ok':
            redis_healthy = False
    except Exception:
        redis_healthy = False
        
    status = 'healthy' if db_healthy and redis_healthy else 'unhealthy'
    code = 200 if status == 'healthy' else 503

    return JsonResponse({
            "status": status,
            'database': 'ok' if db_healthy else 'error',
            'redis': 'ok' if redis_healthy else 'error',
            'timestamp': timezone.now().isoformat(), # .isoformat()：转换成 ISO 8601 标准格式
    }, status=code)
