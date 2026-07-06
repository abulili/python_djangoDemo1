from django.db import models
from django.contrib.auth.models import User
# Create your models here. 定义数据结构（数据库表）
# 写好了要用需要去settings的INSTALLED_APPS注册

# 创建一个叫AICallLog的类，继承自 Django 的模型功能
# 这么写就是继承，models.Model 是一个父类（Django 内置的），AICallLog 是一个子类（你自己写的）
class AICallLog(models.Model):

    # 关联用户
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="用户",
        null=True,
        blank=True
    )

    """记录每次调用AI的日志"""
    # 定义列-列名prompt-类型TextField-可读的名字，方便在后台管理界面显示verbose_name
    prompt = models.TextField(verbose_name="用户输入")
    # blank=True 表示在《表单》中可以不填，null=True 表示数据库里这个字段可以为空。对于AI还没返回结果的日志，这一列就是空的
    # blank=True 只针对后端校验规则，null=True针对数据库数据
    # 表单：Django 自带的 admin 后台 / Django 的 forms.Form / DRF（Django REST Framework）的序列化器
    # 对于 TextField 和 CharField，通常只设 blank=True，不设 null=True（因为Django会用空字符串 "" 表示空，而不是 NULL）
    # 记录AI回答了什么
    response = models.TextField(verbose_name="AI返回", blank=True, default='')
    # CharField 是短字符串，需要指定 max_length， 默认值gpt-3.5
    model_name = models.CharField(max_length=50,verbose_name="模型名称",default="gpt-3.5")
    # auto_now_add=True 是个很方便的设置：当这条记录第一次被创建时，自动把当前时间填进去，并且之后不再更改
    call_time = models.DateTimeField(auto_now_add=True, verbose_name="调用时间")
    duration = models.FloatField(verbose_name="耗时（秒）",default=0.0)
    success = models.BooleanField(verbose_name="是否成功",default=True)

    # 显示规则 在后台或命令行里打印这个对象时，会看到什么样的文字
    def __str__(self):
        # 显示“调用时间 - 用户输入的前20个字
        # f 告诉 Python，这个字符串里大括号 {} 包起来的变量名，要替换成它的实际值
        return f"{self.call_time} - {self.prompt[:20]}"
    
    # 表的“元数据”
    class Meta:
        # verbose_name 是表在后台显示的单数名（“AI调用日志”），verbose_name_plural 是复数名（中文环境通常都一样）
        # apple  apples
        # 用来在 admin 后台和 Django 的其他地方，更友好地显示模型的名字 AI调用日志 / "AI调用日志列表" 或 "多个AI调用日志"
        verbose_name = "AI调用日志"
        verbose_name_plural = "AI调用日志"
        ordering = ['-call_time']  # 默认按时间倒序
    
    # 定义这个对象的“字符串表示形式” <AICallLog: AICallLog object (1)> ==》 2025-06-25 14:30:00 - 帮我写一句关于Python的话
    """
    生效位置
    
    Django Admin 后台	日志列表里显示的文本
    Django Shell	print(log) 或直接输入 log 时显示
    关联对象的外键下拉框	选择关联对象时显示的内容
    """
    def __str__(self):
        return f"{self.call_time} - {self.prompt[:20]}"

# 创建app -> 定义模型 -> 执行迁移（数据库）-> 定义路由 -> 调用