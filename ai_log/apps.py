from django.apps import AppConfig

# app配置文件 告诉Django“这个App叫ai_log，名字不要写错，几乎不修改，Django会自动生成好

class AiLogConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ai_log'
