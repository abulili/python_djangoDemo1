import uuid
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import MaterialAsset, VideoJob
from .serializers import (
    MaterialAssetSerializer,
    VideoJobSerializer,
    file_name_from_storage_key,
    material_storage_key,
    validate_material_type_matches_file,
)
from .tasks import render_novel_video_task
from .asset_probe import probe_asset
from .storage import (
    assert_user_storage_available,
    create_presigned_upload_url,
    delete_storage_path,
    head_storage_object,
    key_to_storage_ref,
    key_to_virtual_path,
    notify_total_storage_if_needed,
    r2_public_base_url,
    storage_usage_payload,
    upload_fileobj_to_storage,
    r2_enabled,
)


class BytesUpload(BytesIO):
    def chunks(self, chunk_size=64 * 1024):
        self.seek(0)
        while True:
            chunk = self.read(chunk_size)
            if not chunk:
                break
            yield chunk


def parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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
        notify_total_storage_if_needed()

    def perform_destroy(self, instance):
        if instance.storage_type == MaterialAsset.STORAGE_UPLOAD and instance.file:
            delete_storage_path(instance.file.path)
        instance.delete()

    @action(detail=False, methods=["post"], url_path="direct-upload-url")
    def direct_upload_url(self, request):
        if not r2_enabled():
            return Response({"code": 400, "message": "R2 storage is not enabled", "data": None}, status=400)

        filename = request.data.get("filename") or "asset.bin"
        content_type = request.data.get("content_type") or "application/octet-stream"
        file_size = int(request.data.get("file_size") or 0)

        try:
            assert_user_storage_available(request.user, file_size)
        except ValidationError as exc:
            return Response({"code": 400, "message": str(exc), "data": storage_usage_payload(request.user)}, status=400)

        class UploadMeta:
            name = filename

        key = material_storage_key(request.user, UploadMeta())
        upload_url = create_presigned_upload_url(key, content_type=content_type, expires_in=3600)

        return Response({
            "code": 200,
            "message": "ok",
            "data": {
                "key": key,
                "upload_url": upload_url,
                "headers": {"Content-Type": content_type},
                "stored_path": key_to_storage_ref(key),
                "url": f"{r2_public_base_url()}{key}",
                "expires_in": 3600,
            },
        })

    @action(detail=False, methods=["post"], url_path="complete-direct-upload")
    def complete_direct_upload(self, request):
        key = str(request.data.get("key") or "").strip().lstrip("/")
        if not key or not key.startswith(f"materials/user_{request.user.id}/"):
            return Response({"code": 400, "message": "invalid upload key", "data": None}, status=400)

        try:
            head = head_storage_object(key)
        except Exception as exc:
            return Response({"code": 400, "message": f"uploaded object not found: {exc}", "data": None}, status=400)

        actual_size = int(head.get("ContentLength") or request.data.get("file_size") or 0)
        content_type = head.get("ContentType") or request.data.get("content_type") or ""
        requested_material_type = request.data.get("material_type") or MaterialAsset.TYPE_VIDEO
        try:
            material_type = validate_material_type_matches_file(requested_material_type, key, content_type)
        except ValidationError as exc:
            delete_storage_path(key_to_virtual_path(key))
            return Response({"code": 400, "message": str(exc), "data": None}, status=400)

        try:
            assert_user_storage_available(request.user, actual_size)
        except ValidationError as exc:
            delete_storage_path(key_to_virtual_path(key))
            return Response({"code": 400, "message": str(exc), "data": storage_usage_payload(request.user)}, status=400)

        tags = request.data.get("tags") or []
        if isinstance(tags, str):
            import json
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = []

        asset = MaterialAsset.objects.create(
            owner=request.user,
            name=request.data.get("name") or key.rsplit("/", 1)[-1],
            material_type=material_type,
            storage_type=MaterialAsset.STORAGE_UPLOAD,
            file=file_name_from_storage_key(key),
            style=request.data.get("style") or "",
            tags=tags if isinstance(tags, list) else [],
            is_shared=parse_bool(request.data.get("is_shared"), False),
            commercial_use=parse_bool(request.data.get("commercial_use"), True),
            file_size=actual_size,
        )
        probe_asset(asset, save=True)
        notify_total_storage_if_needed()

        return Response({
            "code": 200,
            "message": "created",
            "data": self.get_serializer(asset).data,
        }, status=status.HTTP_201_CREATED)

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

    def _queue_job(self, job):
        server_render_enabled = bool(getattr(settings, "NOVEL_VIDEO_SERVER_RENDER_ENABLED", False))
        if job.process_mode != VideoJob.PROCESS_LOCAL and not server_render_enabled:
            job.process_mode = VideoJob.PROCESS_LOCAL

        if job.process_mode == VideoJob.PROCESS_LOCAL:
            job.task_id = ""
            job.status = VideoJob.STATUS_PENDING
            job.error_message = ""
            job.finished_at = None
            job.save(update_fields=["process_mode", "task_id", "status", "error_message", "finished_at", "updated_at"])
            return "queued for local worker"

        task = render_novel_video_task.delay(job.id)
        job.task_id = task.id
        job.status = VideoJob.STATUS_PENDING
        job.error_message = ""
        job.finished_at = None
        job.save(update_fields=["process_mode", "task_id", "status", "error_message", "finished_at", "updated_at"])
        return "queued"

    def perform_create(self, serializer):
        process_mode = serializer.validated_data.get("process_mode") or VideoJob.PROCESS_LOCAL
        job = serializer.save(
            owner=self.request.user,
            trace_id=uuid.uuid4().hex,
            status=VideoJob.STATUS_PENDING,
            process_mode=process_mode,
        )
        self._queue_job(job)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        job = self.get_object()

        if job.status == VideoJob.STATUS_RUNNING:
            return Response({"code": 400, "message": "job is already running", "data": None}, status=400)

        message = self._queue_job(job)
        return Response({
            "code": 200,
            "message": message,
            "data": self.get_serializer(job).data,
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="claim-local")
    def claim_local(self, request):
        worker_id = request.data.get("worker_id", "")
        job = (
            self.get_queryset()
            .filter(process_mode=VideoJob.PROCESS_LOCAL, status=VideoJob.STATUS_PENDING)
            .order_by("created_at")
            .first()
        )
        if not job:
            return Response({"code": 204, "message": "no pending local job", "data": None}, status=status.HTTP_200_OK)

        job.status = VideoJob.STATUS_RUNNING
        job.task_id = worker_id or f"local-user-{request.user.id}-job-{job.id}"
        job.error_message = ""
        job.save(update_fields=["status", "task_id", "error_message", "updated_at"])
        return Response({"code": 200, "message": "claimed", "data": self.get_serializer(job).data})

    @action(detail=True, methods=["post"], url_path="report-failed")
    def report_failed(self, request, pk=None):
        job = self.get_object()
        job.status = VideoJob.STATUS_FAILED
        job.error_message = request.data.get("error_message", "local worker failed")
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        return Response({"code": 200, "message": "reported", "data": self.get_serializer(job).data})

    @action(detail=True, methods=["post"], url_path="upload-result")
    def upload_result(self, request, pk=None):
        job = self.get_object()
        storage_root = Path(getattr(settings, "NOVEL_VIDEO_STORAGE_ROOT", Path(settings.MEDIA_ROOT) / "novel_video"))
        output_dir = storage_root / "jobs" / f"job_{job.id}"

        file_map = {
            "final": ("final.mp4", "final_path", "video/mp4"),
            "cover": ("cover.png", "cover_path", "image/png"),
            "subtitle": ("subtitle.srt", "subtitle_path", "application/x-subrip"),
        }
        incoming_size = sum(int(getattr(item, "size", 0) or 0) for item in request.FILES.values())
        try:
            assert_user_storage_available(request.user, incoming_size, exclude_job=job)
        except ValidationError as exc:
            return Response({"code": 400, "message": str(exc), "data": storage_usage_payload(request.user)}, status=400)

        if job.output_dir:
            delete_storage_path(job.output_dir)
        if not r2_enabled():
            output_dir.mkdir(parents=True, exist_ok=True)

        for field, (filename, attr, default_content_type) in file_map.items():
            uploaded = request.FILES.get(field)
            if not uploaded:
                continue
            key = f"jobs/job_{job.id}/{filename}"
            content_type = getattr(uploaded, "content_type", "") or default_content_type
            setattr(job, attr, upload_fileobj_to_storage(uploaded, key, content_type=content_type))

        job.output_dir = str(output_dir)
        job.output_size = incoming_size
        job.status = VideoJob.STATUS_SUCCESS
        job.error_message = ""
        if request.data.get("duration"):
            try:
                job.duration = float(request.data.get("duration"))
            except (TypeError, ValueError):
                pass
        job.finished_at = timezone.now()
        job.save()
        notify_total_storage_if_needed()
        return Response({"code": 200, "message": "uploaded", "data": self.get_serializer(job).data})


    @action(detail=False, methods=["get"], url_path="storage-usage")
    def storage_usage(self, request):
        return Response({"code": 200, "message": "ok", "data": storage_usage_payload(request.user)})

    @action(detail=False, methods=["post"], url_path="test-r2-upload")
    def test_r2_upload(self, request):
        key = f"tests/user_{request.user.id}/{uuid.uuid4().hex}.txt"
        content = (
            "novel video r2 upload test\n"
            f"user_id={request.user.id}\n"
            f"created_at={timezone.now().isoformat()}\n"
        ).encode("utf-8")
        upload = BytesUpload(content)

        try:
            stored_path = upload_fileobj_to_storage(upload, key, content_type="text/plain; charset=utf-8")
        except Exception as exc:
            return Response({
                "code": 500,
                "message": str(exc),
                "data": {
                    "key": key,
                    "storage_backend": getattr(settings, "NOVEL_VIDEO_STORAGE_BACKEND", "local"),
                    "bucket": getattr(settings, "R2_BUCKET_NAME", ""),
                    "endpoint_configured": bool(getattr(settings, "R2_ENDPOINT_URL", "")),
                    "access_key_configured": bool(getattr(settings, "R2_ACCESS_KEY_ID", "")),
                    "secret_key_configured": bool(getattr(settings, "R2_SECRET_ACCESS_KEY", "")),
                },
            }, status=500)

        public_base = getattr(settings, "NOVEL_VIDEO_STORAGE_URL", "").rstrip("/")
        return Response({
            "code": 200,
            "message": "uploaded",
            "data": {
                "key": key,
                "stored_path": stored_path,
                "url": f"{public_base}/{key}" if public_base else "",
            },
        })

    def perform_destroy(self, instance):
        if instance.output_dir:
            delete_storage_path(instance.output_dir)
        else:
            for path in [instance.final_path, instance.cover_path, instance.subtitle_path]:
                delete_storage_path(path)
        instance.delete()
