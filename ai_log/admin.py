from django.contrib import admin

# Register your models here. 后台管理配置
# 把你定义的Model注册到Django自带的后台管理界面，以让你在浏览器里增删改查数据。

from .models import AICallLog

admin.site.register(AICallLog)