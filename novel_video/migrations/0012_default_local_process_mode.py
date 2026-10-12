# Generated manually to make local generation the safe default.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("novel_video", "0011_opening_options"),
    ]

    operations = [
        migrations.AlterField(
            model_name="videojob",
            name="process_mode",
            field=models.CharField(db_index=True, default="local", max_length=20),
        ),
    ]
