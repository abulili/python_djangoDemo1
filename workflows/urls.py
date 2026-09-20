from rest_framework.routers import DefaultRouter

from .views import (WorkflowRequestViewSet,WorkflowTemplateNodeViewSet, PaymentOrderViewSet,
 WorkflowTemplateViewSet)

router = DefaultRouter()
router.register(r"requests", WorkflowRequestViewSet, basename="workflow-request")
router.register(r"payments", PaymentOrderViewSet, basename="payment-order")
router.register(r"templates", WorkflowTemplateViewSet, basename="workflow-template")
router.register(r"template-nodes", WorkflowTemplateNodeViewSet, basename="workflow-template-node")

urlpatterns = router.urls