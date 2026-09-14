from django.conf import settings
from django.core.cache import cache

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

    return event
