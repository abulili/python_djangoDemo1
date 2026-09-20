from django.shortcuts import render

# Create your views here.
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (PaymentOrder, WorkflowOperationLog, WorkflowRequest, WorkflowTask,WorkflowTemplate,
WorkflowTemplateNode)
from .serializers import (
    CreatePaymentOrderSerializer,
    PaymentActionSerializer,
    PaymentOrderSerializer,
    WorkflowActionSerializer,
    WorkflowRequestSerializer,
    WorkflowTemplateSerializer,
    WorkflowTemplateNodeSerializer,
)
import uuid

def get_default_template():
    # 去数据库里找 code=payment_approval 且启用中的流程模板,找不到返回None
    return WorkflowTemplate.objects.filter(
        code="payment_approval",
        is_active=True,
    ).first()


def get_approver_from_workflow(workflow, approver_field):
    if approver_field == WorkflowTemplateNode.APPROVER_FIELD_CURRENT:
        return workflow.current_approver

    if approver_field == WorkflowTemplateNode.APPROVER_FIELD_SECOND:
        return workflow.second_approver

    return None

def is_node_applicable(workflow, node):
    if node.min_amount is None:
        return True

    if workflow.amount is None:
        return False

    return workflow.amount >= node.min_amount

class WorkflowRequestViewSet(viewsets.ModelViewSet):
    serializer_class = WorkflowRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = WorkflowRequest.objects.select_related(
            "applicant",
            "current_approver",
            "second_approver",
            "payment_order",
        ).prefetch_related(
            "operation_logs",
            "tasks",
        )
        # prefetch_related：提前把“一对多/多对多”的关联数据查出来，减少数据库查询次数
        # 查工作流列表时，顺便把每个工作流的操作日志也批量查出来

        if user.is_superuser:
            return queryset

        # 普通用户只能看到：自己发起的申请或者需要自己审批的申请
        # Q(...) | Q(...) 里的 | 是“或者”。distinct() 是去重
        return queryset.filter(
            Q(applicant=user) |
            Q(current_approver=user) |
            Q(second_approver=user) |
            Q(tasks__approver=user)
        ).distinct()

    def perform_create(self, serializer):
        workflow = serializer.save(applicant=self.request.user)

        WorkflowOperationLog.objects.create(
            workflow=workflow,
            operator=self.request.user,
            action=WorkflowOperationLog.ACTION_CREATE,
            from_status="",
            to_status=workflow.status,
            snapshot={
                "title": workflow.title,
                "request_type": workflow.request_type,
                "amount": str(workflow.amount) if workflow.amount is not None else None,
            },
        )
    
    @action(detail=False, methods=["get"], url_path="mine")
    def mine(self, request):
        queryset = self.get_queryset().filter(applicant=request.user)
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "code": 200,
            "message": "ok",
            "data": serializer.data,
        }, status=status.HTTP_200_OK)

    # 因为pending分为两类，第一类是：我的申请/mine，第二类是待我审批/pending
    @action(detail=False, methods=["get"], url_path="pending")
    def pending(self, request):
        queryset = self.get_queryset().filter(
            tasks__approver=request.user,
            tasks__status=WorkflowTask.STATUS_PENDING,
            status=WorkflowRequest.STATUS_PENDING,
        ).distinct()
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "code": 200,
            "message": "ok",
            "data": serializer.data,
        })

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        """
        1. 根据 id 找到 workflow
        2. 判断当前用户是不是申请人
        3. 判断当前状态是不是 draft
        4. 校验请求参数
        5. 开启事务
        6. 把状态从 draft 改成 pending
        7. 写 submitted_at
        8. 如果没有审批人，临时默认自己
        9. 保存 workflow
        10. 写一条操作日志 submit
        11. 返回最新数据
        """
        workflow = self.get_object()

        if workflow.applicant_id != request.user.id:
            return Response({
                "code": 403,
                "message": "只有申请人可以提交申请", # 谁创建的申请谁才可以提交
                "data": None,
            }, status=status.HTTP_403_FORBIDDEN)

        # draft：申请已经创建了，但还没有正式交给审批人处理。
        if workflow.status != WorkflowRequest.STATUS_DRAFT:
            return Response({
                "code": 400,
                "message": "只能提交草稿状态的申请",
                "data": None,
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = WorkflowActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if workflow.current_approver is None:
            return Response({
                "code": 400,
                "message": "请先指定审批人",
                "data": None,
            }, status=status.HTTP_400_BAD_REQUEST)

       
       
        template = workflow.template or get_default_template()

        if template is None:
            return Response({
                "code": 400,
                "message": "未找到可用流程模板",
                "data": None,
            }, status=status.HTTP_400_BAD_REQUEST)

        # 找模板的第一个节点。
        first_node = None

        for node in template.nodes.filter(is_active=True).order_by("node_order"):
            # 以及审批min_amount = None
            if is_node_applicable(workflow, node):
                first_node = node
                break

        if first_node is None:
            return Response({
                "code": 400,
                "message": "流程模板没有可用节点",
                "data": None,
            }, status=status.HTTP_400_BAD_REQUEST)

        first_approver = get_approver_from_workflow(workflow, first_node.approver_field)

        if first_approver is None:
            return Response({
                "code": 400,
                "message": "请先指定审批人",
                "data": None,
            }, status=status.HTTP_400_BAD_REQUEST)
        # 开启事务
        # 保证：状态更新成功 + 操作日志写入成功 
        # 要么都成功，要么都失败。
        with transaction.atomic():
            old_status = workflow.status

            workflow.template = template
            workflow.status = WorkflowRequest.STATUS_PENDING
            workflow.submitted_at = timezone.now()
            workflow.save(update_fields=[
                "template",
                "status",
                "submitted_at",
                "updated_at",
            ])

            WorkflowTask.objects.create(
                workflow=workflow,
                node_name=first_node.node_name,
                node_order=first_node.node_order,
                approver=first_approver,
            )

            WorkflowOperationLog.objects.create(
                workflow=workflow,
                operator=request.user,
                action=WorkflowOperationLog.ACTION_SUBMIT,
                from_status=old_status,
                to_status=workflow.status,
                comment=serializer.validated_data["comment"],
            )

        return Response({
            "code": 200,
            "message": "提交成功",
            "data": self.get_serializer(workflow).data,
        })

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        workflow = self.get_object()

        if workflow.status != WorkflowRequest.STATUS_PENDING:
            return Response({
                "code": 400,
                "message": "只有待审批状态可以通过",
                "data": None,
            }, status=status.HTTP_400_BAD_REQUEST)

        current_task = workflow.tasks.filter(
            status=WorkflowTask.STATUS_PENDING,
        ).order_by("node_order").first()

        if current_task is None:
            return Response({
                "code": 400,
                "message": "当前没有待处理审批任务",
                "data": None,
            }, status=status.HTTP_400_BAD_REQUEST)

        if current_task.approver_id != request.user.id and not request.user.is_superuser:
            return Response({
                "code": 403,
                "message": "只有当前节点审批人可以通过申请",
                "data": None,
            }, status=status.HTTP_403_FORBIDDEN)

        serializer = WorkflowActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True) # 如果参数校验失败，直接抛出 DRF 的 400 错误响应

        with transaction.atomic():
            old_status = workflow.status
            
            current_task.status = WorkflowTask.STATUS_APPROVED
            current_task.comment = serializer.validated_data["comment"]
            current_task.handled_at = timezone.now()
            current_task.save(update_fields=[
                "status",
                "comment",
                "handled_at",
                "updated_at",
            ])

            next_node = None

            if workflow.template_id:
                for node in workflow.template.nodes.filter(
                    is_active=True,
                    node_order__gt=current_task.node_order,
                ).order_by("node_order"):
                    # 从节点后面继续找，只找金额条件的节点
                    if is_node_applicable(workflow, node):
                        next_node = node
                        break

            if next_node:
                next_approver = get_approver_from_workflow(workflow, next_node.approver_field)

                if next_approver is None:
                    return Response({
                        "code": 400,
                        "message": "下一节点审批人不存在",
                        "data": None,
                    }, status=status.HTTP_400_BAD_REQUEST)

                WorkflowTask.objects.create(
                    workflow=workflow,
                    node_name=next_node.node_name,
                    node_order=next_node.node_order,
                    approver=next_approver,
                )

                WorkflowOperationLog.objects.create(
                    workflow=workflow,
                    operator=request.user,
                    action=WorkflowOperationLog.ACTION_APPROVE,
                    from_status=old_status,
                    to_status=workflow.status,
                    comment=serializer.validated_data["comment"],
                    snapshot={
                        "approved_task_id": current_task.id,
                        "next_node": next_node.node_name,
                    },
                )
            else:
                workflow.status = WorkflowRequest.STATUS_APPROVED
                workflow.finished_at = timezone.now()
                workflow.save(update_fields=["status", "finished_at", "updated_at"])

                WorkflowOperationLog.objects.create(
                    workflow=workflow,
                    operator=request.user,
                    action=WorkflowOperationLog.ACTION_APPROVE,
                    from_status=old_status,
                    to_status=workflow.status,
                    comment=serializer.validated_data["comment"],
                    snapshot={
                        "approved_task_id": current_task.id,
                        "finished": True,
                    },
                )

        return Response({
            "code": 200,
            "message": "审批通过",
            "data": self.get_serializer(workflow).data,
        })

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        workflow = self.get_object()

        if workflow.status != WorkflowRequest.STATUS_PENDING:
            return Response({
                "code": 400,
                "message": "只有待审批状态可以驳回",
                "data": None,
            }, status=status.HTTP_400_BAD_REQUEST)

        current_task = workflow.tasks.filter(
            status=WorkflowTask.STATUS_PENDING,
        ).order_by("node_order").first()

        if current_task is None:
            return Response({
                "code": 400,
                "message": "当前没有待处理审批任务",
                "data": None,
            }, status=status.HTTP_400_BAD_REQUEST)

        if current_task.approver_id != request.user.id and not request.user.is_superuser:
            return Response({
                "code": 403,
                "message": "只有当前节点审批人可以驳回申请",
                "data": None,
            }, status=status.HTTP_403_FORBIDDEN)

        serializer = WorkflowActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True) # 如果参数校验失败，直接抛出 DRF 的 400 错误响应

        with transaction.atomic():
            old_status = workflow.status
            
            current_task.status = WorkflowTask.STATUS_REJECTED
            current_task.comment = serializer.validated_data["comment"]
            current_task.handled_at = timezone.now()
            current_task.save(update_fields=[
                "status",
                "comment",
                "handled_at",
                "updated_at",
            ])

            workflow.status = WorkflowRequest.STATUS_REJECTED
            workflow.finished_at = timezone.now()
            workflow.save(update_fields=["status", "finished_at", "updated_at"])

            WorkflowOperationLog.objects.create(
                workflow=workflow,
                operator=request.user,
                action=WorkflowOperationLog.ACTION_REJECT,
                from_status=old_status,
                to_status=workflow.status,
                comment=serializer.validated_data["comment"],
                snapshot={
                    "rejected_task_id": current_task.id,
                    "node_order": current_task.node_order,
                },
            )

        return Response({
            "code": 200,
            "message": "审批驳回",
            "data": self.get_serializer(workflow).data,
        })

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        workflow = self.get_object()

        if workflow.applicant_id != request.user.id:
            return Response({
                "code": 403,
                "message": "只有申请人可以取消申请",
                "data": None,
            }, status=status.HTTP_403_FORBIDDEN)

        if workflow.status not in [
            WorkflowRequest.STATUS_DRAFT,
            WorkflowRequest.STATUS_PENDING,
        ]:
            return Response({
                "code": 400,
                "message": "当前状态不能取消",
                "data": None,
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = WorkflowActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            old_status = workflow.status
            workflow.status = WorkflowRequest.STATUS_CANCELLED
            workflow.finished_at = timezone.now()
            workflow.save(update_fields=["status", "finished_at", "updated_at"])

            workflow.tasks.filter(
                status=WorkflowTask.STATUS_PENDING,
            ).update(
                status=WorkflowTask.STATUS_CANCELLED,
                handled_at=timezone.now(),
            )

            WorkflowOperationLog.objects.create(
                workflow=workflow,
                operator=request.user,
                action=WorkflowOperationLog.ACTION_CANCEL,
                from_status=old_status,
                to_status=workflow.status,
                comment=serializer.validated_data["comment"],
            )

        return Response({
            "code": 200,
            "message": "取消成功",
            "data": self.get_serializer(workflow).data,
        })

    @action(detail=True, methods=["post"], url_path="create-payment")
    def create_payment(self, request, pk=None):
        workflow = self.get_object()

        if workflow.applicant_id != request.user.id:
            return Response({
                "code": 403,
                "message": "只有申请人可以创建支付订单",
                "data": None,
            }, status=status.HTTP_403_FORBIDDEN)

        if workflow.request_type != WorkflowRequest.TYPE_PAYMENT:
            return Response({
                "code": 400,
                "message": "只有打款申请可以创建支付订单",
                "data": None,
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # hasattr(workflow, "payment_order") 因为设置了related_name="payment_order"
        if hasattr(workflow, "payment_order"):
            return Response({
                "code": 400,
                "message": "该申请已经存在支付订单",
                "data": None,
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = CreatePaymentOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            order = PaymentOrder.objects.create(
                workflow=workflow,
                order_no=f"PAY{timezone.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8]}",
                amount=serializer.validated_data["amount"],
                pay_method=serializer.validated_data["pay_method"],
            )

            WorkflowOperationLog.objects.create(
                workflow=workflow,
                operator=request.user,
                action="create_payment",
                from_status=workflow.status,
                to_status=workflow.status,
                comment="创建支付订单",
                snapshot={
                    "order_no": order.order_no,
                    "amount": str(order.amount),
                    "pay_method": order.pay_method,
                },
            )

        return Response({
            "code": 200,
            "message": "支付订单创建成功",
            "data": PaymentOrderSerializer(order).data,
        })

class PaymentOrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentOrderSerializer
    permission_classes = [IsAuthenticated]   

    def get_queryset(self):
        user = self.request.user

        queryset = PaymentOrder.objects.select_related(
            "workflow",
            # 2个跨表查询 这两个下划线 __ 可以理解成“往关联对象里面走一层”。
            "workflow__applicant",
            "workflow__current_approver",
        )

        if user.is_superuser:
            return queryset
        # 因为一对一的关系，所以PaymentOrder 可以通过 workflow 找到对应的 WorkflowRequest
        return queryset.filter(
            Q(workflow__applicant=user) | Q(workflow__current_approver=user)
        ).distinct()

    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request, pk=None):
        order = self.get_object()
        workflow = order.workflow

        if workflow.applicant_id != request.user.id:
            return Response({
                "code": 403,
                "message": "只有申请人可以标记已支付",
                "data": None,
            }, status=status.HTTP_403_FORBIDDEN)

        if order.status != PaymentOrder.STATUS_PENDING:
            return Response({
                "code": 400,
                "message": "只有待支付订单可以标记已支付",
                "data": None,
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = PaymentActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            old_status = order.status
            order.status = PaymentOrder.STATUS_USER_PAID
            order.paid_at = timezone.now()
            order.save(update_fields=["status", "paid_at", "updated_at"])

            WorkflowOperationLog.objects.create(
                workflow=workflow,
                operator=request.user,
                action="mark_paid",
                from_status=workflow.status,
                to_status=workflow.status,
                comment=serializer.validated_data["comment"],
                snapshot={
                    "order_no": order.order_no,
                    "from_payment_status": old_status,
                    "to_payment_status": order.status,
                },
            )

        return Response({
            "code": 200,
            "message": "已标记为用户已支付",
            "data": self.get_serializer(order).data,
        })

    @action(detail=True, methods=["post"], url_path="confirm")
    def confirm(self, request, pk=None):
        order = self.get_object()
        workflow = order.workflow

        if not request.user.is_superuser:
            return Response({
                "code": 403,
                "message": "只有管理员可以确认到账",
                "data": None,
            }, status=status.HTTP_403_FORBIDDEN)

        if order.status != PaymentOrder.STATUS_USER_PAID:
            return Response({
                "code": 400,
                "message": "只有用户已支付订单可以确认到账",
                "data": None,
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = PaymentActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            old_payment_status = order.status
            old_workflow_status = workflow.status

            order.status = PaymentOrder.STATUS_CONFIRMED
            order.confirmed_at = timezone.now()
            order.save(update_fields=["status", "confirmed_at", "updated_at"])

            if workflow.status == WorkflowRequest.STATUS_DRAFT:
                workflow.status = WorkflowRequest.STATUS_PENDING
                workflow.submitted_at = timezone.now()
                workflow.save(update_fields=["status", "submitted_at", "updated_at"])

            WorkflowOperationLog.objects.create(
                workflow=workflow,
                operator=request.user,
                action="confirm_payment",
                from_status=old_workflow_status,
                to_status=workflow.status,
                comment=serializer.validated_data["comment"],
                snapshot={
                    "order_no": order.order_no,
                    "from_payment_status": old_payment_status,
                    "to_payment_status": order.status,
                },
            )

        return Response({
            "code": 200,
            "message": "确认到账成功",
            "data": self.get_serializer(order).data,
        })

class WorkflowTemplateViewSet(viewsets.ModelViewSet):
    serializer_class = WorkflowTemplateSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = WorkflowTemplate.objects.prefetch_related("nodes")

        if self.request.user.is_superuser:
            return queryset

        return queryset.filter(is_active=True)



