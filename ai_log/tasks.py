import time
import logging
from celery import shared_task
from django.conf import settings
from openai import OpenAI
from .models import AICallLog, AiTraceStepLog
from django.contrib.auth.models import User
from .services import call_ai_service

from celery.exceptions import SoftTimeLimitExceeded

from .notifications.feishu import AINotificationContext, send_feishu_ai_notification

from .feishu_bot_service import (
    FeishuBotError,
    extract_feishu_text_message,
    send_feishu_text_message,
    verify_feishu_event_token,
)

from .job_record_service import (process_job_record_prompt)

from .langchain_agent_service import run_langchain_style_agent

from .multi_agent_service import run_multi_agent

logger = logging.getLogger(__name__)


def _get_task_user_or_record_missing(
    *,
    user_id,
    trace_id,
    conversation_id,
    query,
    task_id,
    model_key="",
    failed_step,
    extra_detail=None,
):
    user = User.objects.filter(id=user_id).first()
    if user:
        return user

    error_message = f"任务用户不存在: user_id={user_id}"
    detail = {
        "reason": "user_not_found",
        "user_id": user_id,
        "task_id": task_id or "",
    }
    if extra_detail:
        detail.update(extra_detail)

    AiTraceStepLog.objects.create(
        user=None,
        trace_id=trace_id,
        conversation_id=conversation_id or "",
        step=failed_step,
        query=query,
        success=False,
        error_message=error_message,
        detail=detail,
    )

    AICallLog.objects.create(
        user=None,
        prompt=query,
        response=error_message,
        success=False,
        model_name=model_key or "",
        trace_id=trace_id,
        conversation_id=conversation_id or "",
        task_id=task_id or "",
    )

    return None


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
        logger.debug("response: %s", str(response))
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
        logger.debug("call_ai_task2 error: %s", str(e))
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

