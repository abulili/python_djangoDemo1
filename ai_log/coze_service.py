import json
import uuid
import requests
from django.conf import settings

class CozeServiceError(Exception):
    # 这个类暂时不额外写内容，只继承 Exception 的能力
    # 自定义内容
    pass

def _extract_json(text):
    text = (text or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CozeServiceError(f"Coze返回不是合法JSON: {text[:300]}") from exc

def _deep_find_key(obj, target_key):
    if isinstance(obj, dict):
        if target_key in obj:
            return obj[target_key]

        for value in obj.values():
            found = _deep_find_key(value, target_key)
            if found is not None:
                return found

    elif isinstance(obj, list):
        for item in obj:
            found = _deep_find_key(item, target_key)
            if found is not None:
                return found

    return None


def _deep_find_ai_content(obj):
    if isinstance(obj, dict):
        messages = obj.get("messages")
        if isinstance(messages, list):
            for msg in reversed(messages):
                if not isinstance(msg, dict):
                    continue

                if msg.get("type") == "ai" and msg.get("content"):
                    return msg["content"]

                if msg.get("role") in ("assistant", "ai") and msg.get("content"):
                    return msg["content"]

        if obj.get("type") == "ai" and obj.get("content"):
            return obj["content"]

        if obj.get("role") in ("assistant", "ai") and obj.get("content"):
            return obj["content"]

        for value in obj.values():
            found = _deep_find_ai_content(value)
            if found:
                return found

    elif isinstance(obj, list):
        for item in reversed(obj):
            found = _deep_find_ai_content(item)
            if found:
                return found

    return ""

def _read_stream(response):
    answer_parts = []
    token_cost = {}
    time_cost_ms = 0
    raw_events = []

    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line:
            continue

        line = raw_line.strip()
        raw_events.append(line)

        # 只处理 data 行，跳过 event: message
        if not line.startswith("data:"):
            continue

        data_text = line[5:].strip()

        if data_text in ("[DONE]", "DONE"):
            break

        try:
            event = json.loads(data_text)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type")
        content = event.get("content") or {}

        if event_type == "answer":
            chunk = content.get("answer")
            if chunk:
                answer_parts.append(chunk)

        elif event_type == "message_end":
            message_end = content.get("message_end") or {}

            code = str(message_end.get("code", "0"))
            if code != "0":
                raise CozeServiceError(message_end.get("message", "Coze执行失败"))

            token_cost = message_end.get("token_cost") or {}
            time_cost_ms = message_end.get("time_cost_ms") or 0

        elif event_type == "error":
            error = content.get("error") or {}
            raise CozeServiceError(error.get("error_msg", "Coze执行错误"))

    answer_text = "".join(answer_parts).strip()

    if not answer_text:
        raise CozeServiceError(
            "Coze没有返回AI消息内容，原始返回前5行: "
            + json.dumps(raw_events[:5], ensure_ascii=False)
        )

    return answer_text, token_cost, time_cost_ms

def call_coze_job_record_agent(prompt, user_id=None, trace_id=None, session_id=None):
    if not prompt:
        raise CozeServiceError("prompt不能为空")
    if not settings.COZE_API_BASE_URL:
        raise CozeServiceError("COZE_API_BASE_URL未配置")
    if not settings.COZE_API_KEY:
        raise CozeServiceError("COZE_API_KEY未配置")
    if not settings.COZE_PROJECT_ID:
        raise CozeServiceError("COZE_PROJECT_ID未配置")

    trace_id = trace_id or uuid.uuid4().hex
    session_id = session_id or f"job_record_{user_id or 'anonymous'}"

    payload = {
        "content": {
            "query": {
                "prompt": [
                    {
                        "type": "text",
                        "content": {
                            "text": prompt
                        }
                    }
                ]
            }
        },
        "type": "query",
        "session_id": session_id,
        "project_id": project_id,
    }

    response = requests.post(
        settings.COZE_API_BASE_URL + "/stream_run",
        headers={
            "Authorization": f"Bearer {settings.COZE_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        json=payload,
        stream=True,
        timeout=settings.COZE_REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code >= 400:
        raise CozeServiceError(f"Coze调用失败: {response.status_code} {response.text[:300]}")

    answer_text, token_cost, time_cost_ms = _read_stream(response)
    record = _extract_json(answer_text)

    return {
        "trace_id": trace_id,
        "record": record,
        "answer_text": answer_text,
        "token_cost": token_cost,
        "time_cost_ms": time_cost_ms,
    }