import os
import shutil
from pathlib import Path

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone


GB = 1024 * 1024 * 1024


def user_storage_limit_bytes():
    return int(getattr(settings, "NOVEL_VIDEO_USER_STORAGE_LIMIT_BYTES", GB))


def total_storage_alert_bytes():
    return int(getattr(settings, "NOVEL_VIDEO_TOTAL_STORAGE_ALERT_BYTES", 8 * GB))


def storage_enabled():
    return bool(getattr(settings, "NOVEL_VIDEO_STORAGE_ENABLED", True))


def file_size(path):
    if not path:
        return 0
    try:
        target = Path(path)
        return target.stat().st_size if target.is_file() else 0
    except OSError:
        return 0


def tree_size(path):
    if not path:
        return 0
    root = Path(path)
    if root.is_file():
        return file_size(root)
    if not root.exists():
        return 0
    total = 0
    for item in root.rglob("*"):
        if item.is_file():
            total += file_size(item)
    return total



def storage_backend():
    return str(getattr(settings, "NOVEL_VIDEO_STORAGE_BACKEND", "local") or "local").lower()


def r2_enabled():
    return storage_backend() == "r2"


def _r2_setting(name, default=""):
    return str(getattr(settings, name, "") or os.getenv(name, default) or default).strip()


def r2_bucket_name():
    return _r2_setting("R2_BUCKET_NAME")


def r2_public_base_url():
    return (_r2_setting("R2_PUBLIC_BASE_URL") or getattr(settings, "NOVEL_VIDEO_STORAGE_URL", "")).rstrip("/") + "/"


def key_to_storage_ref(key):
    if r2_enabled():
        return f"r2://{r2_bucket_name()}/{key.lstrip('/')}"
    return str(storage_root() / key.replace("/", os.sep))


def storage_public_url(path):
    if not path:
        return ""
    key = path_to_key(path)
    marker = "novel_video/"
    if key.startswith(marker):
        key = key[len(marker):]
    if r2_enabled() and key:
        return f"{r2_public_base_url()}{key}"
    return ""


def r2_is_configured():
    endpoint = _r2_setting("R2_ENDPOINT_URL")
    return bool(
        r2_bucket_name()
        and endpoint
        and "ACCOUNT_ID" not in endpoint
        and _r2_setting("R2_ACCESS_KEY_ID")
        and _r2_setting("R2_SECRET_ACCESS_KEY")
    )


def r2_client():
    if not r2_is_configured():
        raise RuntimeError("R2 is not configured. Please set R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY and R2_BUCKET_NAME.")
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=_r2_setting("R2_ENDPOINT_URL"),
        aws_access_key_id=_r2_setting("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=_r2_setting("R2_SECRET_ACCESS_KEY"),
        region_name=_r2_setting("R2_REGION", "auto"),
    )


def storage_root():
    return Path(getattr(settings, "NOVEL_VIDEO_STORAGE_ROOT", Path(settings.MEDIA_ROOT) / "novel_video"))


def key_to_virtual_path(key):
    return str(storage_root() / key.replace("/", os.sep))


def path_to_key(path):
    if not path:
        return ""
    value = str(path).replace("\\", "/")
    if value.startswith("r2://"):
        parts = value.split("/", 3)
        return parts[3] if len(parts) > 3 else ""
    try:
        return Path(path).resolve().relative_to(storage_root().resolve()).as_posix()
    except (OSError, ValueError):
        return value.lstrip("/")


def candidate_storage_keys(path):
    key = path_to_key(path)
    keys = []
    for item in [key]:
        if item and item not in keys:
            keys.append(item)

    value = str(path or "").replace("\\", "/").lstrip("/")
    marker = "novel_video/"
    if marker in value:
        legacy_key = value[value.index(marker):]
        if legacy_key and legacy_key not in keys:
            keys.append(legacy_key)

    if key:
        if key.startswith(marker):
            without_prefix = key[len(marker):]
            if without_prefix and without_prefix not in keys:
                keys.append(without_prefix)
        else:
            with_prefix = f"{marker}{key}"
            if with_prefix not in keys:
                keys.append(with_prefix)

    return keys


