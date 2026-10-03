import json
import uuid

from .coze_service import call_coze_job_record_agent
from .models import AICallLog, AiTraceStepLog
from .n8n_service import N8NServiceError, send_job_record_to_n8n

def process_job_record_prompt(*, prompt, user=None, trace_id=None, source="api", source_detail=None):
    trace_id = trace_id or uuid.uuid4().hex
    source_detail = source_detail or {}

    result = call_coze_job_record_agent(
        prompt=prompt,
        user_id=user.id if user else source_detail.get("user_id", "anonymous"),
        trace_id=trace_id,
    )

    token_cost = result.get("token_cost") or {}
    record = result["record"]
    duration = (result.get("time_cost_ms") or 0) / 1000

    log = AICallLog.objects.create(
        user=user,
        prompt=prompt,
        response=json.dumps(record, ensure_ascii=False),
        model_name="coze-job-record-agent",
        success=True,
        trace_id=trace_id,
        conversation_id=record.get("company", ""),
        prompt_tokens=token_cost.get("input_tokens", 0),
        completion_tokens=token_cost.get("output_tokens", 0),
        total_tokens=token_cost.get("total_tokens", 0),
        duration=duration,
    )

    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=record.get("company", ""),
        step="external_coze_extract",
        query=prompt,
        detail={
            "provider": "coze",
            "source": source,
            "source_detail": source_detail,
            "record": record,
            "token_cost": token_cost,
            "time_cost_ms": result.get("time_cost_ms"),
            "log_id": log.id,
        },
        success=True,
        duration=duration,
    )

    n8n_result = None

    try:
        n8n_result = send_job_record_to_n8n(
            trace_id=trace_id,
            log_id=log.id,
            record=record,
        )

        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=record.get("company", ""),
            step="n8n_job_record_webhook",
            query=prompt,
            detail={
                "provider": "n8n",
                "webhook_result": n8n_result,
            },
            success=True,
        )

    except N8NServiceError as e:
        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=record.get("company", ""),
            step="n8n_job_record_webhook",
            query=prompt,
            detail={"provider": "n8n"},
            success=False,
            error_message=str(e),
        )

    return {
        "trace_id": trace_id,
        "log_id": log.id,
        "record": record,
        "n8n_result": n8n_result,
    }

