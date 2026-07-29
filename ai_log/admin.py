from django.contrib import admin

# Register your models here. 后台管理配置
# 把你定义的Model注册到Django自带的后台管理界面，以让你在浏览器里增删改查数据。

from .models import AICallLog, PromptTemplate

admin.site.register(AICallLog)

# 注册模板管理
@admin.register(PromptTemplate) # Django Admin 的注册装饰器,作用是把 PromptTemplate 模型注册到 Django 的后台管理界面。
class PromptTemplateAdmin(admin.ModelAdmin): # 自定义管理类
    list_display = ['name', 'description', 'is_active', 'created_at'] # 列表页显示哪些字段
    search_fields = ['name', 'description']  # 搜索框可以搜哪些字段