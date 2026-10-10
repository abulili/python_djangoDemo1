from rest_framework.routers import DefaultRouter
from .views import MaterialAssetViewSet, VideoJobViewSet

router = DefaultRouter()
router.register(r"assets", MaterialAssetViewSet, basename="novel-video-asset")
router.register(r"jobs", VideoJobViewSet, basename="novel-video-job")

urlpatterns = router.urls