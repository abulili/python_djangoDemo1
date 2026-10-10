from django.contrib import admin
from .models import MaterialAsset, VideoJob


@admin.register(MaterialAsset)
class MaterialAssetAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "material_type", "storage_type", "style", "is_shared", "owner", "created_at"]
    list_filter = ["material_type", "storage_type", "style", "is_shared"]
    search_fields = ["name", "local_path", "style"]


@admin.register(VideoJob)
class VideoJobAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "render_mode", "status", "owner", "created_at", "finished_at"]
    list_filter = ["render_mode", "status", "style"]
    search_fields = ["title", "trace_id", "task_id"]
    readonly_fields = ["script", "error_message", "trace_id", "task_id"]
