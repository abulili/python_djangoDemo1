from django.db import migrations


def rename_old_trace_table(apps, schema_editor):
    tables = schema_editor.connection.introspection.table_names()

    old_table = "ai_log_ragtracelog"
    new_table = "ai_log_aitracesteplog"

    if old_table in tables and new_table not in tables:
        schema_editor.execute(f"RENAME TABLE {old_table} TO {new_table}")


def reverse_rename_old_trace_table(apps, schema_editor):
    tables = schema_editor.connection.introspection.table_names()

    old_table = "ai_log_ragtracelog"
    new_table = "ai_log_aitracesteplog"

    if new_table in tables and old_table not in tables:
        schema_editor.execute(f"RENAME TABLE {new_table} TO {old_table}")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("ai_log", "0012_alter_aitracesteplog_options"),
    ]

    operations = [
        migrations.RunPython(
            rename_old_trace_table,
            reverse_rename_old_trace_table,
        ),
    ]