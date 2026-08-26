"""Индексы под запросы, которые страницы делают на самом деле.

Ни один из шести не про схему — все шесть про то, как в таблицу ходят.
Обоснование каждого стоит рядом с `Meta.indexes` в `core/models.py`, а
короче всего так:

- `library(user, kind)` — «полка такого-то читателя», единственный способ
  обращения к таблице;
- `notification(user, -created_at)` — лента за неделю и бейдж в шапке;
  бейдж считается на **каждой** странице у каждого вошедшего;
- `story(-views)` и `story(-created_at)` — оси сортировки каталога «Ең
  көп оқылған» и «Жаңалары»; у третьей (`-recent_views`, дефолт) индекс
  был с самого начала;
- `tag(status, -usage_count)` и `tag(status, -weekly_count)` — две
  витрины тегов. Их две потому, что они отвечают на разные вопросы
  (DEC-31), и по одному индексу на вопрос.

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
