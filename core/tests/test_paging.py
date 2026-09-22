"""Ни один список не растёт вместе с базой.

Окно было у каталога и у разговора под главой; остальные шесть списков
отдавались целиком. Опасность у них разная, и в этом весь смысл проверки:
библиотеку и свои работы человек наполняет сам и видит, как список
удлиняется, — а подписчиков ему приводят, и очередь модерации тяжелеет
ровно в тот день, когда с ней не справляются, то есть страница становится
медленной тогда, когда она нужнее всего.

Проверяется одно и то же у всех шести: показано ровно окно, а не всё, и
переход на следующую страницу нарисован. Число в заголовке при этом — про
весь список: «20» над первой страницей из трёх было бы неправдой.
"""

from django.urls import reverse

from core import data
from core.models import (
    BlockedTagPattern,
    ChapterRevision,
    Follow,
    LibraryEntry,
    Report,
)
from core.tests import factories as make
from core.tests.base import TestCase, login_as_newcomer
from core.views.common import LIST_PAGE

#: На одну больше окна — минимум, при котором вторая страница обязана быть.
OVER = LIST_PAGE + 1


def _moderator(client, username='paging_mod'):
    user = make.user(username=username)
    user.is_staff = True
    user.save(update_fields=['is_staff'])
    client.force_login(user)
    return user


class TheListsComeInWindows(TestCase):

    def _shows_a_window(self, response, rows, *, expected=LIST_PAGE):
        self.assertEqual(len(rows), expected)
        self.assertContains(response, 'aria-label="Беттер"')

    # ── Подписчики: список растит не тот, кто на него смотрит ────────────
    def test_followers(self):
        author = make.user(username='paging_star')
        for _ in range(OVER):
            Follow.objects.create(follower=make.user(), following=author)

        response = self.client.get(reverse(
            'core:profile_people',
            kwargs={'username': author.username, 'kind': 'followers'}))

        self._shows_a_window(response, response.context['people'])

    def test_the_segment_still_counts_the_whole_list(self):
        """Число над списком — про всех подписчиков, а не про эту
        страницу."""
        author = make.user(username='paging_star_2')
        for _ in range(OVER):
            Follow.objects.create(follower=make.user(), following=author)

        response = self.client.get(reverse(
            'core:profile_people',
            kwargs={'username': author.username, 'kind': 'followers'}))

        opened = next(i for i in response.context['people_items']
                      if i['slug'] == 'followers')
        self.assertEqual(opened['count'], OVER)

    # ── Очередь модерации: тяжелеет тогда, когда с ней не справляются ────
    def test_the_moderation_queue(self):
        _moderator(self.client)
        before = data.queue_size()
        for _ in range(OVER):
            story = make.story(author=make.user(), chapters=1, published=False,
                               status='NotPublished')
            ChapterRevision.objects.create(
                chapter=story.chapter_set.first(), title='Атау', body='Мәтін',
                state='pending')

        response = self.client.get(reverse('core:moderation_queue'))

        self._shows_a_window(response, response.context['stories'])
        self.assertEqual(response.context['total'], before + OVER)

    def test_the_queue_keeps_the_axis_on_the_second_page(self):
        """Без оси в адресе вторая страница «Ұзақ күтуде» открывала бы
        вторую страницу всей очереди."""
        _moderator(self.client, 'paging_mod_axis')

        response = self.client.get(reverse('core:moderation_queue') + '?kind=first')

        self.assertEqual(response.context['page_qs'], 'kind=first')

    # ── Жалобы и задержанные пікірлер ───────────────────────────────────
    def test_open_reports(self):
        _moderator(self.client, 'paging_mod_reports')
        story = make.story(author=make.user(), chapters=1)
        for _ in range(OVER):
            Report.objects.create(reporter=make.user(), story=story,
                                  reason='spam')

        response = self.client.get(reverse('core:moderation_reports'))

        self._shows_a_window(response, response.context['reports'])

    def test_held_comments(self):
        _moderator(self.client, 'paging_mod_held')
        BlockedTagPattern.objects.get_or_create(
            pattern='кезек-стоп', defaults={'scope': 'comment'})
        story = make.story(author=make.user(), chapters=1)
        for _ in range(OVER):
            data.add_comment(story, make.user(), text='кезек-стоп деген сөз',
                             chapter_number=1)

        response = self.client.get(reverse('core:moderation_comments'))

        self._shows_a_window(response, response.context['comments'])

    # ── Библиотека и свои работы: копятся годами ─────────────────────────
    def test_the_library_shelf(self):
        reader = login_as_newcomer(self.client, 'paging_reader')
        for _ in range(OVER):
            LibraryEntry.objects.create(
                user=reader, story=make.story(author=make.user(), chapters=1),
                kind='saved')

        response = self.client.get(reverse('core:library') + '?tab=saved')

        self._shows_a_window(response, response.context['entries'])
        opened = next(i for i in response.context['lib_items']
                      if i['slug'] == 'saved')
        self.assertEqual(opened['count'], OVER)

    def test_the_library_keeps_the_tab_on_the_second_page(self):
        login_as_newcomer(self.client, 'paging_reader_tab')

        response = self.client.get(reverse('core:library') + '?tab=done')

        self.assertEqual(response.context['page_qs'], 'tab=done')

    def test_the_works_on_a_profile(self):
        author = make.user(username='paging_author')
        for _ in range(OVER):
            make.story(author=author, chapters=1)

        response = self.client.get(reverse('core:profile_other',
                                           kwargs={'username': author.username}))

        self._shows_a_window(response, response.context['works'])

    def test_a_short_list_gets_no_pagination(self):
        """Одна страница — навигации нет вовсе: «‹ 1 ›» это украшение,
        которое нечего листать."""
        author = make.user(username='paging_quiet')
        Follow.objects.create(follower=make.user(), following=author)

        response = self.client.get(reverse(
            'core:profile_people',
            kwargs={'username': author.username, 'kind': 'followers'}))

        self.assertNotContains(response, 'aria-label="Беттер"')


class GarbageInThePageNumberOpensThePage(TestCase):
    """Старая ссылка и опечатка не должны закрывать раздел — то же, что
    делает каталог: не-число читается первой страницей, слишком большое —
    последней."""

    def setUp(self):
        super().setUp()
        self.author = make.user(username='paging_sturdy')
        Follow.objects.create(follower=make.user(), following=self.author)
        self.url = reverse('core:profile_people',
                           kwargs={'username': self.author.username,
                                   'kind': 'followers'})

    def test_nonsense(self):
        self.assertEqual(self.client.get(f'{self.url}?page=garbage').status_code, 200)

    def test_out_of_range(self):
        self.assertEqual(self.client.get(f'{self.url}?page=999').status_code, 200)

    def test_negative(self):
        self.assertEqual(self.client.get(f'{self.url}?page=-3').status_code, 200)
