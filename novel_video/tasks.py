import json
import time
import uuid
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from ai_log.models import AiTraceStepLog
from .models import VideoJob
from .renderer import render_video
from .script_builder import build_script
from .tts import prepare_tts
from .storage import (
    assert_user_storage_available,
    delete_local_storage_path,
    delete_storage_path,
    download_file_from_storage,
    notify_total_storage_if_needed,
    r2_enabled,
    tree_size,
    upload_file_to_storage,
)


def srt_time(seconds):
    ms = int(seconds * 1000)
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def write_sentence_card_srt(script, path):
    current = 0
    blocks = []

    for item in script.get("segments", []):
        duration = float(item.get("duration", 3))
        start = current
        end = current + duration
        blocks.append(
            f"{item['index']}\n"
            f"{srt_time(start)} --> {srt_time(end)}\n"
            f"{item['text']}\n"
        )
        current = end

    Path(path).write_text("\n".join(blocks), encoding="utf-8")
    return current


def iter_asset_nodes(value):
    if isinstance(value, dict):
        if value.get("path") and value.get("storage_type") == "upload":
            yield value
        for child in value.values():
            yield from iter_asset_nodes(child)
    elif isinstance(value, list):
        for item in value:
            yield from iter_asset_nodes(item)


def localize_script_assets(script, output_dir):
    if not r2_enabled():
        return script

    asset_dir = Path(output_dir) / "_assets"
    downloaded = {}
    for node in iter_asset_nodes(script):
        source_path = node.get("path") or ""
        if not source_path:
            continue
        source = Path(source_path)
        if source.is_file():
            continue
        if source_path in downloaded:
            node["path"] = downloaded[source_path]
            continue

        asset_id = node.get("asset_id") or "asset"
        suffix = source.suffix or ".bin"
        target = asset_dir / f"asset_{asset_id}{suffix}"
        local_path = download_file_from_storage(source_path, target)
        downloaded[source_path] = local_path
        node["path"] = local_path

    return script


@shared_task(bind=True)
def render_novel_video_task(self, job_id):
    started = time.time()
    output_dir = None
    close_old_connections()
    job = VideoJob.objects.select_related(
        "owner",
        "background_asset",
        "bgm_asset",
        "opening_audio_asset",
    ).get(id=job_id)

    job.status = VideoJob.STATUS_RUNNING
    job.task_id = self.request.id or ""
    job.trace_id = job.trace_id or uuid.uuid4().hex
    job.error_message = ""
    job.save(update_fields=["status", "task_id", "trace_id", "error_message", "updated_at"])

    try:
        AiTraceStepLog.objects.create(
            user=job.owner,
            trace_id=job.trace_id,
            step="novel_video_start",
            query=job.title,
            detail={"job_id": job.id, "render_mode": job.render_mode},
        )

        storage_root = Path(getattr(settings, "NOVEL_VIDEO_STORAGE_ROOT", Path(settings.MEDIA_ROOT) / "novel_video"))
        output_dir = storage_root / "jobs" / f"job_{job.id}"
        if job.output_dir:
            delete_storage_path(job.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        script = build_script(job)
        script = prepare_tts(script, job, output_dir)
        script = localize_script_assets(script, output_dir)

        script_path = output_dir / "script.json"
        script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")

        subtitle_path = ""
        if job.render_mode == VideoJob.MODE_SENTENCE_CARD:
            subtitle_file = output_dir / "subtitle.srt"
            write_sentence_card_srt(script, subtitle_file)
            subtitle_path = str(subtitle_file)

        render_result = render_video(script, output_dir)

        result = {
            "job_id": job.id,
            "status": "success",
            "script_path": str(script_path),
            "subtitle_path": subtitle_path,
            **render_result,
        }

        (output_dir / "job_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        result_files = [Path(render_result["final_path"]), Path(render_result["cover_path"])]
        if subtitle_path:
            result_files.append(Path(subtitle_path))
        output_size = sum(path.stat().st_size for path in result_files if path.is_file())
        assert_user_storage_available(job.owner, output_size, exclude_job=job)

        final_path = upload_file_to_storage(
            render_result["final_path"],
            f"jobs/job_{job.id}/final.mp4",
            content_type="video/mp4",
        )
        cover_path = upload_file_to_storage(
            render_result["cover_path"],
            f"jobs/job_{job.id}/cover.png",
            content_type="image/png",
        )
        remote_subtitle_path = ""
        if subtitle_path:
            remote_subtitle_path = upload_file_to_storage(
                subtitle_path,
                f"jobs/job_{job.id}/subtitle.srt",
                content_type="application/x-subrip",
            )

        close_old_connections()
        job = VideoJob.objects.get(id=job.id)
        job.status = VideoJob.STATUS_SUCCESS
        job.script = script
        job.output_dir = str(output_dir)
        job.final_path = final_path
        job.cover_path = cover_path
        job.subtitle_path = remote_subtitle_path
        job.output_size = output_size
        job.duration = round(time.time() - started, 2)
        job.finished_at = timezone.now()
        job.save()
        notify_total_storage_if_needed()
        delete_local_storage_path(output_dir)

        close_old_connections()
        AiTraceStepLog.objects.create(
            user=job.owner,
            trace_id=job.trace_id,
            step="novel_video_success",
            query=job.title,
            success=True,
            duration=job.duration,
            detail=result,
        )

        return result

    except Exception as e:
        if output_dir:
            delete_local_storage_path(output_dir)
        close_old_connections()
        job = VideoJob.objects.get(id=job.id)
        job.status = VideoJob.STATUS_FAILED
        job.error_message = str(e)
        job.duration = round(time.time() - started, 2)
        job.finished_at = timezone.now()
        job.save()

        close_old_connections()
        AiTraceStepLog.objects.create(
            user=job.owner,
            trace_id=job.trace_id,
            step="novel_video_failed",
            query=job.title,
            success=False,
            error_message=str(e),
            duration=job.duration,
            detail={"job_id": job.id},
        )

        return {"status": "failed", "error": str(e), "job_id": job.id}
