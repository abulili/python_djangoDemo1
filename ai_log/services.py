import logging
from openai import OpenAI
from django.conf import settings
from django.core.cache import cache
import time

logger = logging.getLogger(__name__)

def calculate_cost(model_key, prompt_tokens,completion_tokens):
    # 根据模型计算费用
    pricing = {
        'deepseek':{ 'input': 0.001, 'output': 0.002 },
        # 'agnes':{ 'input': 0.00021, 'output': 0.00105 },
        'agnes':{ 'input': 0.0, 'output': 0.0 },
    }
    price = pricing.get(model_key, pricing.get('deepseek'))
    cost = (prompt_tokens / 1000 * price['input']) + (completion_tokens / 1000 * price['output'])
    return round(cost, 4)

def call_ai_service(prompt, model_key = None):
    # AI调用服务（供ViewSet和Task调用）
    if not model_key:
        model_key = getattr(settings,'DEFAULT_AI_MODEL', 'deepseek')
    model_config = settings.AI_MODELS.get(model_key)
    if not model_config:
        model_key = settings.DEFAULT_AI_MODEL
        model_config = settings.AI_MODELS[model_key]
    
    cache_key = f"ai_response:{model_key}:{prompt[:50]}"

    # 查缓存
    cached_result = cache.get(cache_key)
    if cached_result:
        logger.info(f"命中缓存，模型：{model_key}")
        return {
            'reply': cached_result,
            'prompt_tokens':0,
            'completion_tokens':0,
            'total_tokens':0,
            'cost': 0.0,
            'from_cache': True,
            'duration': 0.0,
        },True
    
    # 调用AI
    client = OpenAI(
        api_key = model_config['api_key'],
        base_url = model_config['base_url'],
    )
    start_time = time.time()
    try:
        response = client.chat.completions.create(
            model = model_config['default_model'],
            messages=[{'role':'user', 'content': prompt}],
            stream=False
        )
        ai_reply = response.choices[0].message.content

        duration = time.time() - start_time

        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        total_tokens = usage.total_tokens if usage else 0
        cost = calculate_cost(model_key, prompt_tokens,completion_tokens)

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
        },True
    
    except Exception as e:
        logger.error(f"AI调用失败（{model_key}）:{e}")
        return {
            'error': str(e),
            'reply':f"AI调用失败：{str(e)}"
        },False