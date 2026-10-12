from pathlib import Path

from django.conf import settings
from rest_framework import serializers

from .asset_probe import probe_asset
from .models import MaterialAsset, VideoJob
from .storage import (
    assert_user_storage_available,
    delete_storage_path,
    file_size,
    key_to_storage_ref,
    path_to_key,
    storage_public_url,
    upload_fileobj_to_storage,
)


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


def material_storage_key(owner, uploaded_file):
    import uuid

    suffix = Path(getattr(uploaded_file, "name", "")).suffix or ".bin"
    owner_id = getattr(owner, "id", "unknown")
    return f"materials/user_{owner_id}/{uuid.uuid4().hex}{suffix}"


def file_name_from_storage_key(key):
    return f"novel_video/{key}"


def guess_material_type(filename="", content_type=""):
    suffix = Path(filename or "").suffix.lower()
    content_type = (content_type or "").lower()
    if content_type.startswith("image/") or suffix in IMAGE_SUFFIXES:
        return MaterialAsset.TYPE_IMAGE
    if content_type.startswith("video/") or suffix in VIDEO_SUFFIXES:
        return MaterialAsset.TYPE_VIDEO
    if content_type.startswith("audio/") or suffix in AUDIO_SUFFIXES:
        return MaterialAsset.TYPE_AUDIO
    return ""


def validate_material_type_matches_file(material_type, filename="", content_type=""):
    actual_type = guess_material_type(filename, content_type)
    if actual_type and material_type and actual_type != material_type:
        raise serializers.ValidationError(
            f"material_type mismatch: selected {material_type}, but file looks like {actual_type}"
        )
    return actual_type or material_type


class MaterialAssetSerializer(serializers.ModelSerializer):
    path = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = MaterialAsset
        fields = "__all__"
        read_only_fields = ["id", "owner", "created_at", "path", "url", "file_size"]

    def get_path(self, obj):
        if obj.storage_type == MaterialAsset.STORAGE_UPLOAD and obj.file:
            return key_to_storage_ref(path_to_key(obj.file.path))
        return obj.get_path()

    def get_url(self, obj):
        if obj.storage_type != MaterialAsset.STORAGE_UPLOAD or not obj.file:
            return ""

        public_url = storage_public_url(obj.file.path)
        if public_url:
            return public_url

        url = obj.file.url
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(url)
        return url

    def validate(self, data):
        storage_type = data.get(
            "storage_type",
            self.instance.storage_type if self.instance else MaterialAsset.STORAGE_LOCAL,
        )

        current_local_path = self.instance.local_path if self.instance else ""
        if storage_type == MaterialAsset.STORAGE_LOCAL and not data.get("local_path") and not current_local_path:
            raise serializers.ValidationError("local_path is required when storage_type is local")

        current_file = self.instance.file if self.instance else None
        uploaded_file = data.get("file")
        if storage_type == MaterialAsset.STORAGE_UPLOAD and not uploaded_file and not current_file:
            raise serializers.ValidationError("file is required when storage_type is upload")

        if storage_type == MaterialAsset.STORAGE_UPLOAD and uploaded_file:
            data["material_type"] = validate_material_type_matches_file(
                data.get("material_type", self.instance.material_type if self.instance else ""),
                getattr(uploaded_file, "name", ""),
                getattr(uploaded_file, "content_type", ""),
            )
            request = self.context.get("request")
            owner = self.instance.owner if self.instance else getattr(request, "user", None)
            old_size = self.instance.file_size if self.instance else 0
            incoming_size = max(int(getattr(uploaded_file, "size", 0) or 0) - int(old_size or 0), 0)
            if owner and getattr(owner, "is_authenticated", False):
                try:
                    assert_user_storage_available(owner, incoming_size)
                except Exception as exc:
                    raise serializers.ValidationError(str(exc)) from exc

        return data

    def create(self, validated_data):
        uploaded_file = validated_data.pop("file", None)
        if validated_data.get("storage_type") == MaterialAsset.STORAGE_UPLOAD and uploaded_file:
            key = material_storage_key(validated_data.get("owner"), uploaded_file)
            upload_fileobj_to_storage(uploaded_file, key, content_type=getattr(uploaded_file, "content_type", ""))
            validated_data["file"] = file_name_from_storage_key(key)
            validated_data["file_size"] = int(getattr(uploaded_file, "size", 0) or 0)

        asset = super().create(validated_data)
        probe_asset(asset, save=True)
        return asset

    def update(self, instance, validated_data):
        old_file_path = instance.file.path if instance.file else ""
        uploaded_file = validated_data.pop("file", None)
        new_file_name = ""
        new_file_size = 0
        if validated_data.get("storage_type", instance.storage_type) == MaterialAsset.STORAGE_UPLOAD and uploaded_file:
            key = material_storage_key(instance.owner, uploaded_file)
            upload_fileobj_to_storage(uploaded_file, key, content_type=getattr(uploaded_file, "content_type", ""))
            new_file_name = file_name_from_storage_key(key)
            new_file_size = int(getattr(uploaded_file, "size", 0) or 0)

        asset = super().update(instance, validated_data)
        if new_file_name:
            asset.file.name = new_file_name
            asset.file_size = new_file_size or file_size(asset.file.path)
            asset.save(update_fields=["file", "file_size"])
            if old_file_path and old_file_path != asset.file.path:
                delete_storage_path(old_file_path)
        elif asset.storage_type == MaterialAsset.STORAGE_UPLOAD and asset.file:
            asset.file_size = asset.file_size or file_size(asset.file.path)
            asset.save(update_fields=["file_size"])
        else:
            asset.file_size = 0
            asset.save(update_fields=["file_size"])
        probe_asset(asset, save=True)
        return asset


