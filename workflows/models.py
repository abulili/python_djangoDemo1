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
        verbose_name="一级审批人",
    )
    second_approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="second_pending_workflow_requests",
        verbose_name="二级审批人",
    )
    template = models.ForeignKey(
        "WorkflowTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflow_requests",
        verbose_name="流程模板",
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

class PaymentOrder(models.Model):
    STATUS_PENDING = "pending"
    STATUS_USER_PAID = "user_paid"
    STATUS_CONFIRMED = "confirmed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "待支付"),
        (STATUS_USER_PAID, "用户已支付"),
        (STATUS_CONFIRMED, "已确认到账"),
        (STATUS_CANCELLED, "已取消"),
    ]

    METHOD_ALIPAY = "alipay"
    METHOD_WECHAT = "wechat"

    METHOD_CHOICES = [
        (METHOD_ALIPAY, "支付宝"),
        (METHOD_WECHAT, "微信"),
    ]

    # 一个 WorkflowRequest 只能有一个 PaymentOrder
    # 一个 PaymentOrder 也只属于一个 WorkflowRequest
    # 如果以后要支持：分批付款/多次补款/多渠道支付 才一对多
    workflow = models.OneToOneField(
        WorkflowRequest,
        on_delete=models.CASCADE,
        related_name="payment_order",
        verbose_name="关联工作流",
    )
    order_no = models.CharField(max_length=64, unique=True, db_index=True, verbose_name="订单号")
    amount = models.DecimalField(max_digits=12,decimal_places=2,verbose_name="金额")
    pay_method = models.CharField(max_length=20, choices=METHOD_CHOICES, verbose_name="支付方式")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
        verbose_name="支付状态",
    )
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="用户支付时间")
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name="确认到账时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order_no} - {self.status}"

class WorkflowTask(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "待处理"),
        (STATUS_APPROVED, "已通过"),
        (STATUS_REJECTED, "已驳回"),
        (STATUS_CANCELLED, "已取消"),
    ]

    workflow = models.ForeignKey(
        WorkflowRequest,
        on_delete=models.CASCADE,
        related_name="tasks",
        verbose_name="工作流申请",
    )
    node_name = models.CharField(max_length=100, verbose_name="节点名称")
    # 非负整数的数字字段
    node_order = models.PositiveIntegerField(verbose_name="节点顺序")
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workflow_tasks",
        verbose_name="审批人",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
        verbose_name="任务状态",
    )
    comment = models.TextField(blank=True, default="", verbose_name="审批意见")
    handled_at = models.DateTimeField(null=True, blank=True, verbose_name="处理时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        ordering = ["node_order", "id"]
        unique_together = ["workflow", "node_order"]

    def __str__(self):
        return f"{self.workflow_id} - {self.node_name} - {self.status}"

class WorkflowTemplate(models.Model):
    name = models.CharField(max_length=100, verbose_name="模板名称")
    code = models.CharField(max_length=50, unique=True, db_index=True, verbose_name="模板编码")
    description = models.TextField(blank=True, default="", verbose_name="说明")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="是否启用")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name

class WorkflowTemplateNode(models.Model):
    APPROVER_FIELD_CURRENT = "current_approver"
    APPROVER_FIELD_SECOND = "second_approver"

    APPROVER_FIELD_CHOICES = [
        (APPROVER_FIELD_CURRENT, "一级审批人"),
        (APPROVER_FIELD_SECOND, "二级审批人"),
    ]

    template = models.ForeignKey(
        WorkflowTemplate,
        on_delete=models.CASCADE,
        related_name="nodes",
        verbose_name="流程模板",
    )
    node_name = models.CharField(max_length=100, verbose_name="节点名称")
    node_order = models.PositiveIntegerField(verbose_name="节点顺序")
    approver_field = models.CharField(
        max_length=50,
        choices=APPROVER_FIELD_CHOICES,
        verbose_name="审批人字段",
    )
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="是否启用")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    min_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="最低适用金额",
    )
    
    class Meta:
        ordering = ["node_order", "id"]
        unique_together = ["template", "node_order"]

    def __str__(self):
        return f"{self.template.code} - {self.node_name}"


