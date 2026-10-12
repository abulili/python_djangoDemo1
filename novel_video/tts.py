import asyncio
import json
import subprocess
import time
from pathlib import Path

from django.conf import settings


def run(cmd):
    completed = subprocess.run(cmd, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def ffprobe():
    return getattr(settings, "FFPROBE_PATH", "ffprobe")


def probe_duration(path):
    output = run([
        ffprobe(),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
    ])
    data = json.loads(output or "{}")
    duration = float((data.get("format") or {}).get("duration") or 0)
    return max(duration, 0)


async def _edge_tts(text, output, voice, rate, volume):
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError("edge-tts is not installed. Please run: pip install edge-tts") from exc

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        volume=volume,
    )
    await communicate.save(str(output))


def is_retryable_tts_error(exc):
    message = str(exc).lower()
    retry_markers = [
        "429",
        "too many requests",
        "invalid response status",
        "timeout",
        "temporarily unavailable",
        "connection reset",
        "server disconnected",
        "503",
        "502",
        "504",
    ]
    return any(marker in message for marker in retry_markers)


def tts_retry_sleep(attempt):
    delays = getattr(settings, "NOVEL_VIDEO_TTS_RETRY_DELAYS", "8,20,45")
    try:
        values = [float(item.strip()) for item in str(delays).split(",") if item.strip()]
    except ValueError:
        values = [8, 20, 45]
    if not values:
        values = [8, 20, 45]
    return values[min(attempt - 1, len(values) - 1)]


def synthesize_text(text, output, voice="", rate="", volume=""):
    text = (text or "").strip()
    if not text:
        return None, 0

    provider = getattr(settings, "NOVEL_VIDEO_TTS_PROVIDER", "edge")
    if provider != "edge":
        raise RuntimeError(f"unsupported tts provider: {provider}")

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    voice = voice or getattr(settings, "NOVEL_VIDEO_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
    rate = rate or getattr(settings, "NOVEL_VIDEO_TTS_RATE", "+0%")
    volume = volume or getattr(settings, "NOVEL_VIDEO_TTS_VOLUME", "+0%")

    max_retries = int(getattr(settings, "NOVEL_VIDEO_TTS_MAX_RETRIES", 3) or 3)
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            asyncio.run(_edge_tts(text, output, voice, rate, volume))
            return str(output), probe_duration(output)
        except Exception as exc:
            last_error = exc
            if output.exists():
                output.unlink(missing_ok=True)
            if attempt >= max_retries or not is_retryable_tts_error(exc):
                break
            time.sleep(tts_retry_sleep(attempt + 1))

    raise RuntimeError(
        "TTS generation failed after retries. "
        "edge-tts may be rate limited by Microsoft. "
        f"Last error: {last_error}"
    ) from last_error


def sleep_between_tts_requests():
    interval = float(getattr(settings, "NOVEL_VIDEO_TTS_REQUEST_INTERVAL_SECONDS", 1.5) or 0)
    if interval > 0:
        time.sleep(interval)


def prepare_tts(script, job, output_dir):
    output_dir = Path(output_dir)
    tts_dir = output_dir / "_tts"
    voice = job.tts_voice
    rate = job.tts_rate
    volume = job.tts_volume

    opening = script.get("opening") or {}
    if opening.get("audio_mode") == "tts" and opening.get("text"):
        audio_path, duration = synthesize_text(
            opening.get("text", ""),
            tts_dir / "opening.mp3",
            voice=voice,
            rate=rate,
            volume=volume,
        )
        opening["audio"] = {"path": audio_path, "duration": duration}
        if duration > 0:
            opening["duration"] = max(1, round(duration, 2))

    if not job.tts_enabled:
        return script

    if script.get("render_mode") == "sentence_card":
        for item in script.get("segments", []):
            index = int(item.get("index") or 0)
            audio_path, duration = synthesize_text(
                item.get("text", ""),
                tts_dir / f"segment_{index:03}.mp3",
                voice=voice,
                rate=rate,
                volume=volume,
            )
            item["narration"] = {"path": audio_path, "duration": duration}
            if duration > 0:
                item["duration"] = max(1, round(duration, 2))
            sleep_between_tts_requests()
        return script

    main = script.get("main") or {}
    audio_path, duration = synthesize_text(
        main.get("text", ""),
        tts_dir / "narration.mp3",
        voice=voice,
        rate=rate,
        volume=volume,
    )
    script.setdefault("audio", {})["narration"] = {"path": audio_path, "duration": duration}
    if duration > 0 and not int(main.get("duration") or 0):
        main["duration"] = max(1, round(duration, 2))
    return script
