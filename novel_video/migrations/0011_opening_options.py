from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("novel_video", "0010_videojob_text_start_time"),
    ]

    operations = [
        migrations.AddField(
            model_name="videojob",
            name="opening_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="videojob",
            name="opening_audio_mode",
            field=models.CharField(default="uploaded", max_length=20),
        ),
        migrations.AddField(
            model_name="videojob",
            name="opening_lines",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
