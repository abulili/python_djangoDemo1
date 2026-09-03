from rest_framework import serializers
from .models import (AICallLog, PromptTemplate,Conversation, ConversationMessage, KnowledgeChunk, KnowledgeDocument, AiTraceStepLog)

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
        read_only_fields = ['id', 'call_time', 'user'] # 只读字段，前端可以查看，但不能修改，前端传了也会被忽略
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

# 怎么转JSON，前端json校验
class PromptTemplateSerializer(serializers.ModelSerializer):
    """Prompt template serializer."""

    class Meta:
        model = PromptTemplate
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_variables(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("variables must be a list")
        if not all(isinstance(item, str) for item in value): # 先看isinstance(item, str)判断是不是字符串，再for对每个元素判断，再all只有全部元素都是str才是True
            raise serializers.ValidationError("every variable name must be a string")
        return value

class ConversationMessageSerializer(serializers.ModelSerializer):
    """AI会话消息序列化器"""
    class Meta:
        model = ConversationMessage
        fields = ['id', 'role', 'content']
        read_only_fields = ['id', 'created_at']

class ConversationSerializer(serializers.ModelSerializer):
    """AI会话序列化器 (转json)"""
    messages = ConversationMessageSerializer(many=True, read_only=True)
    
    class Meta:
        model = Conversation
        fields = [
            "id",
            "conversation_id",
            "title",
            "created_at",
            "updated_at",
            "messages",
        ]
        read_only_fields = [
            "id",
            "conversation_id",
            "created_at",
            "updated_at",
            "messages",
        ]

class KnowledgeChunkSerializer(serializers.ModelSerializer):
    """知识库切片序列化器"""
    class Meta:
        model = KnowledgeChunk
        fields = ['id', 'content', 'chunk_index', 'created_at']
        read_only_fields = ['id', 'created_at']

class KnowledgeDocumentSerializer(serializers.ModelSerializer):
    """知识库文档序列化器"""
    chunks = KnowledgeChunkSerializer(many=True, read_only=True) # 返回文档时，顺便把这个文档下面的多个切片也返回出来
    chunk_count = serializers.SerializerMethodField() # 文档切了几段,是我自己写方法算出来的字段,KnowledgeDocument 表里没有 chunk_count 这一列。但是前端想看到
    # 然后 DRF 会自动找get_chunk_count
    # 字段名叫 chunk_count,方法名就叫 get_chunk_count

    class Meta:
        model = KnowledgeDocument
        fields = [
            'id',
            'title',
            'content',
            'created_at',
            'updated_at',
            'chunks',
            'chunk_count',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'chunks', 'chunk_count']

    def get_chunk_count(self, obj):
        return obj.chunks.count()

    def validate_content(self, value):
        if len(value.strip()) < 10: # strip() 是去掉首尾空格、换行
            raise serializers.ValidationError("文档内容至少10个字符")
        return value

class AiTraceStepLogSerializer(serializers.ModelSerializer):
    """RAG 步骤追踪日志序列化器"""
    class Meta:
        model = AiTraceStepLog
        fields = [
            "id",
            "trace_id",
            "conversation_id",
            "step",
            "query",
            "detail",
            "success",
            "error_message",
            "duration",
            "created_at",
        ]
        read_only_fields = fields
