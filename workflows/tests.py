from django.test import TestCase

# Create your tests here.
from django.contrib.auth import get_user_model
from .models import WorkflowOperationLog, WorkflowRequest
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
        workflow = WorkflowRequest.objects.create(
            request_type="payment",
            title="测试打款申请",
            applicant=self.applicant,
            current_approver=self.approver,
        )

        self.client.force_authenticate(user=self.applicant)
        self.client.post(
            f"/api/workflows/requests/{workflow.id}/submit/",
            {"comment": "提交审批"},
            format="json",
        )

        self.client.force_authenticate(user=self.approver)
        self.client.post(
            f"/api/workflows/requests/{workflow.id}/approve/",
            {"comment": "同意"},
            format="json",
        )

        actions = list(
            WorkflowOperationLog.objects.filter(workflow=workflow)
            .values_list("action", flat=True)
        )
        # actions 必须完全等于 ["submit", "approve"]
        # 数量一样 顺序一样 内容一样，也是确认此操作日志按顺序写入：先提交再通过
        self.assertEqual(actions, ["submit", "approve"])