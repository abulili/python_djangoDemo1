from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("novel_video", "0007_videojob_font_stroke"),
    ]

    operations = [
        migrations.AddField(
            model_name="videojob",
            name="process_mode",
            field=models.CharField(db_index=True, default="server", max_length=20),
        ),
    ]
