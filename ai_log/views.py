from django.shortcuts import render
import requests
# Create your views here. 处理请求的函数，比如查询数据库、调用AI（业务逻辑）

from django.http import JsonResponse

from rest_framework import viewsets
from ai_log.models import AICallLog
from .serializers import AICallLogSerializer

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

from django.db.models import Count, Sum, Avg
from django.utils import timezone
from datetime import datetime, timedelta

from django.http import StreamingHttpResponse
import json

from rest_framework.permissions import IsAuthenticated

from rest_framework.exceptions import PermissionDenied

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
            "model": "deepseek-v4-pro",
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
        client = OpenAI(api_key=settings.DEEPSEEK_API_KEY,base_url="https://api.deepseek.com")
        # print(os.getenv("DEEPSEEK_API_KEY"))
        
        for attempt in range(retries):
            try: 
                response = client.chat.completions.create(
                    model="deepseek-v4-pro",
                    messages=[{
                        "role":"user",
                        "content": prompt
                    }],
                    stream=False
                )
                ai_reply = response.choices[0].message.content
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


    # 流式sse
    def stream_ai_response(self, prompt):
        """流式调用逐字返回"""
        client = OpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )

        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
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



    @action(detail=False, methods=['post'],url_path='stream')
    def stream_chat(self, request):
        """流式对话接口"""
        prompt = request.data.get('prompt')
        if not prompt:
            return error_response("请提供prompt",code=400)
        
        response = StreamingHttpResponse(self.stream_ai_response(prompt),content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        return response
    # ========== 标准 CRUD 接口（ModelViewSet 自动生成） ==========
    # 你要实现的代码（AI 自动填 response）
    def create(self, request):
        user_prompt = request.data.get('prompt')

        if not user_prompt:
            return Response(
                {'error': '请提供prompt字段'},
                status=status.HTTP_400_BAD_REQUEST
            )
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
    
    def get_queryset(self):
        # return super().get_queryset() 原代码
        """用户只能看到自己的日志，管理员可以看到所有"""
        user = self.request.user
        if user.is_superuser:
            return AICallLog.objects.all()
        return AICallLog.objects.filter(user=user)
        


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
        # 分用户
        queryset = AICallLog.objects.filter(user=request.user) if not request.user.is_superuser else AICallLog.objects.all()
        
        total = queryset.count()
        success_count = queryset.filter(success=True).count()
        fail_count = total - success_count
        success_rate = f"{(success_count / total * 100):.2f}%" if total > 0 else "0%"
        avg_duration = queryset.aggregate(Avg('duration'))['duration__avg'] or 0
        today = timezone.now().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_logs = queryset.filter(call_time__gte=today_start)

        """
        # 2. 今日统计
        today = timezone.now().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_logs = AICallLog.objects.filter(call_time__gte=today_start)
        
        today_total = today_logs.count()
        today_success = today_logs.filter(success=True).count()
        today_fail = today_total - today_success
        today_success_rate = f"{(today_success / today_total * 100):.2f}%" if today_total > 0 else "0%"
        today_avg_duration = today_logs.aggregate(Avg('duration'))['duration__avg'] or 0
        """
        # 3. 组装返回数据
        data = {
            "total": total,
            "success_count": success_count,
            "fail_count": fail_count,
            "success_rate": success_rate,
            "avg_duration": round(avg_duration, 2),
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
        AICallLog.objects.filter(id__in=ids,user=request.user).update(**update_data)
        return success_response({"update_count":len(ids)})

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

