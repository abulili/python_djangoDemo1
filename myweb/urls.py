"""
URL configuration for myweb project.
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from rest_framework.routers import DefaultRouter
from ai_log.views import AICallLogViewSet, MyCustomAPIView
from rest_framework_simplejwt.views import TokenObtainPairView,TokenRefreshView


def handler404(request, exception):
    return JsonResponse({
        "code": 404,
        "message": "接口不存在，请检查url路径",
        "data": None
    }, status=404)


def handler500(request):
    return JsonResponse({
        "code": 500,
        "message": "服务器内部错误，请稍后重试",
        "data": None
    }, status=500)


router = DefaultRouter()
router.register(r'logs', AICallLogViewSet, basename='log')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
    path('api/my-custom/', MyCustomAPIView.as_view()),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    # djang的应用命名空间机制 'users.urls' 会被 Django 解析为：users/urls.py
    # 等价写法（如果 urls 不在根目录）
    # path('api/users/', include('users.urls', namespace='users')),
    # 因为users在INSTALLED_APPS 中注册
    # include() 将子 URL 配置合并到主 URL 配置中，urlpatterns += urls.urlpatterns
    path('api/users/',include('users.urls')),
]

handler404 = handler404
handler500 = handler500