class VideoJobSerializer(serializers.ModelSerializer):
    final_url = serializers.SerializerMethodField()
    cover_url = serializers.SerializerMethodField()
    subtitle_url = serializers.SerializerMethodField()

    class Meta:
        model = VideoJob
        fields = "__all__"
        read_only_fields = [
            "id", "owner", "status", "task_id", "trace_id", "script",
            "output_dir", "final_path", "cover_path", "subtitle_path",
            "error_message", "duration", "created_at", "updated_at",
            "finished_at", "final_url", "cover_url", "subtitle_url", "output_size",
        ]

    def _path_to_url(self, path):
        if not path:
            return ""

        public_url = storage_public_url(path)
        if public_url:
            return public_url

        try:
            file_path = Path(path).resolve()
        except OSError:
            return ""

        url = self._relative_url(
            file_path,
            getattr(settings, "NOVEL_VIDEO_STORAGE_ROOT", Path(settings.MEDIA_ROOT) / "novel_video"),
            getattr(settings, "NOVEL_VIDEO_STORAGE_URL", f"{settings.MEDIA_URL.rstrip('/')}/novel_video/"),
        )
        if not url:
            url = self._relative_url(file_path, settings.MEDIA_ROOT, settings.MEDIA_URL)
        if not url:
            return ""

        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(url)
        return url

    def _relative_url(self, file_path, root, url_prefix):
        try:
            relative_path = file_path.relative_to(Path(root).resolve()).as_posix()
        except (OSError, ValueError):
            return ""
        return f"{str(url_prefix).rstrip('/')}/{relative_path}"

    def get_final_url(self, obj):
        return self._path_to_url(obj.final_path)

    def get_cover_url(self, obj):
        return self._path_to_url(obj.cover_path)

    def get_subtitle_url(self, obj):
        return self._path_to_url(obj.subtitle_path)

    def validate(self, data):
        current_title = self.instance.title if self.instance else ""
        current_text = self.instance.novel_text if self.instance else ""
        current_background = self.instance.background_asset if self.instance else None
        background_asset = data.get("background_asset", current_background)
        bgm_asset = data.get("bgm_asset", self.instance.bgm_asset if self.instance else None)
        opening_audio_asset = data.get("opening_audio_asset", self.instance.opening_audio_asset if self.instance else None)

        if not data.get("title") and not current_title:
            raise serializers.ValidationError("title is required")
        if not data.get("novel_text") and not current_text:
            raise serializers.ValidationError("novel_text is required")
        if not background_asset:
            raise serializers.ValidationError("background_asset is required")
        if background_asset and background_asset.material_type not in [MaterialAsset.TYPE_IMAGE, MaterialAsset.TYPE_VIDEO]:
            raise serializers.ValidationError("background_asset must be an image or video")
        if bgm_asset and bgm_asset.material_type != MaterialAsset.TYPE_AUDIO:
            raise serializers.ValidationError("bgm_asset must be an audio asset")
        if opening_audio_asset and opening_audio_asset.material_type != MaterialAsset.TYPE_AUDIO:
            raise serializers.ValidationError("opening_audio_asset must be an audio asset")
        return data
