from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

class UserRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, validators=[
        validate_password
    ]) # 密码强度验证
    """
    # 1. 密码不能与用户信息太相似（如用户名、邮箱）
    # 2. 密码长度至少 8 位（可配置）
    # 3. 密码不能是常见密码（如 '12345678'、'password'）
    # 4. 密码不能全是数字
    
    # 5. 密码不能全是字母 （需配置）
    """
    password2 = serializers.CharField(write_only=True, required=True, label='确认密码')

    # 内部配置类，定义模型行为和元数据
    class Meta:
        model = User # 指定使用的模型
        fields = ['id','username','email', 'password', 'password2'] # 序列化哪些字段
        extra_kwargs = { # 额外参数配置 Meta带的，为字段添加额外验证
            'email':{'required':True}, # 约等于直接定义字段 email = serializers.EmailField(required=True, max_length=100)
            'username':{'required':True},
        }
    
    def validate(self, attrs):
        # 验证密码是否一致 Python 会自动进行类型转换和比较，类型不同不相等
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({'password2':'密码不一致'})
        return attrs
    
    def create(self, validated_data):
        # 创建用户
        # 移除password2,不保存到数据库
        # validated_data 是一个字典（dict 对象），支持 pop() 方法。 pop 移除指定键，并返回其值
        validated_data.pop('password2')

        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
        )
        return user
