"""Следы чтения: оқылым, закладка, полка.

Всё три пишутся самим чтением, а не кнопкой. Оқылым считается раз на
работу за сессию — иначе перезагрузка накручивала бы счётчик; окно
«Қазір танымал» живёт журналом прочтений и убывает вместе с ним.

Закладка помнит, докуда дочитано, и она же переносит работу с полки
«оқығым келеді» на «оқып жатырмын»: просить об этом читателя отдельно
значит просить дважды об одном.
"""


from datetime import timedelta

from core.tests.base import STORY_SLUG, TestCase, login_as, login_as_newcomer
from django.test import Client
from django.urls import reverse

from core import data
from core.domain.story import RECENT_VIEWS_DAYS
from core.models import LibraryEntry, ReadingProgress, Story, StoryView
from django.db.models import F
from django.utils import timezone


class ReadingMovesTheWorkBetweenShelves(TestCase):
    """Автопереходы полки (BR-61, FR-LIB-02).

    Вкладка «Оқу үстіндегі» наполнялась одним сидом: у настоящего читателя
    она оставалась пустой, сколько бы он ни читал.
    """

    SLUG = STORY_SLUG
    READER = 'lonely_reader'

    def setUp(self):
        login_as_newcomer(self.client, self.READER)
        self.last = len(data.chapters_of(self.SLUG))

    def _open(self, chapter):
        self.client.get(reverse('core:story_detail',
                                kwargs={'slug': self.SLUG}) + f'?chapter={chapter}')

    def _kind(self):
        entry = LibraryEntry.objects.filter(user__username=self.READER,
                                            story__slug=self.SLUG).first()
        return entry.kind if entry else None

    def test_reading_moves_the_work_from_shelf_to_shelf(self):
        """Строка `done` предлагает «Қайта оқу», и после нажатия полка
        обязана описывать то, что происходит."""
        self.assertIsNone(self._kind())
        self._open(2)
        self.assertEqual(self._kind(), 'reading')
        self._open(self.last)
        self.assertEqual(self._kind(), 'done')
        self._open(1)
        self.assertEqual(self._kind(), 'reading')

    def test_reading_never_leaves_two_entries(self):
        for chapter in (1, 3, self.last, 2):
            self._open(chapter)
        self.assertEqual(
            LibraryEntry.objects.filter(user__username=self.READER,
                                        story__slug=self.SLUG).count(), 1)

    def test_a_guest_leaves_no_trace(self):
        self.client.logout()
        before = LibraryEntry.objects.count()
        self._open(3)
        self.assertEqual(LibraryEntry.objects.count(), before)


class ReadingCountsAsAView(TestCase):
    """Оқылым засчитывается при открытии работы (FR-STORY-01, DEC-36).

    До этого счётчик в базу клал только сид: `views` и `recent_views` не
    росли ни от одного захода. То есть «Қазір танымал» — дефолтная
    сортировка каталога — навсегда показывала порядок демо-данных, а
    автору портал сообщал число, к которому его читатели не имели
    отношения.
    """

    SLUG = STORY_SLUG

    def _url(self, **params):
        url = reverse('core:story_detail', kwargs={'slug': self.SLUG})
        return url + ('?' + '&'.join(f'{k}={v}' for k, v in params.items())
                      if params else '')

    def _counters(self):
        s = Story.objects.get(slug=self.SLUG)
        return s.views, s.recent_views

    def test_a_first_visit_moves_both_counters_and_the_page_shows_it(self):
        """Цифра, отставшая на один заход, читается как «меня не засчитали»."""
        views_before, recent_before = self._counters()
        response = self.client.get(self._url())
        views, recent = self._counters()
        self.assertEqual(views, views_before + 1)
        self.assertEqual(recent, recent_before + 1)
        self.assertEqual(response.context['story'].views, views_before + 1)

    def test_one_reader_counts_once_however_much_they_hop(self):
        before = self._counters()[0]
        self.client.get(self._url())
        self.client.get(self._url())
        self.client.get(self._url(chapter=3))
        self.client.get(self._url(chapter=7))
        self.assertEqual(self._counters()[0], before + 1)
        # А другой — считается снова.
        Client().get(self._url())
        self.assertEqual(self._counters()[0], before + 2)

    def test_the_author_does_not_read_themselves_into_the_numbers(self):
        story = Story.objects.get(slug=self.SLUG)
        login_as(self.client, story.author.username)
        before = self._counters()
        self.client.get(self._url())
        self.assertEqual(self._counters(), before)

    def test_reading_passes_neither_for_editing_nor_for_a_story_that_is_gone(self):
        """`updated_at` двигает автор, а не читатель: «өзгертілген бүгін»
        после чужого захода — неправда, и она уезжает в сортировку."""
        before = Story.objects.get(slug=self.SLUG).updated_at
        self.client.get(self._url())
        self.assertEqual(Story.objects.get(slug=self.SLUG).updated_at, before)
        self.assertEqual(
            self.client.get(reverse('core:story_detail',
                                    kwargs={'slug': 'no-such-story'})).status_code,
            404)


