"""Номер главы у полки перестаёт храниться (PLAN-OPTIMIZATION, шаг 1.6).

`LibraryEntry.progress_chapter` и `ReadingProgress.current_chapter` — один
и тот же факт в двух колонках, и в корпусе они уже разошлись. Данные не
переносятся: полке номер приезжает аннотацией `progress_chapter`.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_remove_story_chapters'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='libraryentry',
            name='progress_chapter',
        ),
    ]
