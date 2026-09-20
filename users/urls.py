from django.urls import path,include

from .views import (UserRegisterView, LogoutView, LoginEventViewSet, 
ForceLogoutUsersView, BanUsersView, UnbanUsersView, IPBlockRuleViewSet,
RequestRiskEventViewSet,CurrentUserView
)

from rest_framework.routers import DefaultRouter


router = DefaultRouter()
router.register(r'login-events', LoginEventViewSet, basename='login-event')
router.register(r'ip-block-rules', IPBlockRuleViewSet, basename='ip-block-rule')
router.register(r'request-risk-events', RequestRiskEventViewSet, basename='request-risk-event')

urlpatterns = [
    # as_view() 是 Django 类视图（Class-Based View）的入口方法，它将类转换为可调用的视图函数。
    path('register/', UserRegisterView.as_view(), name='register'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('force-logout/', ForceLogoutUsersView.as_view(), name='force-logout'),
    path('ban/', BanUsersView.as_view(), name='ban-users'),
    path('unban/', UnbanUsersView.as_view(), name='unban-users'),
    path("me/", CurrentUserView.as_view(), name="current-user"),
    path('', include(router.urls)),
]
    