"""Индексы под запросы, которые страницы делают на самом деле.

Ни один из шести не про схему — все шесть про то, как в таблицу ходят.
Обоснование каждого стоит рядом с `Meta.indexes` в `core/models.py`.
Данных миграция не трогает.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_media_uploads'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='libraryentry',
            index=models.Index(fields=['user', 'kind'], name='core_librar_user_id_326c26_idx'),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['user', '-created_at'], name='core_notifi_user_id_1cc5b6_idx'),
        ),
        migrations.AddIndex(
            model_name='story',
            index=models.Index(fields=['-views'], name='core_story_views_eaacf4_idx'),
        ),
        migrations.AddIndex(
            model_name='story',
            index=models.Index(fields=['-created_at'], name='core_story_created_f3a776_idx'),
        ),
        migrations.AddIndex(
            model_name='tag',
            index=models.Index(fields=['status', '-usage_count'], name='core_tag_status_f71c54_idx'),
        ),
        migrations.AddIndex(
            model_name='tag',
            index=models.Index(fields=['status', '-weekly_count'], name='core_tag_status_617cf5_idx'),
        ),
    ]
