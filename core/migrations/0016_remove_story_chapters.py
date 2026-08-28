"""Число частей перестаёт храниться (PLAN-OPTIMIZATION, шаг 1.2).

Считается по записям глав: аннотацией `chapter_count` в выдаче и
`chapter_set.count()` у одиночного объекта. Данные не переносятся —
колонка расходилась с текстом, и переносить разошедшееся некуда.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_user_profile_fields'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='story',
            name='chapters',
        ),
    ]
