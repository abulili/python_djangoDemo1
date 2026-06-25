"""
URL configuration for myweb project.
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from rest_framework.routers import DefaultRouter
from ai_log.views import AICallLogViewSet, MyCustomAPIView


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
]

handler404 = handler404
handler500 = handler500
