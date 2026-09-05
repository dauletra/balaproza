"""Перенос существующих глав в модель ревизий (BR-79, DEC-69).

До этой миграции глава была одной строкой: то, что пишет автор, и то, что
читает читатель. После — у неё есть рабочая копия и отдельная одобренная
ревизия. Значит каждой уже написанной главе нужно выдать её историю, и
выдать так, чтобы **портал не изменился на глазах у читателя**.

Правило переноса одно: что было видно — остаётся видным.

  - глава публичной работы получает `approved`-ревизию и становится
    опубликованной: читатель видел её вчера, увидит и завтра;
  - глава работы, стоящей на модерации, получает `pending`: она и была на
    проверке, очередь модератора не должна опустеть от миграции;
  - глава черновика не получает ничего — её и не видел никто.

`completed_by_author` восстанавливается из статуса: `Completed` — это
единственное, что в старой колонке было словом автора, а не исходом
модерации, и терять его нельзя.
"""

from django.db import migrations
from django.utils import timezone

from core.domain.catalog import PUBLIC_STATUSES


def publish_existing(apps, schema_editor):
    Chapter = apps.get_model('core', 'Chapter')
    ChapterRevision = apps.get_model('core', 'ChapterRevision')
    Story = apps.get_model('core', 'Story')

    Story.objects.filter(status='Completed').update(completed_by_author=True)

    now = timezone.now()
    for chapter in Chapter.objects.select_related('story').iterator():
        status = chapter.story.status
        if status in PUBLIC_STATUSES:
            state = 'approved'
        elif status == 'OnModeration':
            state = 'pending'
        else:
            continue

        revision = ChapterRevision.objects.create(
            chapter=chapter, title=chapter.title, body=chapter.body,
            char_count=len(chapter.body), state=state,
            submitted_at=now, decided_at=now if state == 'approved' else None,
        )
        if state == 'approved':
            chapter.published_revision = revision
            chapter.save(update_fields=['published_revision'])


def unpublish(apps, schema_editor):
    """Назад — снять ссылки и убрать ревизии. Текст при этом не теряется:
    рабочая копия главы всё это время лежала в `Chapter.body`."""
    Chapter = apps.get_model('core', 'Chapter')
    ChapterRevision = apps.get_model('core', 'ChapterRevision')
    Chapter.objects.update(published_revision=None)
    ChapterRevision.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [('core', '0004_chapter_revisions')]

    operations = [migrations.RunPython(publish_existing, unpublish)]
