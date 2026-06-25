import os
import django

# 让这个脚本能用Django的环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myweb.settings')
django.setup()

from ai_log.models import AICallLog

# 这里写你的测试代码

# 列表推导式
# 取出所有日志的prompts
all_prompts = [log.prompt for log in AICallLog.objects.all()]
print(all_prompts)

# 取出耗时大于0.1秒的日志id
# AICallLog.objects.all()返回的是一个 QuerySet（查询集），你可以把它理解成一个“装着所有 AICallLog 对象的列表”。
# AICallLog：数据库里那张表的“蓝图”
# objects：Django 自动给你的“数据库管理员”
# all()：管理员给你的命令：“把表里所有的记录都拿出来”
# 返回值：一个装着 N 个 AICallLog 对象 的容器（QuerySet）
slow_prompts = [log.id for log in AICallLog.objects.all() if log.duration > 0.1]
print(slow_prompts)

# 返回字典列表
#[(可选返回形式)，for xx in xx]
log_summaries = [
    {"id":log.id, "short_prompt": log.prompt[:10]}
    for log in AICallLog.objects.all()
]
print(log_summaries)

# 导入方式
# 导入整个模块
import ai_log.models
log1 = ai_log.models.AICallLog(prompt="测试1")
# 导入具体的类
import ai_log.models.AICallLog
log2 = AICallLog(prompt="测试1")
# 导入并重命名（避免命名冲突）
from ai_log.models import AICallLog as Log
log3 = Log(prompt="测试1")
# 导入全部，容易命名冲突
from ai_log.models import *
log4 = AICallLog(prompt="测试1")


# # 定义简单函数
# def get_status(duration):
#     if duration > 1.0:
#         return '慢'
#     elif duration > 0.5:
#         return '中'
#     else:
#         return '快'
    
# # 调用
# print(get_status(0.4))

# # 带默认参数的函数
# def create_log(prompt, duration=0.0,success=True):
#     # 模拟创建日志
#     return {"prompt": prompt, "duration": duration, "success": success}

# print(create_log('aaa', 0.5,'04'))

# # 异常处理  不清楚什么异常可以先写 except Exception as e，把具体异常类型打印出来 print(f"异常类型：{type(e).__name__}，信息：{e}")，然后改成对应的
# def call_ai_safely(prompt):
#     try:
#         # 模拟调用，故意出错
#         # a = 1 / 0
#         if len(prompt) > 100:
#             raise ValueError("提示词太长")
#         return "AI返回的结果"
#     except ValueError as e:
#         print(f"参数错误：{e}")
#         return None
#     except Exception as e:
#         print(f"其他错误: {e}")
#         # 没有显式 return，Python函数如果执行到最后没有 return，会默认返回 None
#     finally: 
#         print('最后的最后')

# print(call_ai_safely("你好"))
# print(call_ai_safely("你"*101))

# # !执行顺序
# # return None
# #   ↓
# # 执行 finally 里的 print
# #   ↓
# # 函数真正返回 None
# #   ↓
# # 外层的 print 打印 None

# # 实际queryset上使用异常处理
# from ai_log.models import AICallLog

# def get_log_safely(log_id):
#     try:
#         log = AICallLog.objects.get(id = log_id)
#         return log
#     except AICallLog.DoesNotExist:
#         print(f"ID为{log_id}的日志不存在")
#         return None
#     except Exception as e:
#         print(f"查询出错：{e}")
#         return None
    
# # 测试
# print(get_log_safely(1))  # 如果id=1存在
# print(get_log_safely(999))  # 不存在，触发DoesNotExist
    

# # 变量和类型
# prompt_text = "帮我写个Python计划"
# duration_value = 0.5
# is_success = True

# print(type(prompt_text))  # <class 'str'>
# print(type(duration_value))  # <class 'float'>
# print(type(is_success))  # <class 'bool'>

# # 列表和字典
# log_ids = [1,2,3]
# log_data = {
#     "prompt": "你好",
#     "response":"你好呀",
#     "duration":0.3,
#     "success": True
# }

# # if 判断
# if duration_value > 1.0:
#     print('调用太慢')
# elif duration_value > 0.5:
#     print('速度一般')
# else:
#     print('速度很快')

# # for 循环
# for log_id in log_ids:
#     print(f"日志ID: {log_id}")

# # 从数据库里查数据
# from ai_log.models import AICallLog
# all_logs = AICallLog.objects.all() # QuerySet，类似列表
# for log in all_logs:
#     print(f"用户问：{log.prompt}") # 打印每条记录的prompt字段
