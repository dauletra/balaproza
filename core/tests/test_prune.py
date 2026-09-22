"""Уборка того, что копится молча: уведомления и снимки текста глав.

Обе таблицы растут линейно с возрастом портала и не показываются нигде,
где рост было бы видно, — поэтому проверяется не только «удалилось», но
и «не удалилось то, чего трогать нельзя». Вторая половина здесь важнее:
опубликованная ревизия связана с главой через `SET_NULL`, и удалить её
значит снять текст с публикации.
"""

from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone

from core import data
from core.models import Chapter, ChapterRevision, Notification
from core.queries.notifications import KEEP_DAYS
from core.queries.write import KEEP_REVISION_DAYS
from core.tests import factories as make
from core.tests.base import TestCase


def _age(queryset, days):
    """Состарить строки: у обеих таблиц дата ставится `auto_now_add`/
    умолчанием, и подделать её можно только `update()`."""
    queryset.update(created_at=timezone.now() - timedelta(days=days))


class OldNotificationsGoAway(TestCase):

    def setUp(self):
        super().setUp()
        self.author = make.user()
        self.story = make.story(author=self.author, chapters=1)

    def _notify(self, days_ago):
        note = Notification.objects.create(
            user=self.author, kind='moderation', story=self.story,
            outcome='approved')
        _age(Notification.objects.filter(pk=note.pk), days_ago)
        return note

    def test_a_month_old_event_is_removed(self):
        old = self._notify(KEEP_DAYS + 1)

        data.prune_notifications()

        self.assertFalse(Notification.objects.filter(pk=old.pk).exists())

    def test_a_fresh_one_stays(self):
        fresh = self._notify(1)

        data.prune_notifications()

        self.assertTrue(Notification.objects.filter(pk=fresh.pk).exists())

    def test_the_edge_belongs_to_the_survivors(self):
        """Ровно `KEEP_DAYS` — ещё живое: граница называется «старше», и
        читаться она должна строго."""
        edge = self._notify(KEEP_DAYS - 1)

        data.prune_notifications()

        self.assertTrue(Notification.objects.filter(pk=edge.pk).exists())


class OldRevisionsGoAwayButNotTheOnesInUse(TestCase):

    def setUp(self):
        super().setUp()
        self.author = make.user()
        self.story = make.story(author=self.author, chapters=1)
        self.chapter = self.story.chapter_set.first()

    def _revision(self, state, days_ago):
        revision = ChapterRevision.objects.create(
            chapter=self.chapter, title='Атау', body='Мәтін', state=state)
        _age(ChapterRevision.objects.filter(pk=revision.pk), days_ago)
        return revision

    def test_an_old_closed_snapshot_is_removed(self):
        old = self._revision('rejected', KEEP_REVISION_DAYS + 1)

        data.prune_revisions()

        self.assertFalse(ChapterRevision.objects.filter(pk=old.pk).exists())

    def test_a_pending_one_stays_however_long_it_waits(self):
        """Очередь бывает длинной, и уборка не решает за модератора."""
        waiting = self._revision('pending', KEEP_REVISION_DAYS * 10)

        data.prune_revisions()

        self.assertTrue(ChapterRevision.objects.filter(pk=waiting.pk).exists())

    def test_the_published_one_stays_and_the_chapter_keeps_its_text(self):
        """Связь `SET_NULL`: удалить опубликованную ревизию значит
        обнулить поле у главы, то есть снять текст с публикации. Читатель
        потерял бы главу, а автор не понял бы почему."""
        published = self._revision('approved', KEEP_REVISION_DAYS + 5)
        Chapter.objects.filter(pk=self.chapter.pk).update(
            published_revision=published)

        data.prune_revisions()

        self.chapter.refresh_from_db()
        self.assertEqual(self.chapter.published_revision_id, published.pk)
        self.assertTrue(self.chapter.is_published)

    def test_a_fresh_snapshot_stays(self):
        fresh = self._revision('draft', 1)

        data.prune_revisions()

        self.assertTrue(ChapterRevision.objects.filter(pk=fresh.pk).exists())

    def test_a_superseded_approved_snapshot_is_removed(self):
        """Одобренная, но уже не опубликованная — история: её сменила
        следующая одобренная, и держать её месяцами незачем."""
        superseded = self._revision('approved', KEEP_REVISION_DAYS + 1)
        current = self._revision('approved', 1)
        Chapter.objects.filter(pk=self.chapter.pk).update(
            published_revision=current)

        data.prune_revisions()

        self.assertFalse(ChapterRevision.objects.filter(pk=superseded.pk).exists())
        self.assertTrue(ChapterRevision.objects.filter(pk=current.pk).exists())


class TheCommandDoesBothAndSaysSo(TestCase):

    def test_it_runs_and_is_idempotent(self):
        call_command('prune_old_rows', '--quiet')
        call_command('prune_old_rows', '--quiet')
