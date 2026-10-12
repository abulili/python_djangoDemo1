import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urljoin

import requests
from django.conf import settings


BASE_DIR = Path(__file__).resolve().parent.parent
WORK_ROOT = Path(os.getenv("NOVEL_VIDEO_LOCAL_WORK_ROOT", BASE_DIR / "local_worker_runs"))

if not settings.configured:
    settings.configure(
        FFMPEG_PATH=os.getenv("FFMPEG_PATH", "ffmpeg"),
        FFPROBE_PATH=os.getenv("FFPROBE_PATH", "ffprobe"),
        MEDIA_ROOT=WORK_ROOT,
        NOVEL_VIDEO_STORAGE_ROOT=WORK_ROOT / "outputs",
        NOVEL_VIDEO_TTS_PROVIDER=os.getenv("NOVEL_VIDEO_TTS_PROVIDER", "edge"),
        NOVEL_VIDEO_TTS_VOICE=os.getenv("NOVEL_VIDEO_TTS_VOICE", "zh-CN-XiaoxiaoNeural"),
        NOVEL_VIDEO_TTS_RATE=os.getenv("NOVEL_VIDEO_TTS_RATE", "+0%"),
        NOVEL_VIDEO_TTS_VOLUME=os.getenv("NOVEL_VIDEO_TTS_VOLUME", "+0%"),
    )

from novel_video.models import VideoJob
from novel_video.renderer import render_video
from novel_video.script_builder import build_script
from novel_video.tasks import write_sentence_card_srt
from novel_video.tts import prepare_tts


class AssetObject(SimpleNamespace):
    def get_path(self):
        return getattr(self, "resolved_path", "") or getattr(self, "local_path", "")


def api_url(base_url, path):
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def ensure_ok(response):
    if response.status_code >= 400:
        raise RuntimeError(f"{response.status_code} {response.text}")
    return response


def get_payload(response):
    data = response.json()
    return data.get("data", data)


def login(base_url, username, password):
    response = requests.post(
        api_url(base_url, "token/"),
        json={"username": username, "password": password},
        timeout=30,
    )
    payload = ensure_ok(response).json()
    token = payload.get("access")
    if not token:
        raise RuntimeError("login succeeded but response has no access token")
    return token


def download_file(url, target, token=""):
    target.parent.mkdir(parents=True, exist_ok=True)
    headers = auth_headers(token) if token else {}
    with requests.get(url, headers=headers, stream=True, timeout=120) as response:
        ensure_ok(response)
        with target.open("wb") as writer:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    writer.write(chunk)
    return str(target)


def fetch_asset(base_url, token, asset_id):
    if not asset_id:
        return None
    response = requests.get(
        api_url(base_url, f"novel-video/assets/{asset_id}/"),
        headers=auth_headers(token),
        timeout=30,
    )
    return get_payload(ensure_ok(response))


def resolve_asset(asset_data, asset_dir, token):
    if not asset_data:
        return None

    asset = AssetObject(**asset_data)
    asset.resolved_path = ""

    if asset_data.get("storage_type") == "upload":
        url = asset_data.get("url")
        if not url:
            raise RuntimeError(f"uploaded asset has no url: {asset_data.get('id')}")
        suffix = Path(url.split("?")[0]).suffix or ".bin"
        asset.resolved_path = download_file(url, asset_dir / f"asset_{asset_data['id']}{suffix}", token="")
        return asset

    local_path = asset_data.get("local_path") or asset_data.get("path") or ""
    if not local_path:
        raise RuntimeError(f"local asset has no local_path: {asset_data.get('id')}")
    if not Path(local_path).is_file():
        raise RuntimeError(f"local asset not found on this computer: {local_path}")

    asset.resolved_path = local_path
    return asset


def build_job_object(job_data, assets):
    values = dict(job_data)
    for key, asset in assets.items():
        values[key] = asset
    values.setdefault("split_punctuation", [])
    values.setdefault("text_rules", {})
    values.setdefault("name_replacements", [])
    return SimpleNamespace(**values)


def upload_result(base_url, token, job_id, output, duration):
    files = {
        "final": open(output["final_path"], "rb"),
        "cover": open(output["cover_path"], "rb"),
    }
    subtitle_path = output.get("subtitle_path")
    if subtitle_path and Path(subtitle_path).is_file():
        files["subtitle"] = open(subtitle_path, "rb")

    try:
        response = requests.post(
            api_url(base_url, f"novel-video/jobs/{job_id}/upload-result/"),
            headers=auth_headers(token),
            data={"duration": str(round(duration, 2))},
            files=files,
            timeout=300,
        )
        ensure_ok(response)
    finally:
        for file_obj in files.values():
            file_obj.close()


