import logging
from openai import OpenAI
from django.conf import settings
from django.core.cache import cache
import time
import json
from .models import PromptTemplate,Conversation, ConversationMessage
from decimal import Decimal, ROUND_HALF_UP
from datetime import timezone as datetime_timezone

logger = logging.getLogger(__name__)

# 最大保留消息数
MAX_HISTORY = 20

def get_coversation_history(conversation_id, user=None):
    """
    获取会话上下文：
    1. 优先从 Redis 读，速度快
    2. Redis 没有时，从数据库恢复最近 MAX_HISTORY 条
    3. 恢复后写回 Redis，方便下一次请求
    """
    if not conversation_id:
        return []

    # 从redis获取对话历史
    key = f"coversation:{conversation_id}"
    history = cache.get(key)
    print('history', history)
    if history:
        return json.loads(history)

    if not user:
        return []
    
    # filter(...) 返回的是一个查询集合，不是单个对象
    conversation = Conversation.objects.filter(
        conversation_id=conversation_id,
        user=user, # 从 Redis 读的时候，只需要 conversation_id。但从数据库兜底时，必须加用户限制：
    ).first()
    # 不用 .first() 的话，conversation 是一个 QuerySet，你不能直接当成一条会话来用。
    if not conversation:
        return []

    messages = list(
        conversation.messages
                    .order_by('-created_at')[:MAX_HISTORY] # 短横线 - 表示倒序,不加-就是正序 相当于[:20]
                    .values("role", "content")
    )

    messages.reverse()

    cache.set(
        key,
        json.dumps(messages, ensure_ascii=False),
        timeout=3600*24
    )

    return messages

def save_conversation_history(conversation_id, messages):
    # 保留对话历史到redis，保留最近的MAX_HISTORY条
    key = f"coversation:{conversation_id}"
    if len(messages) > MAX_HISTORY:
        messages = messages[-MAX_HISTORY:]
    cache.set(key, json.dumps(messages),timeout=3600*24) # 保留24小时

def save_conversation_messages_to_db(conversation_id, user, user_content, assistant_content):
    """
    一轮对话保存到数据库
    """
    if not conversation_id or not user:
        return None
    
    title = user_content[:30] if user_content else ""

    # 如果这个 conversation_id 对应的会话已经存在，就拿出来；如果不存在，就创建一个新的
    """
    get_or_create 等价于：
    try:
        conversation = Conversation.objects.get(conversation_id=conversation_id)
        created = False
    except Conversation.DoesNotExist:
        conversation = Conversation.objects.create(
            conversation_id=conversation_id,
            user=user,
            title=title,
        )
        created = True
    """
    conversation, created = Conversation.objects.get_or_create(
        conversation_id=conversation_id, # 查找条件（放在外面的就是查找条件，如果不加default，直接就是）
        defaults={ # defaults 只在“创建新会话”时生效： 创建时才用的默认值
            "user": user,
            "title": title,
        }
    )
    if conversation.user_id != user.id:
        raise PermissionError("无权访问该对话")
    
    if not conversation.title and title:
        conversation.title = title
        conversation.save(update_fields=['title', 'updated_at'])

    ConversationMessage.objects.create(
        conversation=conversation,
        role='user',
        content=user_content or "",
    )

    ConversationMessage.objects.create(
        conversation=conversation,
        role='assistant',
        content=assistant_content or "",
    )

    conversation.save(update_fields=['updated_at'])

    return conversation
    

DEEPSEEK_PRICING = {
    "deepseek": { # 默认是deepseek-v4-flash
        "off_peak": {
            "cache_hit_input": Decimal("0.05"),
            "cache_miss_input": Decimal("1.5"),
            "output": Decimal("4.5"),
        },
        "peak": {
            "cache_hit_input": Decimal("0.10"),
            "cache_miss_input": Decimal("3.0"),
            "output": Decimal("9.0"),
        },
    },
    "deepseek-v4-flash": {
        "off_peak": {
            "cache_hit_input": Decimal("0.05"),
            "cache_miss_input": Decimal("1.5"),
            "output": Decimal("4.5"),
        },
        "peak": {
            "cache_hit_input": Decimal("0.10"),
            "cache_miss_input": Decimal("3.0"),
            "output": Decimal("9.0"),
        },
    },
    "deepseek-v4-pro": {
        "off_peak": {
            "cache_hit_input": Decimal("0.15"),
            "cache_miss_input": Decimal("4.5"),
            "output": Decimal("13.5"),
        },
        "peak": {
            "cache_hit_input": Decimal("0.30"),
            "cache_miss_input": Decimal("9.0"),
            "output": Decimal("27.0"),
        },
    },
}

def get_usage_value(usage, field_name, default=0):
    if not usage:
        return default
    if isinstance(usage, dict):
        return usage.get(field_name, default) or default

    return getattr(usage, field_name, default) or default

def get_deepseek_price_period(now=None):
    from django.utils import timezone

    now = now or timezone.now()
    beijing_now = now.astimezone(datetime_timezone.utc).astimezone()

    hour = beijing_now.hour

    if 9 <= hour < 12 or 14 <= hour < 18:
        return 'peak'
    else:
        return 'off_peak'

