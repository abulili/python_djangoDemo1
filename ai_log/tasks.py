import time
import logging
from celery import shared_task
from django.conf import settings
from openai import OpenAI
from .models import AICallLog, AiTraceStepLog
from django.contrib.auth.models import User
from .services import call_ai_service

from celery.exceptions import SoftTimeLimitExceeded

logger = logging.getLogger(__name__)

@shared_task
def call_ai_task(prompt, user_id, trace_id = ""):
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
            model="deepseek-v4-flash",
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
            trace_id=trace_id
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
                trace_id=trace_id,
            )
        except:
            pass
        return {
            'status': 'error',
            'error': str(e),
        }

@shared_task
def call_ai_task2(prompt, user_id, model_key=None,trace_id=""):
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
        logger.debug('response',str(response))
        # 存数据库
        user = User.objects.get(id=user_id)
        log = AICallLog.objects.create(
            prompt = prompt,
            response = ai_reply,
            duration = round(duration,2),
            success=True,
            user=user,
            model_name=model_key,
            trace_id=trace_id,
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
        logger.debug('call_ai_task2 error',str(e))
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
                trace_id=trace_id,
            )
        except:
            pass
        return {
            'status': 'error',
            'error': str(e),
        }

def is_retryable_ai_error(error_message):
    retry_keywords = [
        "timeout",
        "timed out",
        "超时",
        "connection",
        "连接",
        "temporarily",
        "临时",
        "rate limit",
        "429",
        "500",
        "502",
        "503",
        "504",
    ]

    non_retry_keywords = [
        "invalid api key",
        "unauthorized",
        "401",
        "forbidden",
        "403",
        "余额不足",
        "insufficient balance",
        "model not found",
        "invalid model",
        "参数错误",
        "bad request",
        "400",
    ]

    lower_message = error_message.lower()

    if any(keyword in lower_message for keyword in non_retry_keywords):
        return False

    return any(keyword in lower_message for keyword in retry_keywords)

def get_ai_retry_countdown(error_message):
    lower_message = error_message.lower()

    if "429" in lower_message or "rate limit" in lower_message:
        return 10

    if "503" in lower_message or "temporarily" in lower_message or "临时" in lower_message:
        return 5

    return 2

@shared_task(bind=True, max_retries=3, default_retry_delay=2, soft_time_limit=240,
    time_limit=300) # self--Celery task 对象 
    # soft_time_limit=240：跑到 240 秒时，Celery 先给任务一个“软提醒/软中断” time_limit=300：跑到 300 秒时，Celery 强制终止任务
def call_ai_task4(self, prompt, user_id, model_key=None, conversation_id=None, template_name=None, template_vars=None,trace_id=""):
    """
    异步调用AI模型，存结果到数据库。
    bind=True:让任务函数能拿到当前 task 对象。
    self.request.retries:当前已经重试了几次。
    self.max_retries:最多允许重试几次。
    """
    
    logger.info(f"开始处理AI调用，会话ID：{conversation_id}用户ID： {user_id}, prompt: {prompt[:50]}...")
    user = User.objects.get(id=user_id)
    start_time = time.time()

    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id,
        step="task_start",
        query=prompt,
        detail={
            "model": model_key,
            "template_name": template_name or "",
        },
    )

    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id,
        step="call_model_start",
        query=prompt,
        detail={
            "model": model_key,
            "stream": False,
        },
    )

    try:
        result, success = call_ai_service(
            prompt=prompt,
            model_key=model_key,
            conversation_id=conversation_id,
            template_name=template_name,
            template_vars=template_vars,
            user=user
        )
        task_duration = result.get("duration", 0.0) or 0.0
        log = AICallLog.objects.create(
            prompt = prompt,
            response=result.get('reply', ''),
            duration = task_duration,
            success=success,
            user=user,
            model_name=model_key or 'deepseek',
            prompt_tokens=result.get('prompt_tokens', 0),
            completion_tokens=result.get('completion_tokens', 0),
            total_tokens=result.get('total_tokens', 0),
            cost=result.get('cost', 0.0),
            conversation_id=conversation_id,
            trace_id=trace_id
        )
        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="task_done" if success else "task_failed",
            duration=task_duration,
            query=prompt,
            success=success,
            error_message="" if success else result.get("reply", "AI调用失败"),
            detail={
                "success": success,
                "duration": task_duration,
                "total_tokens": result.get("total_tokens", 0),
                "cost": result.get("cost", 0.0),
                "model": model_key,
            },
        )

        logger.info(f"AI调用完成，日志ID：{log.id}，success={success}")
        return {
            "status": "success" if success else "error",
            "log_id": log.id,
            'prompt': prompt,
            'response': result.get("reply", ""),
            'duration': task_duration,
            'model_name':model_key,
            'tokens': result.get('total_tokens',0),
            'cost': result.get('cost', 0.0),
            'conversation_id': conversation_id,
            "trace_id": trace_id,
            "total_tokens": result.get("total_tokens", 0),
        }
    except SoftTimeLimitExceeded as e:
        """
        time_limit 的作用是防极端情况,直接停止
        
        soft_time_limit 抛出来了，但代码没捕获住
        第三方 SDK 卡死，无法正常响应 Python 异常
        任务卡在某些底层 IO / C 扩展里
        代码进入死循环或阻塞点，软超时没能干净退出
        """
        duration = time.time() - start_time
        error_message = "AI任务执行超时"

        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id or "",
            step="task_failed",
            query=prompt,
            success=False,
            error_message=error_message,
            duration=duration,
            detail={
                "reason": "soft_time_limit_exceeded",
                "soft_time_limit": 240,
                "time_limit": 300,
            },
        )

        AICallLog.objects.create(
            conversation_id=conversation_id or "",
            prompt=prompt,
            response=error_message,
            duration=duration,
            success=False,
            user=user,
            model_name=model_key or "deepseek",
            trace_id=trace_id,
        )

        logger.exception("call_ai_task4 执行超时")

        return {
            "status": "error",
            "message": error_message,
            "trace_id": trace_id,
            "conversation_id": conversation_id,
        }
    except Exception as e:
        error_message = str(e)
        duration = time.time() - start_time
        retryable = is_retryable_ai_error(error_message)
        countdown = get_ai_retry_countdown(error_message)


        if retryable and self.request.retries < self.max_retries:
            AiTraceStepLog.objects.create(
                user=user,
                trace_id=trace_id,
                conversation_id=conversation_id or "",
                step="task_retry",
                query=prompt,
                success=False,
                error_message=error_message,
                duration=duration,
                detail={
                    "retry_count": self.request.retries + 1,
                    "max_retries": self.max_retries,
                    "retryable": retryable,
                    "countdown": countdown,
                },
            )

            raise self.retry(exc=e, countdown=countdown)

        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id or "",
            step="task_failed",
            query=prompt,
            success=False,
            error_message=error_message,
            duration=duration,
            detail={
                "reason": "max_retries_exceeded" if retryable else "non_retryable_error",
                "retry_count": self.request.retries,
                "max_retries": self.max_retries,
                "retryable": retryable,
                "countdown": countdown,
            },
        )

        AICallLog.objects.create(
            conversation_id=conversation_id or "",
            prompt=prompt,
            response=error_message,
            duration=duration,
            success=False,
            user=user,
            model_name=model_key or "deepseek",
            trace_id=trace_id,
        )

        logger.exception("call_ai_task4 调用失败")

        return {
            "status": "error",
            "message": error_message,
            "trace_id": trace_id,
            "conversation_id": conversation_id,
        }
        

