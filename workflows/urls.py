from rest_framework.routers import DefaultRouter

from .views import WorkflowRequestViewSet

router = DefaultRouter()
router.register(r"requests", WorkflowRequestViewSet, basename="workflow-request")

urlpatterns = router.urls