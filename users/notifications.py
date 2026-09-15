import logging
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

@dataclass
class SecurityNotificationContext:
    risk_type: str
    ip_address: str = ""
    user_id: int | None = None
    username: str = ""
    path: str = ""
    method: str = ""
    status_code: int = 0
    count: int = 0
    window_seconds: int = 60
    detail: dict | None = None

def should_notify_security_event(ctx: SecurityNotificationContext) -> bool:
    if not getattr(settings, "SECURITY_NOTIFY_ENABLED", True):
        return False

    return True
    
def send_feishu_security_notification(ctx: SecurityNotificationContext) -> dict:
    if not should_notify_security_event(ctx):
        return {
            "sent": False,
            "reason": "rule_skipped",
        }

    webhook = getattr(settings, "FEISHU_BOT_WEBHOOK", "")
    if not webhook:
        return {
            "sent": False,
            "reason": "missing_webhook",
        }

    risk_label_map = {
        "blocked_ip": "黑名单 IP",
        "auth_failed": "认证失败",
        "permission_denied": "权限拒绝",
        "rate_limited": "接口限流",
        "server_error": "服务异常",
    }

    risk_label = risk_label_map.get(ctx.risk_type, ctx.risk_type)

    text = f"""AI通知 | 安全风控告警
    风险类型：{risk_label}
    IP：{ctx.ip_address or "-"}
    用户ID：{ctx.user_id or "-"}
    用户名：{ctx.username or "-"}
    接口：{ctx.method} {ctx.path}
    状态码：{ctx.status_code}
    窗口：{ctx.window_seconds}s
    触发次数：{ctx.count}

    处理建议：请检查该 IP 或用户是否存在异常请求行为，必要时执行 IP 拉黑、用户封禁或批量下线。
    """

    try:
        resp = requests.post(
            webhook,
            json = {
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
        logger.exception("发送飞书安全告警失败: %s", e)
        return {
            "sent": False,
            "reason": "request_failed",
            "error": str(e),
        }
    
    if data.get("code", 0) != 0:
        return {
            "sent": False,
            "reason": "feishu_rejected",
            "error": data,
        }

    return {
        "sent": True,
        "response": data,
    }

    