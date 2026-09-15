from django.conf import settings
from django.core.cache import cache

from .models import IPBlockRule

def get_client_ip(request):
    if not request:
        return None

    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR")

def get_risk_type(status_code):
    if status_code == 401:
        return "auth_failed"
    if status_code == 403:
        return "permission_denied"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "server_error"
    return ""

def record_request_risk_event(request, response):
    if not getattr(settings, "SECURITY_RISK_EVENT_ENABLED", True):
        return None
    
    status_code = getattr(response, "status_code", 0)
    risk_type = get_risk_type(status_code)

    if not risk_type:
        return None

    from .models import RequestRiskEvent

    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        user = None

    ip_address = get_client_ip(request)
    path = request.path
    method = request.method

    window_seconds = getattr(settings, "SECURITY_RISK_WINDOW_SECONDS", 60)
    threshold = getattr(settings, "SECURITY_RISK_THRESHOLD", 10)

    identity = user.id if user else ip_address or "unknown"
    cache_key = f"security_risk:{risk_type}:{identity}:{path}:{method}"

    added = cache.add(cache_key, 0, timeout=window_seconds)
    current_count = cache.incr(cache_key)

    if current_count < threshold:
        return None

    event = RequestRiskEvent.objects.create(
        user=user,
        ip_address=ip_address,
        path=path[:255],
        method=method,
        status_code=status_code,
        risk_type=risk_type,
        count=current_count,
        window_seconds=window_seconds,
        detail={
            "threshold": threshold,
            "cache_key": cache_key,
        },
    )

    try:
        from .notifications import SecurityNotificationContext, send_feishu_security_notification

        notify_result = send_feishu_security_notification(SecurityNotificationContext(
            risk_type=risk_type,
            ip_address=ip_address or "",
            user_id=user.id if user else None,
            username=user.username if user else "",
            path=path,
            method=method,
            status_code=status_code,
            count=current_count,
            window_seconds=window_seconds,
            detail=event.detail,
        ))
    except Exception as e:
        notify_result = {
            "sent": False,
            "reason": "notification_exception",
            "error": str(e),
        }

    event.notify_result = notify_result
    event.save(update_fields=["notify_result"])

    # 自动处理
    auto_action_result = None

    try: 
        auto_action_result = apply_security_auto_action(event)
    except Exception as e:
        auto_action_result = {
            "handled": False,
            "reason": "auto_action_exception",
            "error": str(e),
        }
    
    detail = event.detail or {}
    detail["auto_action_result"] = auto_action_result
    event.detail = detail
    event.save(update_fields=["detail"])

    return event

def apply_security_auto_action(event):
    if not getattr(settings, "SECURITY_AUTO_ACTION_ENABLED", False):
        return {
            "handled": False,
            "reason": "auto_action_disabled",
        }

    if not getattr(settings, "SECURITY_AUTO_BLOCK_IP_ENABLED", False):
        return {
            "handled": False,
            "reason": "auto_block_ip_disabled",
        }

    block_risk_types = getattr(settings, "SECURITY_AUTO_BLOCK_IP_RISK_TYPES", [])

    if event.risk_type not in block_risk_types:
        return {
            "handled": False,
            "reason": "risk_type_not_allowed",
            "risk_type": event.risk_type,
        }

    if not event.ip_address:
        return {
            "handled": False,
            "reason": "missing_ip",
        }

    rule, created = IPBlockRule.objects.get_or_create(
        ip_address=event.ip_address,
        defaults={
            "reason": f"自动风控拉黑：{event.risk_type}，{event.count} 次 / {event.window_seconds} 秒",
            "is_active": True,
        },
    )

    if not created and not rule.is_active:
        rule.is_active = True
        rule.reason = f"自动风控重新拉黑：{event.risk_type}，{event.count} 次 / {event.window_seconds} 秒"
        rule.save(update_fields=["is_active", "reason"])

    return {
        "handled": True,
        "action": "block_ip",
        "ip_address": event.ip_address,
        "created": created,
    }

    