def upload_file_to_storage(local_path, key, content_type=None):
    if not r2_enabled():
        return str(local_path)
    extra_args = {}
    if content_type:
        extra_args["ContentType"] = content_type
    client = r2_client()
    kwargs = {"ExtraArgs": extra_args} if extra_args else {}
    client.upload_file(str(local_path), r2_bucket_name(), key, **kwargs)
    return key_to_storage_ref(key)


def create_presigned_upload_url(key, content_type=None, expires_in=3600):
    if not r2_enabled():
        raise RuntimeError("Direct upload is only available when R2 storage is enabled.")

    params = {
        "Bucket": r2_bucket_name(),
        "Key": key,
    }
    if content_type:
        params["ContentType"] = content_type

    return r2_client().generate_presigned_url(
        "put_object",
        Params=params,
        ExpiresIn=int(expires_in or 3600),
    )


def head_storage_object(key):
    if not r2_enabled():
        return {}
    return r2_client().head_object(Bucket=r2_bucket_name(), Key=key)


def upload_fileobj_to_storage(file_obj, key, content_type=None):
    if not r2_enabled():
        target = storage_root() / key
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as writer:
            for chunk in file_obj.chunks():
                writer.write(chunk)
        return str(target)

    extra_args = {}
    if content_type:
        extra_args["ContentType"] = content_type
    client = r2_client()
    file_obj.seek(0)
    kwargs = {"ExtraArgs": extra_args} if extra_args else {}
    client.upload_fileobj(file_obj, r2_bucket_name(), key, **kwargs)
    return key_to_storage_ref(key)


def download_file_from_storage(stored_path, target_path):
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    source = Path(str(stored_path or ""))
    if source.is_file():
        if source.resolve() != target_path.resolve():
            shutil.copyfile(source, target_path)
        return str(target_path)

    if not r2_enabled():
        raise FileNotFoundError(f"storage file not found: {stored_path}")

    keys = candidate_storage_keys(stored_path)
    if not keys:
        raise FileNotFoundError(f"storage key not found for path: {stored_path}")

    client = r2_client()
    bucket = r2_bucket_name()
    last_error = None
    for key in keys:
        try:
            client.download_file(bucket, key, str(target_path))
            return str(target_path)
        except Exception as exc:
            last_error = exc
            error_code = getattr(getattr(exc, "response", None), "get", lambda *_: {})("Error", {}).get("Code", "")
            if error_code not in {"404", "NoSuchKey", "NotFound"}:
                raise

    raise FileNotFoundError(f"storage object not found for path: {stored_path}; tried keys: {keys}; last error: {last_error}")


def upload_directory_to_storage(local_dir, prefix):
    uploaded = {}
    for item in Path(local_dir).rglob("*"):
        if not item.is_file():
            continue
        key = f"{prefix.rstrip('/')}/{item.relative_to(local_dir).as_posix()}"
        uploaded[item.name] = upload_file_to_storage(item, key)
    return uploaded


def delete_local_storage_path(path):
    if not path or not is_safe_storage_path(path):
        return 0
    target = Path(path)
    released = tree_size(target)
    if target.is_file():
        target.unlink(missing_ok=True)
    elif target.is_dir():
        shutil.rmtree(target)
    return released


def delete_r2_key(key):
    if not r2_enabled() or not r2_is_configured() or not key:
        return
    r2_client().delete_object(Bucket=r2_bucket_name(), Key=key)


def delete_r2_prefix(prefix):
    if not r2_enabled() or not r2_is_configured() or not prefix:
        return
    client = r2_client()
    bucket = r2_bucket_name()
    continuation_token = None
    while True:
        params = {"Bucket": bucket, "Prefix": prefix.rstrip("/") + "/"}
        if continuation_token:
            params["ContinuationToken"] = continuation_token
        response = client.list_objects_v2(**params)
        objects = [{"Key": item["Key"]} for item in response.get("Contents", [])]
        if objects:
            client.delete_objects(Bucket=bucket, Delete={"Objects": objects})
        if not response.get("IsTruncated"):
            break
        continuation_token = response.get("NextContinuationToken")

