import logging
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

@dataclass
class AINotificationContext:
    # Ai调用的消息
    success: bool
    user_id: int
    model_name: str
    prompt: str
    response: str = ""
    error_message: str = ""
    trace_id: str = ""
    conversation_id: str = ""
    duration: float = 0.0
    total_tokens: int = 0
    cost: float = 0.0
    log_id: int | None = None

# 判断是否需要通知
def should_notify_ai_call(ctx: AINotificationContext) -> bool:
    if not settings.AI_NOTIFY_ENABLED:
        return False
    if not ctx.success:
        return True
    if settings.AI_NOTIFY_ON_SUCCESS:
        return True
    if ctx.duration >= settings.AI_NOTIFY_SLOW_SECONDS:
        return True
    if ctx.cost >= settings.AI_NOTIFY_HIGH_COST:
        return True
    return False

# 真正调用飞书 Webhook 发消息
def send_feishu_ai_notification(ctx: AINotificationContext) -> None:
    if not should_notify_ai_call(ctx):
        return {"sent": False, "reason": "rule_skipped"}
    if not settings.FEISHU_BOT_WEBHOOK:
        return {"sent": False, "reason": "missing_webhook"}

    status_text = "成功" if ctx.success else "失败"
    summary = ctx.response or ctx.error_message or "-"

    text = f"""AI通知 | AI调用{status_text}
    用户ID：{ctx.user_id}
    模型：{ctx.model_name}
    耗时：{ctx.duration:.2f}s
    Token：{ctx.total_tokens}
    成本：{ctx.cost:.6f}
    Trace ID：{ctx.trace_id or "-"}
    会话ID：{ctx.conversation_id or "-"}
    日志ID：{ctx.log_id or "-"}

    用户输入：{ctx.prompt[:120]}
    结果摘要：{summary[:120]}...
    """

    try:
        resp = requests.post(
            settings.FEISHU_BOT_WEBHOOK,
            json={
                "msg_type": "text",
                "content": {
                    "text": text
                }
            },
            timeout = 5
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.exception("发送飞书通知失败: %s", e)
        return {
            "sent": False,
            "reason": "request_failed",
            "error": str(e)
        }
    if data.get("code", 0) != 0:
        return {
            "sent": False,
            "reason": "feishu_rejected",
            "error": data
        }

    return {
        "sent": True,
        "response": data
    }