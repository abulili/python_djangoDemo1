from rest_framework import serializers
from .models import AICallLog

# 序列化器 把 AICallLog 对象转换成JSON，或者把JSON转换成 AICallLog 对象
class AICallLogSerializer(serializers.ModelSerializer):
    """AI调用日志序列化器"""
    # 这里的class Meta和models.py的class Meta不一样
    # DRF 在底层读取
    # 在 DRF 的 serializers.ModelSerializer 里，class Meta 的作用是告诉序列化器：“我要为哪个模型（Model）自动生成序列化规则”
    class Meta:
        # 用来读取是什么模型有哪些字段，需要序列化什么字段
        model = AICallLog
        fields = '__all__' # 包含所有字段, 也可以[]来指定字段读写
        read_only_fields = ['id', 'call_time'] # 只读字段，前端可以查看，但不能修改，前端传了也会被忽略
    def validate_prompt(self, value):
        """校验用户输入：至少2个字符，最多1000个字符"""
        if len(value) < 2:
            raise serializers.ValidationError("用户输入至少2个字符")
        if len(value) > 1000:
            raise serializers.ValidationError("用户输入不能超过1000个字符")
        return value

    def validate_duration(self, value):
        """校验耗时：不能为负数，不能超过60秒"""
        if value < 0:
            raise serializers.ValidationError("耗时不能为负数")
        if value > 60:
            raise serializers.ValidationError("耗时不能超过60秒")
        return value

    def validate(self, data):
        """对象级校验：成功时 response 不能为空"""
        if data.get('success') is True and not data.get('response'):
            raise serializers.ValidationError("调用成功时，response不能为空")
        return data