from rest_framework.routers import DefaultRouter

from .views import WorkflowRequestViewSet,WorkflowRequestViewSet, PaymentOrderViewSet, WorkflowTemplateViewSet

router = DefaultRouter()
router.register(r"requests", WorkflowRequestViewSet, basename="workflow-request")
router.register(r"payments", PaymentOrderViewSet, basename="payment-order")
router.register(r"templates", WorkflowTemplateViewSet, basename="workflow-template")

urlpatterns = router.urls