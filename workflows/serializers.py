from rest_framework import serializers

from .models import WorkflowOperationLog, WorkflowRequest

class WorkflowOperationLogSerializer(serializers.ModelSerializer):
    # source="operator.username"： 从 operator 这个关联用户对象里取 username。
    operator_username = serializers.CharField(source="operator.username", read_only=True)

    class Meta:
        model = WorkflowOperationLog
        fields = [
            "id",
            "operator",
            "operator_username",
            "action",
            "from_status",
            "to_status",
            "comment",
            "snapshot",
            "created_at",
        ]
        read_only_fields = fields

class WorkflowRequestSerializer(serializers.ModelSerializer):
    applicant_username = serializers.CharField(source="applicant.username", read_only=True)
    current_approver_username = serializers.CharField(source="current_approver.username", read_only=True)
    operation_logs = WorkflowOperationLogSerializer(many=True, read_only=True)

    class Meta:
        model = WorkflowRequest
        fields = [
            "id",
            "request_type",
            "title",
            "description",
            "amount",
            "business_data",
            "status",
            "applicant",
            "applicant_username",
            "current_approver",
            "current_approver_username",
            "submitted_at",
            "finished_at",
            "created_at",
            "updated_at",
            "operation_logs",
        ]
        read_only_fields = [
            "id",
            "status",
            "applicant",
            "applicant_username",
            "submitted_at",
            "finished_at",
            "created_at",
            "updated_at",
            "operation_logs",
        ]

class WorkflowActionSerializer(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True, default="")