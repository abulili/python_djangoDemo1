from django.shortcuts import render

# Create your views here.
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import WorkflowOperationLog, WorkflowRequest
from .serializers import WorkflowActionSerializer, WorkflowRequestSerializer

class WorkflowRequestViewSet(viewsets.ModelViewSet):
    serializer_class = WorkflowRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = WorkflowRequest.objects.select_related(
            "applicant",
            "current_approver",
        ).prefetch_related(
            "operation_logs",
        )
        # prefetch_related：提前把“一对多/多对多”的关联数据查出来，减少数据库查询次数
        # 查工作流列表时，顺便把每个工作流的操作日志也批量查出来

        if user.is_superuser:
            return queryset

        # 普通用户只能看到：自己发起的申请或者需要自己审批的申请
        # Q(...) | Q(...) 里的 | 是“或者”。distinct() 是去重
        return queryset.filter(
            Q(applicant=user) | Q(current_approver=user)
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
            current_approver=request.user,
            status=WorkflowRequest.STATUS_PENDING,
        )
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

        # 开启事务
        # 保证：状态更新成功 + 操作日志写入成功 
        # 要么都成功，要么都失败。
        with transaction.atomic():
            old_status = workflow.status
            workflow.status = WorkflowRequest.STATUS_PENDING
            workflow.submitted_at = timezone.now()

            if workflow.current_approver is None:
                workflow.current_approver = request.user

            # update_fields 这次只保存这几个字段
            workflow.save(update_fields=[
                "status",
                "submitted_at",
                "current_approver",
                "updated_at",
            ])
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

        if workflow.current_approver_id != request.user.id and not request.user.is_superuser:
            return Response({
                "code": 403,
                "message": "只有当前审批人可以通过申请",
                "data": None,
            }, status=status.HTTP_403_FORBIDDEN)

        if workflow.status != WorkflowRequest.STATUS_PENDING:
            return Response({
                "code": 400,
                "message": "只有待审批状态可以通过",
                "data": None,
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = WorkflowActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True) # 如果参数校验失败，直接抛出 DRF 的 400 错误响应

        with transaction.atomic():
            old_status = workflow.status
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
            )

        return Response({
            "code": 200,
            "message": "审批通过",
            "data": self.get_serializer(workflow).data,
        })

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        workflow = self.get_object()

        if workflow.current_approver_id != request.user.id and not request.user.is_superuser:
            return Response({
                "code": 403,
                "message": "只有当前审批人可以驳回申请",
                "data": None,
            }, status=status.HTTP_403_FORBIDDEN)

        if workflow.status != WorkflowRequest.STATUS_PENDING:
            return Response({
                "code": 400,
                "message": "只有待审批状态可以驳回",
                "data": None,
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = WorkflowActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            old_status = workflow.status
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
    
    