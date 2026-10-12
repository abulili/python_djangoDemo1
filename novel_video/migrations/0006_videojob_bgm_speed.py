from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("novel_video", "0005_videojob_tts"),
    ]

    operations = [
        migrations.AddField(
            model_name="videojob",
            name="bgm_speed",
            field=models.FloatField(default=1.0),
        ),
    ]
