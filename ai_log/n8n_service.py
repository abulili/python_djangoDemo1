import requests
from django.conf import settings


class N8NServiceError(Exception):
    pass

def send_job_record_to_n8n(trace_id, log_id, record):
    if not settings.N8N_JOB_RECORD_WEBHOOK_URL:
        raise N8NServiceError("N8N_JOB_RECORD_WEBHOOK_URL未配置")

    payload = {
        "trace_id": trace_id,
        "log_id": log_id,
        "record": record,
    }

    response = requests.post(
        settings.N8N_JOB_RECORD_WEBHOOK_URL,
        json=payload,
        timeout=settings.N8N_REQUEST_TIMEOUT_SECONDS,
    )

    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text}

    if response.status_code >= 400:
        raise N8NServiceError(f"n8n调用失败: {response.status_code} {body}")

    return {
        "status_code": response.status_code,
        "body": body,
    }