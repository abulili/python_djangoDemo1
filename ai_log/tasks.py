import time
import logging
from celery import shared_task
from django.conf import settings
from openai import OpenAI
from .models import AICallLog
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

@shared_task
def call_ai_task(prompt, user_id):
    """
    异步调用AI模型，存结果到数据库。
    """
    logger.info(f"开始处理AI调用，用户ID： {user_id}, prompt: {prompt[:50]}...")
    try:
        client = OpenAI(
            api_key = settings.DEEPSEEK_API_KEY,
            base_url = "https://api.deepseek.com",
        )

        start_time = time.time()
        response = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {"role": "user", "content": prompt}
            ],
            stream=False,
        )
        duration = time.time() - start_time

        ai_reply = response.choices[0].message.content

        # 存数据库
        user = User.objects.get(id=user_id)
        log = AICallLog.objects.create(
            prompt = prompt,
            response = ai_reply,
            duration = round(duration,2),
            success=True,
            user=user,
        )
        logger.info(f"AI调用成功， 日志ID： {log.id}")
        return {
            'status': 'success',
            'log_id': log.id,
            'prompt': prompt,
            'response': ai_reply,
            'duration': round(duration, 2)
        }
    except Exception as e:
        logger.error(f"AI调用失败：{e}")
        # 存一条失败的日志
        try:
            user = User.objects.get(id=user_id)
            AICallLog.objects.create(
                prompt=prompt,
                response=f"AI调用失败：{str(e)}",
                duration=0.0,
                success=False,
                user=user,
            )
        except:
            pass
        return {
            'status': 'error',
            'error': str(e),
        }

@shared_task
def call_ai_task2(prompt, user_id, model_key=None):
    """
    异步调用AI模型，存结果到数据库。
    """
    # 获取模型配置
    if not model_key:
        model_key = settings.DEFAULT_AI_MODEL

    model_config = settings.AI_MODELS.get(model_key)
    if not model_config:
        model_key = settings.DEFAULT_AI_MODEL
        model_config = model_config[model_key]

    logger.info(f"开始处理AI调用，用户ID： {user_id}, prompt: {prompt[:50]}...")
    try:
        client = OpenAI(
            api_key = model_config['api_key'],
            base_url = model_config['base_url'],
        )

        start_time = time.time()
        response = client.chat.completions.create(
            model=model_config['default_model'],
            messages=[
                {"role": "user", "content": prompt}
            ],
            stream=False,
        )
        duration = time.time() - start_time

        ai_reply = response.choices[0].message.content if response.choices[0].message else response.response
        print('response',str(response))
        # 存数据库
        user = User.objects.get(id=user_id)
        log = AICallLog.objects.create(
            prompt = prompt,
            response = ai_reply,
            duration = round(duration,2),
            success=True,
            user=user,
            model_name=model_key,
        )
        logger.info(f"AI调用成功， 日志ID： {log.id}")
        return {
            'status': 'success',
            'log_id': log.id,
            'prompt': prompt,
            'response': ai_reply,
            'duration': round(duration, 2),
            'model_name':model_key,
        }
    except Exception as e:
        print('call_ai_task2 error',str(e))
        logger.error(f"AI调用失败：{e}")
        # 存一条失败的日志
        try:
            user = User.objects.get(id=user_id)
            AICallLog.objects.create(
                prompt=prompt,
                response=f"AI调用失败：{str(e)}",
                duration=0.0,
                success=False,
                user=user,
                model_name=model_key,
            )
        except:
            pass
        return {
            'status': 'error',
            'error': str(e),
        }