# * 在这里的意思是：后面的参数必须写参数名传入，不能按位置传
def record_feishu_notification(
    *,
    user,
    trace_id,
    conversation_id,
    prompt,
    success,
    model_name,
    response="",
    error_message="",
    duration=0.0,
    total_tokens=0,
    cost=0.0,
    log_id=None,
):
    try:
        notify_result = send_feishu_ai_notification(AINotificationContext(
            success=success,
            user_id=user.id,
            model_name=model_name,
            prompt=prompt,
            response=response,
            error_message=error_message,
            trace_id=trace_id,
            conversation_id=conversation_id or "",
            duration=duration,
            total_tokens=total_tokens,
            cost=cost,
            log_id=log_id,
        ))
    except Exception as e:
        logger.exception("发送飞书 AI 通知失败")
        notify_result = {
            "sent": False,
            "reason": "notification_exception",
            "error": str(e),
        }

    try:
        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id or "",
            step="notify_feishu",
            query=prompt,
            success=notify_result.get("sent", False) or notify_result.get("reason") == "rule_skipped",
            error_message="" if notify_result.get("sent", False) else notify_result.get("reason", ""),
            detail=notify_result,
        )
    except Exception as e:
        logger.exception("记录飞书通知 trace 失败")

    return notify_result

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
    task_id = self.request.id or ""
    user = _get_task_user_or_record_missing(
        user_id=user_id,
        trace_id=trace_id,
        conversation_id=conversation_id,
        query=prompt,
        task_id=task_id,
        model_key=model_key or "deepseek",
        failed_step="task_failed",
        extra_detail={"source": "call_ai_task4"},
    )
    if not user:
        return {
            "status": "failed",
            "success": False,
            "trace_id": trace_id,
            "conversation_id": conversation_id or "",
            "error": f"任务用户不存在: user_id={user_id}",
        }
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
            trace_id=trace_id,
            task_id=self.request.id or "",
        )

        # 飞书
        record_feishu_notification(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            prompt=prompt,
            success=success,
            model_name=model_key or "deepseek",
            response=result.get("reply", ""),
            error_message="" if success else result.get("reply", "AI调用失败"),
            duration=task_duration,
            total_tokens=result.get("total_tokens", 0),
            cost=result.get("cost", 0.0),
            log_id=log.id,
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

        log = AICallLog.objects.create(
            conversation_id=conversation_id or "",
            prompt=prompt,
            response=error_message,
            duration=duration,
            success=False,
            user=user,
            model_name=model_key or "deepseek",
            trace_id=trace_id,
            task_id=self.request.id or "",
        )

        record_feishu_notification(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            prompt=prompt,
            success=False,
            model_name=model_key or "deepseek",
            response="",
            error_message=error_message,
            duration=duration,
            total_tokens=0,
            cost=0.0,
            log_id=log.id,
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

        log = AICallLog.objects.create(
            conversation_id=conversation_id or "",
            prompt=prompt,
            response=error_message,
            duration=duration,
            success=False,
            user=user,
            model_name=model_key or "deepseek",
            trace_id=trace_id,
            task_id=self.request.id or "",
        )

        record_feishu_notification(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            prompt=prompt,
            success=False,
            model_name=model_key or "deepseek",
            response="",
            error_message=error_message,
            duration=duration,
            total_tokens=0,
            cost=0.0,
            log_id=log.id,
        )

        logger.exception("call_ai_task4 调用失败")

        return {
            "status": "error",
            "message": error_message,
            "trace_id": trace_id,
            "conversation_id": conversation_id,
        }
        

@shared_task(bind=True, soft_time_limit=240, time_limit=300)
def langchain_agent_task(
    self,
    query,
    user_id,
    conversation_id=None,
    top_k=3,
    search_type="hybrid",
    model_key=None,
    trace_id="",
    business_template_name=None,
    business_template_vars=None,
):
    business_template_vars = business_template_vars or {}
    task_id = self.request.id or ""
    user = _get_task_user_or_record_missing(
        user_id=user_id,
        trace_id=trace_id,
        conversation_id=conversation_id,
        query=query,
        task_id=task_id,
        model_key=model_key,
        failed_step="langchain_agent_task_failed",
        extra_detail={"framework": "langchain"},
    )
    if not user:
        return {
            "status": "failed",
            "success": False,
            "trace_id": trace_id,
            "conversation_id": conversation_id or "",
            "error": f"任务用户不存在: user_id={user_id}",
        }

    start_time = time.time()

    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id or "",
        step="langchain_agent_task_start",
        query=query,
        detail={
            "task_id": task_id,
            "search_type": search_type,
            "top_k": top_k,
            "model_key": model_key,
            "business_template_name": business_template_name or "",
        },
    )

    try:
        result = run_langchain_style_agent(
            user=user,
            query=query,
            conversation_id=conversation_id,
            top_k=top_k,
            search_type=search_type,
            model_key=model_key,
            trace_id=trace_id,
            call_ai_service=call_ai_service,
            business_template_name=business_template_name,
            business_template_vars=business_template_vars,
        )

        duration = time.time() - start_time

        if not result.get("success"):
            error_message = result.get("error", "LangChain Agent 调用失败")

            AICallLog.objects.create(
                user=user,
                prompt=query,
                response=error_message,
                success=False,
                model_name=model_key or "",
                trace_id=trace_id,
                conversation_id=conversation_id or "",
                duration=duration,
                task_id=task_id,
            )

            AiTraceStepLog.objects.create(
                user=user,
                trace_id=trace_id,
                conversation_id=conversation_id or "",
                step="langchain_agent_task_failed",
                query=query,
                success=False,
                error_message=error_message,
                duration=duration,
                detail={
                    "task_id": task_id,
                    "framework": result.get("framework", ""),
                },
            )

            return {
                "status": "error",
                "message": error_message,
                "trace_id": trace_id,
                "conversation_id": conversation_id,
            }

        answer = result.get("answer", "")
        usage = result.get("usage", {}) or {}

        AICallLog.objects.create(
            user=user,
            prompt=query,
            response=answer,
            success=True,
            model_name=model_key or "",
            trace_id=trace_id,
            conversation_id=conversation_id or "",
            duration=duration,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            cost=usage.get("cost", 0.0),
            task_id=task_id,
        )

        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id or "",
            step="langchain_agent_task_done",
            query=query,
            success=True,
            duration=duration,
            detail={
                "task_id": task_id,
                "framework": result.get("framework", ""),
                "references_count": len(result.get("references", [])),
                "tool_count": len(result.get("tools", [])),
            },
        )

        return {
            "status": "success",
            "trace_id": trace_id,
            "conversation_id": conversation_id,
            "answer": answer,
            "result": result,
        }

    except Exception as e:
        duration = time.time() - start_time
        error_message = str(e)

        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id or "",
            step="langchain_agent_task_failed",
            query=query,
            success=False,
            error_message=error_message,
            duration=duration,
            detail={
                "task_id": task_id,
                "reason": "unhandled_exception",
            },
        )

        AICallLog.objects.create(
            user=user,
            prompt=query,
            response=error_message,
            success=False,
            model_name=model_key or "",
            trace_id=trace_id,
            conversation_id=conversation_id or "",
            duration=duration,
            task_id=task_id,
        )

        return {
            "status": "error",
            "message": error_message,
            "trace_id": trace_id,
            "conversation_id": conversation_id,
        }