def calculate_cost(model_key, prompt_tokens,completion_tokens,usage=None, real_model_name=None):
    # 根据模型计算费用
    if model_key == 'agnes':
        return 0.0
    if model_key == 'deepseek':
        model_name = real_model_name or "deepseek-v4-flash"
        price_config = DEEPSEEK_PRICING.get(model_name, DEEPSEEK_PRICING.get("deepseek-v4-flash"))
        
        period = get_deepseek_price_period()
        price = price_config[period]

        cache_hit_tokens = get_usage_value(usage, 'prompt_cache_hit_tokens', 0)
        cache_miss_tokens = get_usage_value(usage, 'prompt_cache_miss_tokens', 0)
        if cache_hit_tokens + cache_miss_tokens == 0:
            cache_miss_tokens = prompt_tokens
        
        cost = (
            Decimal(cache_hit_tokens) / Decimal(1000000) * price["cache_hit_input"] + Decimal(cache_miss_tokens) / Decimal(1000000) * price["cache_miss_input"]
            + Decimal(completion_tokens) / Decimal(1000000) * price["output"]
        )

        return float(cost.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP))
    return 0.0


def call_ai_service(prompt, model_key = None, conversation_id=None, template_name=None, template_vars=None, user=None):
    # AI调用服务（供ViewSet和Task调用）
    
    # 如果指定了模板，用模板渲染prompt
    if template_name:
        print('template_name', template_name)
        print('template_vars', template_vars)
        rendered_prompt = get_prompt(template_name, template_vars)
        if rendered_prompt:
            prompt = rendered_prompt
        else:
            logger.warning(f"模板{template_name}不存在或未启用")
    print('prompt', prompt)
    if not model_key:
        model_key = getattr(settings,'DEFAULT_AI_MODEL', 'deepseek')
    model_config = settings.AI_MODELS.get(model_key)
    if not model_config:
        model_key = settings.DEFAULT_AI_MODEL
        model_config = settings.AI_MODELS[model_key]
    
    cache_key = f"ai_response:{model_key}{conversation_id}:{prompt[:50]}"
    # 消息列表
    messages = []
    print('messages1', messages, conversation_id)
    # 如果有会话ID，加载历史对话
    if conversation_id:
        history = get_coversation_history(conversation_id, user=user)
        messages = history.copy()

    # 追加当前用户问题
    messages.append({"role": "user","content": prompt})
    print('messages2', messages)
    # 查缓存
    cached_result = cache.get(cache_key)
    if cached_result:
        logger.info(f"命中缓存，模型：{model_key}")
        messages.append({"role": "assistant", "content": cached_result})
        if conversation_id:
            save_conversation_history(conversation_id, messages)
            save_conversation_messages_to_db(
                conversation_id=conversation_id,
                user=user,
                user_content=prompt,
                assistant_content=cached_result,
            )
        return {
            'reply': cached_result,
            'prompt_tokens':0,
            'completion_tokens':0,
            'total_tokens':0,
            'cost': 0.0,
            'from_cache': True,
            'duration': 0.0,
        },True
    print('messages3', messages)
    # 调用AI
    client = OpenAI(
        api_key = model_config['api_key'],
        base_url = model_config['base_url'],
    )
    start_time = time.time()

    print('messages4', messages)

    try:
        response = client.chat.completions.create(
            model = model_config['default_model'],
            messages=messages,
            stream=False
        )
        ai_reply = response.choices[0].message.content

        duration = time.time() - start_time

        # 把 AI 回复追加到历史
        messages.append({"role": "assistant", "content": ai_reply})
        if conversation_id:
            save_conversation_history(conversation_id, messages)
            save_conversation_messages_to_db(
                conversation_id=conversation_id,
                user=user,
                user_content=prompt,
                assistant_content=ai_reply,
            )

        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        total_tokens = usage.total_tokens if usage else 0
        cost = calculate_cost(model_key, prompt_tokens,completion_tokens,usage=usage,real_model_name=model_config["default_model"],)

        cache.set(cache_key, ai_reply, timeout = 3600)
        logger.info(f"AI调用成功，模型：{model_key}，总Token：{total_tokens}")

        return {
            'reply': ai_reply,
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': total_tokens,
            'cost': cost,
            'from_cache': False,
            'duration': round(duration, 2),
            'conversation_id': conversation_id,
        },True
    
    except Exception as e:
        logger.error(f"AI调用失败（{model_key}）:{e}")
        return {
            'error': str(e),
            'reply':f"AI调用失败：{str(e)}"
        },False

def get_prompt(template_name=None, variables=None):
    """
    根据模板名称和变量获取渲染后的 prompt
    模板示例："你是{role}，请帮我{task}"
    variables = {"role": "代码专家", "task": "写一个快速排序"}
    → "你是代码专家，请帮我写一个快速排序"
    """
    try:
        template = PromptTemplate.objects.get(name=template_name, is_active=True)
        content = template.content
        variables = variables or {}
        try:
            content = content.format(**variables)
        except KeyError as e:
            missing_key = e.args[0]
            raise ValueError(f"缺少模板变量: {missing_key}")
        return content
    except PromptTemplate.DoesNotExist:
        return None

def render_prompt_content(content, varibles=None):
    # 直接渲染prompt内容，不查数据库
    if varibles:
        return content.format(**varibles)
    return content
    
