from django.test import TestCase

# Create your tests here.
from django.contrib.auth import get_user_model
from .models import (WorkflowOperationLog, WorkflowRequest, PaymentOrder, WorkflowTask,
    WorkflowTemplate,
    WorkflowTemplateNode,)
from rest_framework.test import APITestCase

User = get_user_model()

class WorkflowRequestTests(APITestCase):
    def setUp(self):
        self.applicant = User.objects.create_user(
            username="workflow_applicant",
            password="123456",
        )
        self.approver = User.objects.create_user(
            username="workflow_approver",
            password="123456",
        )
        self.template = WorkflowTemplate.objects.create(
            name="付款审批流程",
            code="payment_approval",
        )

        WorkflowTemplateNode.objects.create(
            template=self.template,
            node_name="一级审批",
            node_order=1,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_CURRENT,
        )

        WorkflowTemplateNode.objects.create(
            template=self.template,
            node_name="二级审批",
            node_order=2,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_SECOND,
        )

    def test_create_workflow_request(self):
        self.client.force_authenticate(user=self.applicant)
        response = self.client.post("/api/workflows/requests/", {
            "request_type": "payment",
            "title": "测试打款申请",
            "description": "供应商费用",
            "amount": "100.00",
            "current_approver": self.approver.id,
        }, format="json")

        self.assertEqual(response.status_code, 201) # 201 Created：创建成功

        workflow = WorkflowRequest.objects.get(title="测试打款申请")
        self.assertEqual(workflow.applicant, self.applicant)
        self.assertEqual(workflow.status, WorkflowRequest.STATUS_DRAFT)

        self.assertEqual(
            WorkflowOperationLog.objects.filter(
                workflow=workflow,
                action=WorkflowOperationLog.ACTION_CREATE,
            ).count(),
            1,
        )

    def test_submit_workflow_request(self):
        workflow = WorkflowRequest.objects.create(
            request_type="payment",
            title="测试打款申请",
            applicant=self.applicant,
            current_approver=self.approver,
        )

        self.client.force_authenticate(user=self.applicant)

        response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/submit/",
            {"comment": "提交审批"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        workflow.refresh_from_db()
        self.assertEqual(workflow.status, WorkflowRequest.STATUS_PENDING)
        self.assertIsNotNone(workflow.submitted_at)

    def test_approver_can_approve_pending_request(self):
        workflow = WorkflowRequest.objects.create(
            request_type="payment",
            title="测试打款申请",
            applicant=self.applicant,
            current_approver=self.approver,
            status=WorkflowRequest.STATUS_PENDING,
        )
        WorkflowTask.objects.create(
            workflow=workflow,
            node_name="一级审批",
            node_order=1,
            approver=self.approver,
        )

        self.client.force_authenticate(user=self.approver)

        response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/approve/",
            {"comment": "同意"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        workflow.refresh_from_db()
        self.assertEqual(workflow.status, WorkflowRequest.STATUS_APPROVED)
        self.assertIsNotNone(workflow.finished_at)

    def test_non_approver_cannot_approve(self):
        other_user = User.objects.create_user(
            username="other_user",
            password="123456",
        )

        workflow = WorkflowRequest.objects.create(
            request_type="payment",
            title="测试打款申请",
            applicant=self.applicant,
            current_approver=self.approver,
            status=WorkflowRequest.STATUS_PENDING,
        )

        self.client.force_authenticate(user=other_user)

        response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/approve/",
            {"comment": "我也想批"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    def test_approver_can_reject_pending_request(self):
        workflow = WorkflowRequest.objects.create(
            request_type="payment",
            title="测试打款申请",
            applicant=self.applicant,
            current_approver=self.approver,
            status=WorkflowRequest.STATUS_PENDING,
        )
        WorkflowTask.objects.create(
            workflow=workflow,
            node_name="一级审批",
            node_order=1,
            approver=self.approver,
        )

        self.client.force_authenticate(user=self.approver)

        response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/reject/",
            {"comment": "资料不完整"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        workflow.refresh_from_db()
        self.assertEqual(workflow.status, WorkflowRequest.STATUS_REJECTED)

    def test_applicant_can_cancel_draft_request(self):
        workflow = WorkflowRequest.objects.create(
            request_type="payment",
            title="测试打款申请",
            applicant=self.applicant,
            current_approver=self.approver,
            status=WorkflowRequest.STATUS_DRAFT,
        )

        self.client.force_authenticate(user=self.applicant)

        response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/cancel/",
            {"comment": "不申请了"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        workflow.refresh_from_db()
        self.assertEqual(workflow.status, WorkflowRequest.STATUS_CANCELLED)

    def test_operation_logs_are_created_for_submit_and_approve(self):
        single_template = WorkflowTemplate.objects.create(
            name="一级审批流程",
            code="single_approval_for_log_test",
        )

        WorkflowTemplateNode.objects.create(
            template=single_template,
            node_name="一级审批",
            node_order=1,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_CURRENT,
        )
        workflow = WorkflowRequest.objects.create(
            request_type="payment",
            title="测试打款申请",
            applicant=self.applicant,
            current_approver=self.approver,
            template=single_template,
        )

        self.client.force_authenticate(user=self.applicant)
        submit_response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/submit/",
            {"comment": "提交审批"},
            format="json",
        )
        self.assertEqual(submit_response.status_code, 200)

        self.client.force_authenticate(user=self.approver)
        approve_response  = self.client.post(
            f"/api/workflows/requests/{workflow.id}/approve/",
            {"comment": "同意"},
            format="json",
        )
        self.assertEqual(approve_response.status_code, 200)

        actions = list(
            WorkflowOperationLog.objects.filter(workflow=workflow)
            .values_list("action", flat=True)
        )
        # actions 必须完全等于 ["submit", "approve"]
        # 数量一样 顺序一样 内容一样，也是确认此操作日志按顺序写入：先提交再通过
        self.assertEqual(actions, ["submit", "approve"])

    def test_approved_workflow_cannot_be_approved_again(self):
        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="已通过申请",
            applicant=self.applicant,
            current_approver=self.approver,
            status=WorkflowRequest.STATUS_APPROVED,
        )

        self.client.force_authenticate(user=self.approver)

        response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/approve/",
            {"comment": "重复审批"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_rejected_workflow_cannot_be_approved(self):
        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="已驳回申请",
            applicant=self.applicant,
            current_approver=self.approver,
            status=WorkflowRequest.STATUS_REJECTED,
        )

        self.client.force_authenticate(user=self.approver)

        response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/approve/",
            {"comment": "驳回后再审批"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_non_current_task_approver_cannot_approve(self):
        other_user = User.objects.create_user(
            username="not_task_approver",
            password="123456",
        )

        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="待审批申请",
            applicant=self.applicant,
            current_approver=self.approver,
            status=WorkflowRequest.STATUS_PENDING,
        )

        WorkflowTask.objects.create(
            workflow=workflow,
            node_name="一级审批",
            node_order=1,
            approver=self.approver,
        )

        self.client.force_authenticate(user=other_user)

        response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/approve/",
            {"comment": "我来审批"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    def test_admin_can_approve_as_delegate(self):
        admin = User.objects.create_superuser(
            username="workflow_admin",
            password="123456",
        )

        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="管理员代审批申请",
            applicant=self.applicant,
            current_approver=self.approver,
            status=WorkflowRequest.STATUS_PENDING,
        )

        WorkflowTask.objects.create(
            workflow=workflow,
            node_name="一级审批",
            node_order=1,
            approver=self.approver,
        )

        self.client.force_authenticate(user=admin)

        response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/approve/",
            {"comment": "管理员代审批"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        workflow.refresh_from_db()
        self.assertEqual(workflow.status, WorkflowRequest.STATUS_APPROVED)

    def test_cannot_approve_without_pending_task(self):
        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="无待办任务申请",
            applicant=self.applicant,
            current_approver=self.approver,
            status=WorkflowRequest.STATUS_PENDING,
        )

        WorkflowTask.objects.create(
            workflow=workflow,
            node_name="一级审批",
            node_order=1,
            approver=self.approver,
            status=WorkflowTask.STATUS_APPROVED,
        )

        self.client.force_authenticate(user=self.approver)

        response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/approve/",
            {"comment": "没有 pending task"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
    
    def test_cancel_workflow_cancels_pending_tasks(self):
        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="取消申请",
            applicant=self.applicant,
            current_approver=self.approver,
            status=WorkflowRequest.STATUS_PENDING,
        )

        task = WorkflowTask.objects.create(
            workflow=workflow,
            node_name="一级审批",
            node_order=1,
            approver=self.approver,
        )

        self.client.force_authenticate(user=self.applicant)

        response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/cancel/",
            {"comment": "取消申请"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        workflow.refresh_from_db()
        task.refresh_from_db()

        self.assertEqual(workflow.status, WorkflowRequest.STATUS_CANCELLED)
        self.assertEqual(task.status, WorkflowTask.STATUS_CANCELLED)
        self.assertIsNotNone(task.handled_at)

    def test_low_amount_skips_second_approval_node(self):
        second_approver = User.objects.create_user(
            username="low_amount_second_approver",
            password="123456",
        )

        template = WorkflowTemplate.objects.create(
            name="金额条件审批流程",
            code="amount_condition_low_test",
        )

        WorkflowTemplateNode.objects.create(
            template=template,
            node_name="一级审批",
            node_order=1,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_CURRENT,
        )

        WorkflowTemplateNode.objects.create(
            template=template,
            node_name="二级审批",
            node_order=2,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_SECOND,
            min_amount="1000.00",
        )

        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="小金额申请",
            applicant=self.applicant,
            current_approver=self.approver,
            second_approver=second_approver,
            template=template,
            amount="500.00",
        )

        self.client.force_authenticate(user=self.applicant)
        submit_response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/submit/",
            {"comment": "提交小金额申请"},
            format="json",
        )

        self.assertEqual(submit_response.status_code, 200)

        self.client.force_authenticate(user=self.approver)
        approve_response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/approve/",
            {"comment": "一级通过"},
            format="json",
        )

        self.assertEqual(approve_response.status_code, 200)

        workflow.refresh_from_db()
        self.assertEqual(workflow.status, WorkflowRequest.STATUS_APPROVED)

        self.assertEqual(
            WorkflowTask.objects.filter(workflow=workflow).count(),
            1,
        )

    def test_high_amount_requires_second_approval_node(self):
        second_approver = User.objects.create_user(
            username="high_amount_second_approver",
            password="123456",
        )

        template = WorkflowTemplate.objects.create(
            name="金额条件审批流程",
            code="amount_condition_high_test",
        )

        WorkflowTemplateNode.objects.create(
            template=template,
            node_name="一级审批",
            node_order=1,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_CURRENT,
        )

        WorkflowTemplateNode.objects.create(
            template=template,
            node_name="二级审批",
            node_order=2,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_SECOND,
            min_amount="1000.00",
        )

        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="大金额申请",
            applicant=self.applicant,
            current_approver=self.approver,
            second_approver=second_approver,
            template=template,
            amount="2000.00",
        )

        self.client.force_authenticate(user=self.applicant)
        submit_response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/submit/",
            {"comment": "提交大金额申请"},
            format="json",
        )

        self.assertEqual(submit_response.status_code, 200)

        self.client.force_authenticate(user=self.approver)
        first_approve_response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/approve/",
            {"comment": "一级通过"},
            format="json",
        )

        self.assertEqual(first_approve_response.status_code, 200)

        workflow.refresh_from_db()
        self.assertEqual(workflow.status, WorkflowRequest.STATUS_PENDING)

        second_task = WorkflowTask.objects.get(
            workflow=workflow,
            node_order=2,
        )
        self.assertEqual(second_task.status, WorkflowTask.STATUS_PENDING)
        self.assertEqual(second_task.approver, second_approver)

        self.client.force_authenticate(user=second_approver)
        second_approve_response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/approve/",
            {"comment": "二级通过"},
            format="json",
        )

        self.assertEqual(second_approve_response.status_code, 200)

        workflow.refresh_from_db()
        self.assertEqual(workflow.status, WorkflowRequest.STATUS_APPROVED)

    def test_filter_workflow_requests_by_status(self):
        WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="待审批申请",
            applicant=self.applicant,
            current_approver=self.approver,
            status=WorkflowRequest.STATUS_PENDING,
        )
        WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="已通过申请",
            applicant=self.applicant,
            current_approver=self.approver,
            status=WorkflowRequest.STATUS_APPROVED,
        )

        self.client.force_authenticate(user=self.applicant)

        response = self.client.get("/api/workflows/requests/mine/?status=pending")

        self.assertEqual(response.status_code, 200)

        items = response.data["results"] if "results" in response.data else response.data["data"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "待审批申请")

    def test_filter_workflow_requests_by_request_type(self):
        WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="付款申请",
            applicant=self.applicant,
            current_approver=self.approver,
        )
        WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_GENERAL,
            title="普通申请",
            applicant=self.applicant,
            current_approver=self.approver,
        )

        self.client.force_authenticate(user=self.applicant)

        response = self.client.get("/api/workflows/requests/mine/?request_type=payment")

        self.assertEqual(response.status_code, 200)

        items = response.data["results"] if "results" in response.data else response.data["data"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "付款申请")

    def test_filter_workflow_requests_by_template(self):
        other_template = WorkflowTemplate.objects.create(
            name="其他流程",
            code="other_filter_template",
        )

        WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="默认模板申请",
            applicant=self.applicant,
            current_approver=self.approver,
            template=self.template,
        )
        WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="其他模板申请",
            applicant=self.applicant,
            current_approver=self.approver,
            template=other_template,
        )

        self.client.force_authenticate(user=self.applicant)

        response = self.client.get(f"/api/workflows/requests/mine/?template={self.template.id}")

        self.assertEqual(response.status_code, 200)

        items = response.data["results"] if "results" in response.data else response.data["data"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "默认模板申请")


