from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("novel_video", "0004_alter_materialasset_duration"),
    ]

    operations = [
        migrations.AddField(
            model_name="videojob",
            name="tts_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="videojob",
            name="tts_voice",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="videojob",
            name="tts_rate",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.AddField(
            model_name="videojob",
            name="tts_volume",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
    ]
