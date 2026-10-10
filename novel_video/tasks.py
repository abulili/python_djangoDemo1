import json
import time
import uuid
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from ai_log.models import AiTraceStepLog
from .models import VideoJob
from .renderer import render_video
from .script_builder import build_script


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
        duration = int(item.get("duration", 3))
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


@shared_task(bind=True)
def render_novel_video_task(self, job_id):
    started = time.time()
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

        script = build_script(job)

        output_dir = Path(settings.BASE_DIR) / "reports" / "novel_video" / f"job_{job.id}"
        output_dir.mkdir(parents=True, exist_ok=True)

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

        job.status = VideoJob.STATUS_SUCCESS
        job.script = script
        job.output_dir = str(output_dir)
        job.final_path = render_result["final_path"]
        job.cover_path = render_result["cover_path"]
        job.subtitle_path = subtitle_path
        job.duration = round(time.time() - started, 2)
        job.finished_at = timezone.now()
        job.save()

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
        job.status = VideoJob.STATUS_FAILED
        job.error_message = str(e)
        job.duration = round(time.time() - started, 2)
        job.finished_at = timezone.now()
        job.save()

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