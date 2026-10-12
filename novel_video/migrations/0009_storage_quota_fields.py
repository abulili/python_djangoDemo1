from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("novel_video", "0008_videojob_process_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="materialasset",
            name="file_size",
            field=models.PositiveBigIntegerField(blank=True, default=0),
        ),
        migrations.AddField(
            model_name="videojob",
            name="output_size",
            field=models.PositiveBigIntegerField(blank=True, default=0),
        ),
    ]
