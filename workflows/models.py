from django.db import models

# Create your models here.
from django.db import models
from django.conf import settings

class WorkflowRequest(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "草稿"),
        (STATUS_PENDING, "待审批"),
        (STATUS_APPROVED, "已通过"),
        (STATUS_REJECTED, "已驳回"),
        (STATUS_CANCELLED, "已取消"),
    ]

    TYPE_GENERAL = "general"
    TYPE_PAYMENT = "payment"
    TYPE_AI_REVIEW = "ai_review"

    TYPE_CHOICES = [
        (TYPE_GENERAL, "通用申请"),
        (TYPE_PAYMENT, "打款申请"),
        (TYPE_AI_REVIEW, "AI 人工审核"),
    ]
    # 数据库里存的是 "payment"，页面/admin/serializer 可以显示成“打款申请”
    request_type = models.CharField(
        max_length=50,
        choices=TYPE_CHOICES,# choices 只是限制它只能从一组固定值里选：
        default=TYPE_GENERAL,
        verbose_name="申请类型",
    )
    title = models.CharField(max_length=200, verbose_name="标题")
    description = models.TextField(blank=True, default="", verbose_name="说明")
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="金额",
    )
    business_data = models.JSONField(default=dict, blank=True, verbose_name="业务数据")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_index=True,
        verbose_name="状态",
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workflow_requests",
        verbose_name="申请人",
    )
    current_approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pending_workflow_requests",
        verbose_name="当前审批人",
    )
    submitted_at = models.DateTimeField(null=True, blank=True, verbose_name="提交时间")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} - {self.status}"

class WorkflowOperationLog(models.Model):
    ACTION_CREATE = "create"
    ACTION_SUBMIT = "submit"
    ACTION_APPROVE = "approve"
    ACTION_REJECT = "reject"
    ACTION_CANCEL = "cancel"

    ACTION_CHOICES = [
        (ACTION_CREATE, "创建"),
        (ACTION_SUBMIT, "提交"),
        (ACTION_APPROVE, "通过"),
        (ACTION_REJECT, "驳回"),
        (ACTION_CANCEL, "取消"),
    ]

    workflow = models.ForeignKey(
        WorkflowRequest,
        on_delete=models.CASCADE,
        related_name="operation_logs",
        verbose_name="工作流申请",
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflow_operation_logs",
        verbose_name="操作人",
    )
    action = models.CharField(max_length=30, choices=ACTION_CHOICES, verbose_name="动作")
    from_status = models.CharField(max_length=20, blank=True, default="", verbose_name="原状态")
    to_status = models.CharField(max_length=20, blank=True, default="", verbose_name="新状态")
    comment = models.TextField(blank=True, default="", verbose_name="备注")
    snapshot = models.JSONField(default=dict, blank=True, verbose_name="快照")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="操作时间")

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.workflow_id} - {self.action}"
