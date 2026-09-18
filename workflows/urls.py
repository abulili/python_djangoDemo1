from rest_framework.routers import DefaultRouter

from .views import WorkflowRequestViewSet,WorkflowRequestViewSet, PaymentOrderViewSet

router = DefaultRouter()
router.register(r"requests", WorkflowRequestViewSet, basename="workflow-request")
router.register(r"payments", PaymentOrderViewSet, basename="payment-order")

urlpatterns = router.urls