class TheRecentWindowActuallyShrinks(TestCase):
    """Окно «Қазір танымал» убывает, потому что убывает журнал (DEC-55).

    До журнала с датами оба счётчика росли вместе и никогда не падали: ось
    DEC-36 обещала две недели, а показывала всё время — то есть со
    временем повторяла «Ең көп оқылған», и главная задавала два вопроса с
    одним ответом.
    """

    SLUG = STORY_SLUG

    def _story(self):
        return Story.objects.get(slug=self.SLUG)

    def test_reading_writes_a_dated_row(self):
        before = StoryView.objects.filter(story__slug=self.SLUG).count()
        self.client.get(reverse('core:story_detail', kwargs={'slug': self.SLUG}))
        self.assertEqual(
            StoryView.objects.filter(story__slug=self.SLUG).count(), before + 1)
        # Гость читает без входа, и это тоже прочтение.
        self.assertIsNone(
            StoryView.objects.filter(story__slug=self.SLUG)
            .order_by('-created_at').first().viewer)

    def test_a_view_that_left_the_window_stops_counting_and_stops_being_stored(self):
        story = self._story()
        old = StoryView.objects.create(story=story)
        StoryView.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=RECENT_VIEWS_DAYS + 1))
        Story.objects.filter(pk=story.pk).update(recent_views=F('recent_views') + 1)

        inside = StoryView.objects.filter(
            story=story,
            created_at__gte=timezone.now() - timedelta(days=RECENT_VIEWS_DAYS)).count()
        data.recount_recent_views()

        self.assertEqual(self._story().recent_views, inside)
        self.assertFalse(StoryView.objects.filter(pk=old.pk).exists())
        # Накопленный счёт журналом не пересчитывается: за окном он пуст.
        self.assertGreater(self._story().views, self._story().recent_views)

    def test_a_work_nobody_reads_falls_to_zero_rather_than_keeping_its_number(self):
        quiet = Story.objects.exclude(slug=self.SLUG).first()
        StoryView.objects.filter(story=quiet).update(
            created_at=timezone.now() - timedelta(days=RECENT_VIEWS_DAYS + 1))
        data.recount_recent_views()
        self.assertEqual(Story.objects.get(pk=quiet.pk).recent_views, 0)

    def test_the_recount_is_idempotent(self):
        data.recount_recent_views()
        first = {s.pk: s.recent_views for s in Story.objects.all()}
        data.recount_recent_views()
        self.assertEqual({s.pk: s.recent_views for s in Story.objects.all()}, first)


class ReadingRemembersWhereYouStopped(TestCase):
    """Закладка двигается по мере чтения (FR-HOME-02).

    `ReadingProgress` до этого создавал только сид: «Оқуды жалғастыру» на
    главной всегда указывало в одно и то же место, сколько бы читатель ни
    читал. Закладка — вещь личная, поэтому у гостя её нет вовсе.
    """

    SLUG = STORY_SLUG
    READER = 'lonely_reader'

    def setUp(self):
        login_as_newcomer(self.client, self.READER)

    def _url(self, chapter=None):
        url = reverse('core:story_detail', kwargs={'slug': self.SLUG})
        return f'{url}?chapter={chapter}' if chapter else url

    def _progress(self):
        return ReadingProgress.objects.filter(
            user__username=self.READER, story__slug=self.SLUG).first()

    def test_the_bookmark_appears_moves_and_does_not_multiply(self):
        self.assertIsNone(self._progress())
        self.client.get(self._url(5))
        progress = self._progress()
        self.assertEqual(progress.current_chapter, 5)
        self.assertEqual(progress.last_read_on, timezone.localdate())
        for chapter in (2, 9):
            self.client.get(self._url(chapter))
        self.assertEqual(self._progress().current_chapter, 9)
        self.assertEqual(
            ReadingProgress.objects.filter(user__username=self.READER).count(), 1)

    def test_time_left_counts_the_chapters_still_ahead(self):
        chapters = data.chapters_of(self.SLUG)
        self.client.get(self._url(3))
        expected = sum(c.char_count for c in chapters if c.number > 3)
        self.assertEqual(self._progress().minutes_left, -(-expected // 900))
        self.client.get(self._url(len(chapters)))
        self.assertEqual(self._progress().minutes_left, 0)

    def test_the_first_visit_is_not_a_return_but_the_next_one_is(self):
        """Закладка пишется после резолва главы, а не до него: иначе первое
        знакомство с работой выглядело бы возвращением к ней, и заход не
        засчитался бы `is_first_look` ни разу (DEC-59)."""
        first = self.client.get(self._url())
        self.assertTrue(first.context['is_first_look'])
        self.assertFalse(first.context['has_progress'])

        self.client.get(self._url(6))
        back = self.client.get(self._url())
        self.assertEqual(back.context['chapter_number'], 6)
        self.assertTrue(back.context['has_progress'])

    def test_a_guest_gets_no_bookmark(self):
        self.client.logout()
        self.client.get(self._url(4))
        self.assertFalse(ReadingProgress.objects.filter(story__slug=self.SLUG,
                                                        user__username=self.READER).exists())
