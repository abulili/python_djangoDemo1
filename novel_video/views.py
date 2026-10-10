import uuid
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import MaterialAsset, VideoJob
from .serializers import MaterialAssetSerializer, VideoJobSerializer
from .tasks import render_novel_video_task
from .asset_probe import probe_asset


class MaterialAssetViewSet(viewsets.ModelViewSet):
    serializer_class = MaterialAssetSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return (
            MaterialAsset.objects.filter(owner=user)
            | MaterialAsset.objects.filter(is_shared=True)
        ).distinct()

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["post"], url_path="probe")
    def probe(self, request, pk=None):
        asset = self.get_object()
        result = probe_asset(asset, save=True)
        return Response({
            "code": 200 if result["ok"] else 400,
            "message": "ok" if result["ok"] else "probe failed",
            "data": result,
        }, status=status.HTTP_200_OK if result["ok"] else status.HTTP_400_BAD_REQUEST)


class VideoJobViewSet(viewsets.ModelViewSet):
    serializer_class = VideoJobSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return VideoJob.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(
            owner=self.request.user,
            trace_id=uuid.uuid4().hex,
            status=VideoJob.STATUS_PENDING,
        )

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        job = self.get_object()

        if job.status == VideoJob.STATUS_RUNNING:
            return Response({"code": 400, "message": "job is already running", "data": None}, status=400)

        task = render_novel_video_task.delay(job.id)
        job.task_id = task.id
        job.status = VideoJob.STATUS_PENDING
        job.error_message = ""
        job.save(update_fields=["task_id", "status", "error_message", "updated_at"])

        return Response({
            "code": 200,
            "message": "queued",
            "data": VideoJobSerializer(job).data,
        }, status=status.HTTP_200_OK)