def _sum_bytes(queryset, field):
    return int(queryset.aggregate(total=Sum(field)).get("total") or 0)


def user_storage_bytes(user, exclude_job=None):
    from .models import MaterialAsset, VideoJob

    assets = MaterialAsset.objects.filter(owner=user, storage_type=MaterialAsset.STORAGE_UPLOAD)
    jobs = VideoJob.objects.filter(owner=user)
    if exclude_job is not None:
        jobs = jobs.exclude(id=exclude_job.id)
    return _sum_bytes(assets, "file_size") + _sum_bytes(jobs, "output_size")


def total_storage_bytes():
    from .models import MaterialAsset, VideoJob

    return _sum_bytes(MaterialAsset.objects.filter(storage_type=MaterialAsset.STORAGE_UPLOAD), "file_size") + _sum_bytes(
        VideoJob.objects.all(), "output_size"
    )


def storage_usage_payload(user):
    used = user_storage_bytes(user)
    limit = user_storage_limit_bytes()
    total_used = total_storage_bytes()
    total_alert = total_storage_alert_bytes()
    return {
        "user_used_bytes": used,
        "user_limit_bytes": limit,
        "user_remaining_bytes": max(limit - used, 0),
        "user_percent": round(used / limit * 100, 2) if limit else 0,
        "total_used_bytes": total_used,
        "total_alert_bytes": total_alert,
        "total_percent": round(total_used / total_alert * 100, 2) if total_alert else 0,
        "storage_enabled": storage_enabled(),
    }


def assert_storage_enabled():
    if not storage_enabled():
        raise ValidationError("Online storage is disabled. Please try again later.")


def assert_user_storage_available(user, incoming_bytes, exclude_job=None):
    assert_storage_enabled()
    limit = user_storage_limit_bytes()
    used = user_storage_bytes(user, exclude_job=exclude_job)
    if used + int(incoming_bytes or 0) > limit:
        raise ValidationError(
            f"Storage limit exceeded. Used {used} bytes, incoming {int(incoming_bytes or 0)} bytes, limit {limit} bytes. Please delete old videos or uploaded materials first."
        )


def notify_total_storage_if_needed():
    if not getattr(settings, "NOVEL_VIDEO_STORAGE_ALERT_ENABLED", True):
        return
    used = total_storage_bytes()
    threshold = total_storage_alert_bytes()
    if used < threshold:
        return

    today = timezone.localdate().isoformat()
    cache_key = f"novel_video_storage_alert:{today}:{threshold}"
    if cache.get(cache_key):
        return

    webhook = getattr(settings, "FEISHU_BOT_WEBHOOK", "") or getattr(settings, "NOVEL_VIDEO_FEISHU_WEBHOOK", "")
    if not webhook:
        cache.set(cache_key, True, 24 * 3600)
        return

    text = f"???????????????{used / GB:.2f}GB / {threshold / GB:.2f}GB?????????????????"
    try:
        requests.post(webhook, json={"msg_type": "text", "content": {"text": text}}, timeout=8)
        cache.set(cache_key, True, 24 * 3600)
    except requests.RequestException:
        pass


def _allowed_roots():
    roots = [getattr(settings, "MEDIA_ROOT", ""), getattr(settings, "NOVEL_VIDEO_STORAGE_ROOT", "")]
    result = []
    for root in roots:
        if root:
            try:
                result.append(Path(root).resolve())
            except OSError:
                pass
    return result


def is_safe_storage_path(path):
    if not path:
        return False
    try:
        target = Path(path).resolve()
    except OSError:
        return False
    for root in _allowed_roots():
        try:
            target.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def delete_storage_path(path):
    if not path:
        return 0

    if r2_enabled():
        key = path_to_key(path)
        if Path(key).suffix:
            delete_r2_key(key)
        else:
            delete_r2_prefix(key)

    return delete_local_storage_path(path)
