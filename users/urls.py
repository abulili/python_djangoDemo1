from django.urls import path

from .views import UserRegisterView

urlpatterns = [
    # as_view() 是 Django 类视图（Class-Based View）的入口方法，它将类转换为可调用的视图函数。
    path('register/', UserRegisterView.as_view(), name='register'),
]
    