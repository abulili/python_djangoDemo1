from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("novel_video", "0006_videojob_bgm_speed"),
    ]

    operations = [
        migrations.AddField(
            model_name="videojob",
            name="font_stroke_width",
            field=models.PositiveIntegerField(default=2),
        ),
        migrations.AddField(
            model_name="videojob",
            name="font_stroke_color",
            field=models.CharField(default="#000000", max_length=20),
        ),
    ]
