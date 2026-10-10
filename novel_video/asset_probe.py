import json
import subprocess
from pathlib import Path

from django.conf import settings


def ffprobe():
    return getattr(settings, "FFPROBE_PATH", "ffprobe")


def run(cmd):
    completed = subprocess.run(cmd, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def probe_duration(path):
    output = run([
        ffprobe(),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ])
    data = json.loads(output or "{}")
    duration = (data.get("format") or {}).get("duration")
    return float(duration or 0)


def probe_asset(asset, save=False):
    path = Path(asset.get_path() or "")
    if not path.exists():
        return {
            "ok": False,
            "error": f"asset path not found: {path}",
            "duration": asset.duration,
        }
    if not path.is_file():
        return {
            "ok": False,
            "error": f"asset path is not a file: {path}",
            "duration": asset.duration,
        }

    try:
        duration = probe_duration(path)
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "duration": asset.duration,
        }

    asset.duration = round(duration, 3)
    if save:
        asset.save(update_fields=["duration"])

    return {
        "ok": True,
        "error": "",
        "duration": asset.duration,
    }
