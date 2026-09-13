from django.urls import path,include

from .views import UserRegisterView, LogoutView, LoginEventViewSet

from rest_framework.routers import DefaultRouter


router = DefaultRouter()
router.register(r'login-events', LoginEventViewSet, basename='login-event')

urlpatterns = [
    # as_view() 是 Django 类视图（Class-Based View）的入口方法，它将类转换为可调用的视图函数。
    path('register/', UserRegisterView.as_view(), name='register'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('', include(router.urls)),
]
    