@shared_task(bind=True, soft_time_limit=240, time_limit=300)
def multi_agent_task(
    self,
    query,
    user_id,
    conversation_id=None,
    top_k=3,
    search_type="hybrid",
    model_key=None,
    trace_id="",
    router_type="rule",
    router_model_key=None,
    enabled_agents=None,
):
    enabled_agents = enabled_agents or []
    task_id = self.request.id or ""
    user = _get_task_user_or_record_missing(
        user_id=user_id,
        trace_id=trace_id,
        conversation_id=conversation_id,
        query=query,
        task_id=task_id,
        model_key=model_key,
        failed_step="multi_agent_task_failed",
        extra_detail={
            "router_type": router_type,
            "router_model_key": router_model_key or "",
        },
    )
    if not user:
        return {
            "status": "failed",
            "success": False,
            "trace_id": trace_id,
            "conversation_id": conversation_id or "",
            "error": f"任务用户不存在: user_id={user_id}",
        }

    start_time = time.time()

    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id or "",
        step="multi_agent_task_start",
        query=query,
        detail={
            "task_id": task_id,
            "search_type": search_type,
            "top_k": top_k,
            "model_key": model_key,
            "router_type": router_type,
            "router_model_key": router_model_key,
            "enabled_agents": enabled_agents,
        },
    )

    try:
        result = run_multi_agent(
            user=user,
            query=query,
            conversation_id=conversation_id,
            top_k=top_k,
            search_type=search_type,
            model_key=model_key,
            trace_id=trace_id,
            call_ai_service=call_ai_service,
            router_type=router_type,
            router_model_key=router_model_key,
            enabled_agents=enabled_agents,
        )

        duration = time.time() - start_time

        if not result.get("success"):
            error_message = result.get("error", "Multi-Agent 调用失败")

            AICallLog.objects.create(
                user=user,
                prompt=query,
                response=error_message,
                success=False,
                model_name=model_key or "",
                trace_id=trace_id,
                conversation_id=conversation_id or "",
                duration=duration,
                task_id=task_id,
            )

            AiTraceStepLog.objects.create(
                user=user,
                trace_id=trace_id,
                conversation_id=conversation_id or "",
                step="multi_agent_task_failed",
                query=query,
                success=False,
                error_message=error_message,
                duration=duration,
                detail={
                    "task_id": task_id,
                    "router_type": router_type,
                    "agents": result.get("agents", []),
                    "agent_plan": result.get("agent_plan", {}),
                    "agent_failures": result.get("agent_failures", {}),
                },
            )

            return {
                "status": "error",
                "message": error_message,
                "trace_id": trace_id,
                "conversation_id": conversation_id,
            }

        answer = result.get("answer", "")
        usage_summary = result.get("usage_summary", {}) or {}

        AICallLog.objects.create(
            user=user,
            prompt=query,
            response=answer,
            success=True,
            model_name=model_key or "",
            trace_id=trace_id,
            conversation_id=conversation_id or "",
            duration=duration,
            total_tokens=usage_summary.get("total_tokens", 0),
            cost=usage_summary.get("total_cost", 0.0),
            task_id=task_id,
        )

        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id or "",
            step="multi_agent_task_done",
            query=query,
            success=True,
            duration=duration,
            detail={
                "task_id": task_id,
                "router_type": router_type,
                "agents": result.get("agents", []),
                "references_count": len(result.get("references", [])),
                "agent_plan": result.get("agent_plan", {}),
                "agent_failures": result.get("agent_failures", {}),
                "usage_summary": usage_summary,
            },
        )

        return {
            "status": "success",
            "trace_id": trace_id,
            "conversation_id": conversation_id,
            "answer": answer,
            "result": result,
        }

    except Exception as e:
        duration = time.time() - start_time
        error_message = str(e)

        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id or "",
            step="multi_agent_task_failed",
            query=query,
            success=False,
            error_message=error_message,
            duration=duration,
            detail={
                "task_id": task_id,
                "router_type": router_type,
                "reason": "unhandled_exception",
            },
        )

        AICallLog.objects.create(
            user=user,
            prompt=query,
            response=error_message,
            success=False,
            model_name=model_key or "",
            trace_id=trace_id,
            conversation_id=conversation_id or "",
            duration=duration,
            task_id=task_id,
        )

        return {
            "status": "error",
            "message": error_message,
            "trace_id": trace_id,
            "conversation_id": conversation_id,
        }

