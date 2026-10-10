from django.db import models

# Create your models here.
from django.conf import settings

class MaterialAsset(models.Model):
    # 记录素材
    STORAGE_LOCAL = "local"
    STORAGE_UPLOAD = "upload"

    TYPE_VIDEO = "video"
    TYPE_AUDIO = "audio"
    TYPE_IMAGE = "image"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    material_type = models.CharField(max_length=20, default=TYPE_VIDEO)
    storage_type = models.CharField(max_length=20, default=STORAGE_LOCAL)
    local_path = models.CharField(max_length=500, blank=True, default="")
    file = models.FileField(upload_to="novel_video/materials/", blank=True, null=True)

    style = models.CharField(max_length=50, blank=True, default="", db_index=True)
    tags = models.JSONField(default=list, blank=True)
    duration = models.FloatField(default=0, blank=True)
    aspect_ratio = models.CharField(max_length=20, blank=True, default="9:16")
    is_shared = models.BooleanField(default=False)
    commercial_use = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def get_path(self):
        if self.storage_type == self.STORAGE_UPLOAD and self.file:
            return self.file.path
        return self.local_path

    def __str__(self):
        return self.name


class VideoJob(models.Model):
    # 一次视频生成任务
    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"

    MODE_SCROLLING_TEXT = "scrolling_text"
    MODE_SENTENCE_CARD = "sentence_card"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=100)
    novel_text = models.TextField()
    render_mode = models.CharField(max_length=30, default=MODE_SCROLLING_TEXT)
    style = models.CharField(max_length=50, blank=True, default="")
    target_duration = models.PositiveIntegerField(default=0, blank=True)

    background_asset = models.ForeignKey(
        MaterialAsset, on_delete=models.SET_NULL, null=True, blank=True, related_name="background_jobs"
    )
    bgm_asset = models.ForeignKey(
        MaterialAsset, on_delete=models.SET_NULL, null=True, blank=True, related_name="bgm_jobs"
    )
    opening_audio_asset = models.ForeignKey(
        MaterialAsset, on_delete=models.SET_NULL, null=True, blank=True, related_name="opening_audio_jobs"
    )

    opening_text = models.TextField(blank=True, default="")
    opening_duration = models.PositiveIntegerField(default=3)

    font_name = models.CharField(max_length=100, blank=True, default="")
    font_size = models.PositiveIntegerField(default=48)
    font_color = models.CharField(max_length=20, default="#ffffff")

    scrolling_start_y = models.IntegerField(default=1600)
    scrolling_end_y = models.IntegerField(default=-1600)
    scrolling_speed = models.FloatField(default=1.0)
    sentence_position = models.CharField(max_length=50, default="center")

    bgm_loop = models.BooleanField(default=True)
    bgm_volume = models.FloatField(default=0.35)

    split_punctuation = models.JSONField(default=list, blank=True)
    text_rules = models.JSONField(default=dict, blank=True)
    name_replacements = models.JSONField(default=list, blank=True)

    status = models.CharField(max_length=20, default=STATUS_PENDING, db_index=True)
    task_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    trace_id = models.CharField(max_length=64, blank=True, default="", db_index=True)

    script = models.JSONField(default=dict, blank=True)
    output_dir = models.CharField(max_length=500, blank=True, default="")
    final_path = models.CharField(max_length=500, blank=True, default="")
    cover_path = models.CharField(max_length=500, blank=True, default="")
    subtitle_path = models.CharField(max_length=500, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    duration = models.FloatField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
