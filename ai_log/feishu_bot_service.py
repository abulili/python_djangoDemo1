import json
import requests
from django.conf import settings


class FeishuBotError(Exception):
    pass

def verify_feishu_event_token(payload):
    expected = getattr(settings, "FEISHU_VERIFICATION_TOKEN", "")

    if not expected:
        raise FeishuBotError("FEISHU_VERIFICATION_TOKEN未配置，拒绝处理飞书事件")

    header = payload.get("header") or {}
    actual = payload.get("token") or header.get("token")

    return actual == expected

def extract_feishu_text_message(payload):
    event = payload.get("event") or {}
    message = event.get("message") or {}
    sender = event.get("sender") or {}
    sender_id = sender.get("sender_id") or {}

    message_type = message.get("message_type", "")
    message_id = message.get("message_id", "")
    chat_id = message.get("chat_id", "")
    open_id = sender_id.get("open_id", "")

    if message_type != "text":
        return {
            "text": "",
            "message_type": message_type,
            "message_id": message_id,
            "chat_id": chat_id,
            "open_id": open_id,
        }

    raw_content = message.get("content") or "{}"

    try:
        content = json.loads(raw_content)
    except json.JSONDecodeError:
        content = {}

    return {
        "text": (content.get("text") or "").strip(),
        "message_type": message_type,
        "message_id": message_id,
        "chat_id": chat_id,
        "open_id": open_id,
    }

def get_tenant_access_token():
    if not settings.FEISHU_APP_ID or not settings.FEISHU_APP_SECRET:
        raise FeishuBotError("FEISHU_APP_ID或FEISHU_APP_SECRET未配置")

    response = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={
            "app_id": settings.FEISHU_APP_ID,
            "app_secret": settings.FEISHU_APP_SECRET,
        },
        timeout=8,
    )

    try:
        body = response.json()
    except ValueError as exc:
        raise FeishuBotError(f"飞书token接口返回非JSON: {response.text[:200]}") from exc

    if response.status_code >= 400 or body.get("code") != 0:
        raise FeishuBotError(f"获取tenant_access_token失败: {body}")

    return body["tenant_access_token"]

def send_feishu_text_message(open_id, text):
    if not getattr(settings, "FEISHU_EVENT_REPLY_ENABLED", True):
        return {
            "sent": False,
            "reason": "reply_disabled",
        }

    if not open_id:
        return {
            "sent": False,
            "reason": "missing_open_id",
        }

    token = get_tenant_access_token()

    response = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages",
        params={"receive_id_type": "open_id"},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "receive_id": open_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        },
        timeout=8,
    )

    try:
        body = response.json()
    except ValueError as exc:
        raise FeishuBotError(f"飞书发消息接口返回非JSON: {response.text[:200]}") from exc

    if response.status_code >= 400 or body.get("code") != 0:
        raise FeishuBotError(f"飞书发消息失败: {body}")

    return {
        "sent": True,
        "response": body,
    }