class PaymentOrderTests(APITestCase):
    def setUp(self):
        self.applicant = User.objects.create_user(
            username="payment_applicant",
            password="123456",
        )
        self.approver = User.objects.create_user(
            username="payment_approver",
            password="123456",
        )
        self.admin = User.objects.create_superuser(
            username="payment_admin",
            password="123456",
        )
        self.template = WorkflowTemplate.objects.create(
            name="付款审批流程",
            code="payment_approval",
        )

        WorkflowTemplateNode.objects.create(
            template=self.template,
            node_name="一级审批",
            node_order=1,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_CURRENT,
        )

        WorkflowTemplateNode.objects.create(
            template=self.template,
            node_name="二级审批",
            node_order=2,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_SECOND,
        )

    def test_applicant_can_create_payment_order(self):
        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="测试付款申请",
            applicant=self.applicant,
            current_approver=self.approver,
            amount="100.00",
        )

        self.client.force_authenticate(user=self.applicant)

        response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/create-payment/",
            {
                "amount": "100.00",
                "pay_method": PaymentOrder.METHOD_ALIPAY,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        order = PaymentOrder.objects.get(workflow=workflow)
        workflow.refresh_from_db()
        # 模型字段是 DecimalField，但你创建对象时传了字符串，内存对象不一定立刻变成 Decimal，重新查库后才会按字段类型转换
        # 或者self.assertEqual(order.amount, Decimal("100.00"))
        self.assertEqual(order.amount, workflow.amount)
        self.assertEqual(order.status, PaymentOrder.STATUS_PENDING)

    def test_cannot_create_duplicate_payment_order(self):
        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="测试付款申请",
            applicant=self.applicant,
            current_approver=self.approver,
            amount="100.00",
        )

        PaymentOrder.objects.create(
            workflow=workflow,
            order_no="PAY_EXISTED",
            amount="100.00",
            pay_method=PaymentOrder.METHOD_ALIPAY,
        )

        self.client.force_authenticate(user=self.applicant)

        response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/create-payment/",
            {
                "amount": "100.00",
                "pay_method": PaymentOrder.METHOD_ALIPAY,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_applicant_can_mark_payment_as_paid(self):
        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="测试付款申请",
            applicant=self.applicant,
            current_approver=self.approver,
            amount="100.00",
        )
        order = PaymentOrder.objects.create(
            workflow=workflow,
            order_no="PAY_MARK_PAID",
            amount="100.00",
            pay_method=PaymentOrder.METHOD_ALIPAY,
        )

        self.client.force_authenticate(user=self.applicant)

        response = self.client.post(
            f"/api/workflows/payments/{order.id}/mark-paid/",
            {"comment": "我已经付款"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.STATUS_USER_PAID)
        self.assertIsNotNone(order.paid_at)

    def test_admin_can_confirm_payment_and_submit_workflow(self):
        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="测试付款申请",
            applicant=self.applicant,
            current_approver=self.approver,
            amount="100.00",
            status=WorkflowRequest.STATUS_DRAFT,
        )
        order = PaymentOrder.objects.create(
            workflow=workflow,
            order_no="PAY_CONFIRM",
            amount="100.00",
            pay_method=PaymentOrder.METHOD_ALIPAY,
            status=PaymentOrder.STATUS_USER_PAID,
        )

        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            f"/api/workflows/payments/{order.id}/confirm/",
            {"comment": "确认到账"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        order.refresh_from_db()
        workflow.refresh_from_db()

        self.assertEqual(order.status, PaymentOrder.STATUS_CONFIRMED)
        self.assertEqual(workflow.status, WorkflowRequest.STATUS_PENDING)
        self.assertIsNotNone(order.confirmed_at)
        self.assertIsNotNone(workflow.submitted_at)

    def test_normal_user_cannot_confirm_payment(self):
        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="测试付款申请",
            applicant=self.applicant,
            current_approver=self.approver,
            amount="100.00",
        )
        order = PaymentOrder.objects.create(
            workflow=workflow,
            order_no="PAY_NORMAL_CONFIRM",
            amount="100.00",
            pay_method=PaymentOrder.METHOD_ALIPAY,
            status=PaymentOrder.STATUS_USER_PAID,
        )

        self.client.force_authenticate(user=self.applicant)

        response = self.client.post(
            f"/api/workflows/payments/{order.id}/confirm/",
            {"comment": "我自己确认"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_create_payment_order_writes_operation_log(self):
        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="测试付款申请",
            applicant=self.applicant,
            current_approver=self.approver,
            amount="100.00",
        )

        self.client.force_authenticate(user=self.applicant)

        response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/create-payment/",
            {
                "amount": "100.00",
                "pay_method": PaymentOrder.METHOD_ALIPAY,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        log = WorkflowOperationLog.objects.get(
            workflow=workflow,
            action="create_payment",
        )

        self.assertEqual(log.operator, self.applicant)
        self.assertEqual(log.snapshot["pay_method"], PaymentOrder.METHOD_ALIPAY)

    def test_confirm_payment_writes_operation_log(self):
        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="测试付款申请",
            applicant=self.applicant,
            current_approver=self.approver,
            amount="100.00",
            status=WorkflowRequest.STATUS_DRAFT,
        )
        order = PaymentOrder.objects.create(
            workflow=workflow,
            order_no="PAY_CONFIRM_LOG",
            amount="100.00",
            pay_method=PaymentOrder.METHOD_ALIPAY,
            status=PaymentOrder.STATUS_USER_PAID,
        )

        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            f"/api/workflows/payments/{order.id}/confirm/",
            {"comment": "确认到账"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        log = WorkflowOperationLog.objects.get(
            workflow=workflow,
            action="confirm_payment",
        )

        self.assertEqual(log.operator, self.admin)
        self.assertEqual(log.from_status, WorkflowRequest.STATUS_DRAFT)
        self.assertEqual(log.to_status, WorkflowRequest.STATUS_PENDING)
        self.assertEqual(log.snapshot["to_payment_status"], PaymentOrder.STATUS_CONFIRMED)

    def test_cannot_create_payment_order_for_non_payment_request(self):
        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_GENERAL,
            title="普通申请",
            applicant=self.applicant,
            current_approver=self.approver,
        )

        self.client.force_authenticate(user=self.applicant)

        response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/create-payment/",
            {
                "amount": "100.00",
                "pay_method": PaymentOrder.METHOD_ALIPAY,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_submit_creates_first_workflow_task(self):
        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="两级审批申请",
            applicant=self.applicant,
            current_approver=self.approver,
        )

        self.client.force_authenticate(user=self.applicant)

        response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/submit/",
            {"comment": "提交审批"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        task = WorkflowTask.objects.get(workflow=workflow, node_order=1)
        self.assertEqual(task.node_name, "一级审批")
        self.assertEqual(task.approver, self.approver)
        self.assertEqual(task.status, WorkflowTask.STATUS_PENDING)

    def test_two_level_approval_finishes_after_second_approver(self):
        second_approver = User.objects.create_user(
            username="second_approver",
            password="123456",
        )

        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="两级审批申请",
            applicant=self.applicant,
            current_approver=self.approver,
            second_approver=second_approver,
            template=self.template,
            status=WorkflowRequest.STATUS_PENDING,
        )

        WorkflowTask.objects.create(
            workflow=workflow,
            node_name="一级审批",
            node_order=1,
            approver=self.approver,
        )

        self.client.force_authenticate(user=self.approver)

        first_response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/approve/",
            {"comment": "一级通过"},
            format="json",
        )

        self.assertEqual(first_response.status_code, 200)

        workflow.refresh_from_db()
        self.assertEqual(workflow.status, WorkflowRequest.STATUS_PENDING)

        second_task = WorkflowTask.objects.get(workflow=workflow, node_order=2)
        self.assertEqual(second_task.approver, second_approver)
        self.assertEqual(second_task.status, WorkflowTask.STATUS_PENDING)

        self.client.force_authenticate(user=second_approver)

        second_response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/approve/",
            {"comment": "二级通过"},
            format="json",
        )

        self.assertEqual(second_response.status_code, 200)

        workflow.refresh_from_db()
        self.assertEqual(workflow.status, WorkflowRequest.STATUS_APPROVED)

        first_task = WorkflowTask.objects.get(workflow=workflow, node_order=1)
        second_task.refresh_from_db()

        self.assertEqual(first_task.status, WorkflowTask.STATUS_APPROVED)
        self.assertEqual(second_task.status, WorkflowTask.STATUS_APPROVED)
    
    def test_submit_uses_workflow_template_first_node(self):
        template = WorkflowTemplate.objects.create(
            name="付款审批流程",
            code="payment_approval_first_node_test",
        )
        WorkflowTemplateNode.objects.create(
            template=template,
            node_name="主管审批",
            node_order=1,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_CURRENT,
        )

        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="模板审批申请",
            applicant=self.applicant,
            current_approver=self.approver,
            template=template,
        )

        self.client.force_authenticate(user=self.applicant)

        response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/submit/",
            {"comment": "提交审批"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        task = WorkflowTask.objects.get(workflow=workflow, node_order=1)
        self.assertEqual(task.node_name, "主管审批")
        self.assertEqual(task.approver, self.approver)

    def test_template_two_level_approval(self):
        second_approver = User.objects.create_user(
            username="template_second_approver",
            password="123456",
        )

        template = WorkflowTemplate.objects.create(
            name="付款审批流程",
            code="payment_approval_template_test",
        )
        WorkflowTemplateNode.objects.create(
            template=template,
            node_name="主管审批",
            node_order=1,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_CURRENT,
        )
        WorkflowTemplateNode.objects.create(
            template=template,
            node_name="老板审批",
            node_order=2,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_SECOND,
        )

        workflow = WorkflowRequest.objects.create(
            request_type=WorkflowRequest.TYPE_PAYMENT,
            title="模板两级审批申请",
            applicant=self.applicant,
            current_approver=self.approver,
            second_approver=second_approver,
            template=template,
            status=WorkflowRequest.STATUS_PENDING,
        )

        WorkflowTask.objects.create(
            workflow=workflow,
            node_name="主管审批",
            node_order=1,
            approver=self.approver,
        )

        self.client.force_authenticate(user=self.approver)
        first_response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/approve/",
            {"comment": "主管同意"},
            format="json",
        )

        self.assertEqual(first_response.status_code, 200)

        second_task = WorkflowTask.objects.get(workflow=workflow, node_order=2)
        self.assertEqual(second_task.node_name, "老板审批")
        self.assertEqual(second_task.approver, second_approver)

        self.client.force_authenticate(user=second_approver)
        second_response = self.client.post(
            f"/api/workflows/requests/{workflow.id}/approve/",
            {"comment": "老板同意"},
            format="json",
        )

        self.assertEqual(second_response.status_code, 200)

        workflow.refresh_from_db()
        self.assertEqual(workflow.status, WorkflowRequest.STATUS_APPROVED)
    
class WorkflowTemplateApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="template_user",
            password="123456",
        )
        self.admin = User.objects.create_superuser(
            username="template_admin",
            password="123456",
        )

    def test_normal_user_can_list_active_templates(self):
        active_template = WorkflowTemplate.objects.create(
            name="启用模板",
            code="active_template",
            is_active=True,
        )
        WorkflowTemplateNode.objects.create(
            template=active_template,
            node_name="一级审批",
            node_order=1,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_CURRENT,
        )
        WorkflowTemplate.objects.create(
            name="停用模板",
            code="inactive_template",
            is_active=False,
        )
        self.client.force_authenticate(user=self.user)

        response = self.client.get("/api/workflows/templates/")

        self.assertEqual(response.status_code, 200)
        items = response.data["results"]

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["code"], "active_template")
        self.assertEqual(items[0]["nodes"][0]["node_name"], "一级审批")

    def test_admin_can_list_all_templates(self):
        WorkflowTemplate.objects.create(
            name="启用模板",
            code="active_template",
            is_active=True,
        )
        WorkflowTemplate.objects.create(
            name="停用模板",
            code="inactive_template",
            is_active=False,
        )

        self.client.force_authenticate(user=self.admin)

        response = self.client.get("/api/workflows/templates/")

        self.assertEqual(response.status_code, 200)

        items = response.data["results"]
        codes = {item["code"] for item in items}
        self.assertEqual(codes, {"active_template", "inactive_template"})

    
class WorkflowTemplateNodeApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="template_node_user",
            password="123456",
        )
        self.admin = User.objects.create_superuser(
            username="template_node_admin",
            password="123456",
        )
        self.template = WorkflowTemplate.objects.create(
            name="节点测试流程",
            code="template_node_test",
        )

    def test_admin_can_create_template_node(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.post("/api/workflows/template-nodes/", {
            "template": self.template.id,
            "node_name": "一级审批",
            "node_order": 1,
            "approver_field": WorkflowTemplateNode.APPROVER_FIELD_CURRENT,
            "min_amount": None,
            "is_active": True,
        }, format="json")

        self.assertEqual(response.status_code, 201)

        node = WorkflowTemplateNode.objects.get(template=self.template)
        self.assertEqual(node.node_name, "一级审批")
        self.assertEqual(node.node_order, 1)

    def test_can_filter_nodes_by_template(self):
        other_template = WorkflowTemplate.objects.create(
            name="其他流程",
            code="other_template_node_test",
        )

        WorkflowTemplateNode.objects.create(
            template=self.template,
            node_name="一级审批",
            node_order=1,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_CURRENT,
        )
        WorkflowTemplateNode.objects.create(
            template=other_template,
            node_name="其他审批",
            node_order=1,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_CURRENT,
        )

        self.client.force_authenticate(user=self.admin)

        response = self.client.get(
            f"/api/workflows/template-nodes/?template={self.template.id}"
        )

        self.assertEqual(response.status_code, 200)

        items = response.data["results"] if "results" in response.data else response.data
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["node_name"], "一级审批")

    def test_normal_user_only_sees_active_nodes(self):
        WorkflowTemplateNode.objects.create(
            template=self.template,
            node_name="启用节点",
            node_order=1,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_CURRENT,
            is_active=True,
        )
        WorkflowTemplateNode.objects.create(
            template=self.template,
            node_name="停用节点",
            node_order=2,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_SECOND,
            is_active=False,
        )

        self.client.force_authenticate(user=self.user)

        response = self.client.get("/api/workflows/template-nodes/")

        self.assertEqual(response.status_code, 200)

        items = response.data["results"] if "results" in response.data else response.data
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["node_name"], "启用节点")

    def test_normal_user_cannot_create_template(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post("/api/workflows/templates/", {
            "name": "普通用户创建模板",
            "code": "normal_user_template",
            "description": "",
            "is_active": True,
        }, format="json")

        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_template(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.post("/api/workflows/templates/", {
            "name": "管理员创建模板",
            "code": "admin_template",
            "description": "管理员创建",
            "is_active": True,
        }, format="json")

        self.assertEqual(response.status_code, 201)

        template = WorkflowTemplate.objects.get(code="admin_template")
        self.assertEqual(template.name, "管理员创建模板")

    def test_normal_user_cannot_create_template_node(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post("/api/workflows/template-nodes/", {
            "template": self.template.id,
            "node_name": "普通用户节点",
            "node_order": 1,
            "approver_field": WorkflowTemplateNode.APPROVER_FIELD_CURRENT,
            "is_active": True,
        }, format="json")

        self.assertEqual(response.status_code, 403)

    def test_admin_can_update_template_node(self):
        node = WorkflowTemplateNode.objects.create(
            template=self.template,
            node_name="一级审批",
            node_order=1,
            approver_field=WorkflowTemplateNode.APPROVER_FIELD_CURRENT,
            is_active=True,
        )

        self.client.force_authenticate(user=self.admin)

        response = self.client.patch(
            f"/api/workflows/template-nodes/{node.id}/",
            {
                "node_name": "主管审批",
                "min_amount": "1000.00",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        node.refresh_from_db()
        self.assertEqual(node.node_name, "主管审批")
        self.assertEqual(str(node.min_amount), "1000.00")


            