@shared_task
def process_feishu_job_record_event_task(prompt, message_info, trace_id):
    from .job_record_service import process_job_record_prompt
    from .feishu_bot_service import FeishuBotError, send_feishu_text_message
    from .models import AiTraceStepLog

    try:
        result = process_job_record_prompt(
            prompt=prompt,
            user=None,
            trace_id=trace_id,
            source="feishu_bot",
            source_detail={
                "open_id": message_info.get("open_id", ""),
                "message_id": message_info.get("message_id", ""),
                "chat_id": message_info.get("chat_id", ""),
                "user_id": message_info.get("open_id", "") or "feishu_user",
            },
        )
    except Exception as e:
        error_text = str(e)

        AiTraceStepLog.objects.create(
            trace_id=trace_id,
            conversation_id="",
            step="feishu_job_record_failed",
            query=prompt,
            detail={
                "provider": "coze_n8n_chain",
                "message_info": message_info,
            },
            success=False,
            error_message=error_text,
        )

        try:
            reply_result = send_feishu_text_message(
                message_info.get("open_id", ""),
                f"求职记录处理失败，请稍后重试。\nTrace ID：{trace_id}",
            )
        except FeishuBotError as reply_error:
            reply_result = {
                "sent": False,
                "reason": "reply_failed",
                "error": str(reply_error),
            }

        AiTraceStepLog.objects.create(
            trace_id=trace_id,
            conversation_id="",
            step="feishu_bot_reply",
            query=prompt,
            detail={
                "provider": "feishu",
                "reply_result": reply_result,
                "message_info": message_info,
            },
            success=bool(reply_result.get("sent")),
            error_message="" if reply_result.get("sent") else reply_result.get("error", reply_result.get("reason", "")),
        )

        return {
            "status": "failed",
            "trace_id": trace_id,
            "error": error_text,
            "reply_result": reply_result,
        }

    record = result.get("record") or {}

    reply_text = (
        "已记录到求职面试表："
        f"{record.get('company', '-')}"
        f" / {record.get('position', '-')}"
        f" / {record.get('status', '-')}"
        f"\nTrace ID：{result.get('trace_id')}"
    )

    try:
        reply_result = send_feishu_text_message(
            message_info.get("open_id", ""),
            reply_text,
        )
    except FeishuBotError as e:
        reply_result = {
            "sent": False,
            "reason": "reply_failed",
            "error": str(e),
        }

    AiTraceStepLog.objects.create(
        trace_id=trace_id,
        conversation_id=record.get("company", ""),
        step="feishu_bot_reply",
        query=prompt,
        detail={
            "provider": "feishu",
            "reply_result": reply_result,
            "message_info": message_info,
        },
        success=bool(reply_result.get("sent")),
        error_message="" if reply_result.get("sent") else reply_result.get("error", reply_result.get("reason", "")),
    )

    return {
        **result,
        "reply_result": reply_result,
    }
