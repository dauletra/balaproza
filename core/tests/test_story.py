"""STORY-модуль: detail и reading.

Покрываем:
 - валидный/невалидный slug;
 - наличие 3 scrollspy-якорей и pill-навигации;
 - список глав со ссылками на конкретные главы;
 - gate для комментариев у гостя, форма для авторизованного;
 - ReportModal-триггер только для авторизованного;
 - прогресс чтения отображается только если slug совпадает с SAMPLE_PROGRESS;
 - reading: prev/next ссылки только если есть соседние главы;
 - reading: попавер настроек и текст главы.
"""

from django.test import TestCase
from django.urls import reverse

from core import stub_data


STORY_SLUG = 'dalney-berega'   # есть в STORIES_BY_SLUG и в CHAPTERS_BY_STORY


def _login(client):
    s = client.session
    s['signed_in'] = True
    s['user_name'] = 'Айдана'
    s['user_username'] = 'aidana'
    s.save()


class StoryDetailUnknownSlug(TestCase):
    """Неизвестный slug → 200 + сообщение «Шығарма табылмады»."""

    def test_unknown_slug_renders_not_found_message(self):
        response = self.client.get(reverse('core:story_detail', kwargs={'slug': 'no-such-story'}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Шығарма табылмады')
        # И никаких scrollspy-якорей в этой ветке
        self.assertNotContains(response, 'id="anon"')


class StoryDetailValidSlug(TestCase):

    def setUp(self):
        self.url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG})
        self.response = self.client.get(self.url)

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_title_includes_story_and_author(self):
        story = stub_data.STORIES_BY_SLUG[STORY_SLUG]
        self.assertContains(self.response, story.title)
        self.assertContains(self.response, story.author.name)

    def test_has_scrollspy_anchors(self):
        for anchor_id in ('anon', 'chapters', 'comments'):
            with self.subTest(anchor=anchor_id):
                self.assertContains(self.response, f'id="{anchor_id}"')

    def test_pill_nav_links_to_each_section(self):
        """Pills — реальные href-якоря (для no-JS клиентов тоже работает)."""
        for href in ('#anon', '#chapters', '#comments'):
            with self.subTest(href=href):
                self.assertContains(self.response, f'href="{href}"')

    def test_chapter_list_links_to_each_chapter(self):
        for c in stub_data.chapters_of(STORY_SLUG):
            with self.subTest(chapter=c.number):
                url = reverse('core:story_read_chapter', kwargs={'slug': STORY_SLUG, 'chapter': c.number})
                self.assertContains(self.response, f'href="{url}"')

    def test_genres_chips_rendered(self):
        story = stub_data.STORIES_BY_SLUG[STORY_SLUG]
        for g in story.genres_resolved:
            with self.subTest(genre=g.slug):
                self.assertContains(self.response, g.name)


class StoryDetailGuestVsAuth(TestCase):

    def test_guest_sees_gate_no_input(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'Пікір қалдыру үшін')
        self.assertNotContains(r, '<textarea')

    def test_authed_sees_input_no_gate(self):
        _login(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertNotContains(r, 'Пікір қалдыру үшін')
        self.assertContains(r, '<textarea')

    def test_report_trigger_only_for_authed(self):
        r_guest = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertNotContains(r_guest, "open-report")

        _login(self.client)
        r_auth = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r_auth, "open-report")


class StoryDetailReadingProgress(TestCase):
    """Прогресс «Оқылды N/M» только если slug совпадает с SAMPLE_PROGRESS.story_slug."""

    def test_authed_with_matching_progress_shows_indicator(self):
        # SAMPLE_PROGRESS привязан к 'dalney-berega'
        self.assertEqual(stub_data.SAMPLE_PROGRESS.story_slug, STORY_SLUG)
        _login(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'Оқылды:')

    def test_authed_other_story_no_progress_indicator(self):
        _login(self.client)
        # Другой slug — даже если у пользователя есть прогресс на dalney-berega,
        # на других страницах он не должен подсвечиваться.
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': 'arhimag'}))
        self.assertNotContains(r, 'Оқылды:')

    def test_guest_no_progress_indicator(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertNotContains(r, 'Оқылды:')


class StoryReadKnownChapter(TestCase):

    def setUp(self):
        self.url = reverse('core:story_read_chapter', kwargs={'slug': STORY_SLUG, 'chapter': 4})
        self.response = self.client.get(self.url)

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_renders_chapter_title_and_some_body(self):
        chapter = stub_data.chapter_of(STORY_SLUG, 4)
        self.assertContains(self.response, chapter.title)
        # тело главы — длинный текст, проверим первое предложение
        self.assertContains(self.response, 'Бірде ерте таңда')

    def test_has_back_to_story_link(self):
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG})
        self.assertContains(self.response, f'href="{url}"')

    def test_has_prev_and_next_links_for_middle_chapter(self):
        prev_url = reverse('core:story_read_chapter', kwargs={'slug': STORY_SLUG, 'chapter': 3})
        next_url = reverse('core:story_read_chapter', kwargs={'slug': STORY_SLUG, 'chapter': 5})
        self.assertContains(self.response, f'href="{prev_url}"')
        self.assertContains(self.response, f'href="{next_url}"')


class StoryReadEdgeChapters(TestCase):

    def test_first_chapter_has_no_prev_link(self):
        r = self.client.get(reverse('core:story_read_chapter', kwargs={'slug': STORY_SLUG, 'chapter': 1}))
        # «Алдыңғы бөлім» не должно быть
        self.assertNotContains(r, 'Алдыңғы бөлім')
        # Зато «Келесі бөлім» есть
        self.assertContains(r, 'Келесі бөлім')

    def test_last_chapter_has_no_next_link(self):
        last = len(stub_data.chapters_of(STORY_SLUG))
        r = self.client.get(reverse('core:story_read_chapter', kwargs={'slug': STORY_SLUG, 'chapter': last}))
        self.assertContains(r, 'Алдыңғы бөлім')
        self.assertNotContains(r, 'Келесі бөлім')


class StoryReadUnknownChapter(TestCase):

    def test_chapter_out_of_range_renders_not_found(self):
        r = self.client.get(reverse('core:story_read_chapter', kwargs={'slug': STORY_SLUG, 'chapter': 999}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Бөлім табылмады')


class StoryReadHasSettingsPopover(TestCase):

    def test_popover_listens_for_reader_settings_event(self):
        r = self.client.get(reverse('core:story_read', kwargs={'slug': STORY_SLUG}))
        # Wrapper читалки реагирует на событие reader-settings
        self.assertContains(r, 'reader-settings')
        # Popover содержит триггерную aria
        self.assertContains(r, 'Оқу баптаулары')
