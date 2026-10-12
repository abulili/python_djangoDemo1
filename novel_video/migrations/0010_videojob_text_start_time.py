from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("novel_video", "0009_storage_quota_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="videojob",
            name="text_start_time",
            field=models.FloatField(blank=True, default=0),
        ),
    ]