def cleanup_intermediate_files(job_dir, output_dir):
    for target in [
        job_dir / "assets",
        output_dir / "_work",
        output_dir / "_tts",
    ]:
        if target.exists():
            shutil.rmtree(target)


def report_failed(base_url, token, job_id, error_message):
    requests.post(
        api_url(base_url, f"novel-video/jobs/{job_id}/report-failed/"),
        headers=auth_headers(token),
        json={"error_message": error_message[:4000]},
        timeout=30,
    )


def render_local_job(base_url, token, job_data, cleanup=True):
    started = time.time()
    job_id = job_data["id"]
    job_dir = WORK_ROOT / "jobs" / f"job_{job_id}"
    asset_dir = job_dir / "assets"
    output_dir = job_dir / "output"
    if job_dir.exists():
        shutil.rmtree(job_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    asset_ids = {
        "background_asset": job_data.get("background_asset"),
        "bgm_asset": job_data.get("bgm_asset"),
        "opening_audio_asset": job_data.get("opening_audio_asset"),
    }
    assets = {
        key: resolve_asset(fetch_asset(base_url, token, asset_id), asset_dir, token)
        for key, asset_id in asset_ids.items()
    }

    job = build_job_object(job_data, assets)
    script = build_script(job)
    script = prepare_tts(script, job, output_dir)

    script_path = output_dir / "script.json"
    script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")

    subtitle_path = ""
    if job.render_mode == VideoJob.MODE_SENTENCE_CARD:
        subtitle_file = output_dir / "subtitle.srt"
        write_sentence_card_srt(script, subtitle_file)
        subtitle_path = str(subtitle_file)

    render_result = render_video(script, output_dir)
    render_result["subtitle_path"] = subtitle_path

    result_path = output_dir / "job_result.json"
    result = {
        "job_id": job_id,
        "status": "success",
        "script_path": str(script_path),
        **render_result,
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    upload_result(base_url, token, job_id, render_result, time.time() - started)
    if cleanup:
        cleanup_intermediate_files(job_dir, output_dir)


def claim_job(base_url, token, worker_id=""):
    response = requests.post(
        api_url(base_url, "novel-video/jobs/claim-local/"),
        headers=auth_headers(token),
        json={"worker_id": worker_id} if worker_id else {},
        timeout=30,
    )
    payload = get_payload(ensure_ok(response))
    return payload


def run_loop(base_url, token, worker_id, interval, once=False, cleanup=True):
    print(f"local worker started: {worker_id or 'auto'}")
    print(f"api: {base_url}")
    print(f"work root: {WORK_ROOT}")

    while True:
        job = claim_job(base_url, token, worker_id)
        if not job:
            print("no pending local job")
            if once:
                return
            time.sleep(interval)
            continue

        job_id = job["id"]
        print(f"claimed job {job_id}: {job.get('title')}")
        try:
            render_local_job(base_url, token, job, cleanup=cleanup)
            print(f"job {job_id} uploaded")
        except Exception as exc:
            error_message = str(exc)
            print(f"job {job_id} failed: {error_message}", file=sys.stderr)
            report_failed(base_url, token, job_id, error_message)

        if once:
            return


def main():
    parser = argparse.ArgumentParser(description="Novel video local rendering worker")
    parser.add_argument("--api", default=os.getenv("NOVEL_VIDEO_API_URL", "http://127.0.0.1:8000/api/"))
    parser.add_argument("--token", default=os.getenv("NOVEL_VIDEO_TOKEN", ""))
    parser.add_argument("--username", default=os.getenv("NOVEL_VIDEO_USERNAME", ""))
    parser.add_argument("--password", default=os.getenv("NOVEL_VIDEO_PASSWORD", ""))
    parser.add_argument("--worker-id", default=os.getenv("NOVEL_VIDEO_WORKER_ID", ""))
    parser.add_argument("--interval", type=int, default=int(os.getenv("NOVEL_VIDEO_WORKER_INTERVAL", "5")))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--keep-files", action="store_true")
    args = parser.parse_args()

    token = args.token
    if not token:
        if not args.username or not args.password:
            raise SystemExit("missing auth. Pass --username/--password, or pass --token")
        token = login(args.api, args.username, args.password)

    run_loop(args.api, token, args.worker_id, args.interval, once=args.once, cleanup=not args.keep_files)


if __name__ == "__main__":
    main()
