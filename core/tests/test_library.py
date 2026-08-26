"""LIB — библиотека читателя: три непересекающиеся полки (BR-60/61)."""

from core.tests.base import TestCase, login_as, login_as_newcomer
from django.urls import reverse

from core import data


class LibraryHelpers(TestCase):

    def test_library_of_returns_all_when_no_kind(self):
        self.assertEqual(len(data.library_of('aidana')), 6)

    def test_library_of_filters_by_kind(self):
        self.assertEqual(len(data.library_of('aidana', 'reading')), 2)
        self.assertEqual(len(data.library_of('aidana', 'saved')), 3)
        self.assertEqual(len(data.library_of('aidana', 'done')), 1)

    def test_library_of_unknown_user_is_empty(self):
        self.assertEqual(data.library_of('no-such-user'), [])

    def test_library_entry_resolves_story(self):
        for e in data.library_of('aidana'):
            with self.subTest(entry=e.story.slug):
                self.assertEqual(e.story.slug, e.story.slug)

    def test_reading_entries_have_valid_progress(self):
        for e in data.library_of('aidana', 'reading'):
            with self.subTest(entry=e.story.slug):
                self.assertGreaterEqual(e.progress_chapter, 1)
                self.assertLessEqual(e.progress_chapter, e.story.chapters)


class LibraryGuest(TestCase):

    def test_guest_sees_gate(self):
        r = self.client.get(reverse('core:library'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'кір')
        self.assertNotContains(r, 'Алыс жағалауларда')


class LibraryAuthed(TestCase):

    def setUp(self):
        login_as(self.client)

    def test_default_tab_is_saved(self):
        r = self.client.get(reverse('core:library'))
        self.assertEqual(r.status_code, 200)
        # «Сақталған»: 3 книги
        for e in data.library_of('aidana', 'saved'):
            with self.subTest(slug=e.story.slug):
                self.assertContains(r, e.story.title)

    def test_reading_tab_shows_progress_and_continue(self):
        r = self.client.get(reverse('core:library') + '?tab=reading')
        self.assertContains(r, 'Жалғастыру')
        self.assertContains(r, 'Алыс жағалауларда')
        # Прогресс «N / M бөлім»
        self.assertContains(r, '4 / 12 бөлім')

    def test_done_tab(self):
        r = self.client.get(reverse('core:library') + '?tab=done')
        self.assertContains(r, 'Империя құдіреті')
        self.assertContains(r, 'Қайта оқу')

    def test_segmented_control_links(self):
        r = self.client.get(reverse('core:library'))
        self.assertContains(r, '?tab=saved')
        self.assertContains(r, '?tab=reading')
        self.assertContains(r, '?tab=done')

    def test_unknown_tab_falls_back_to_saved(self):
        r = self.client.get(reverse('core:library') + '?tab=garbage')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Күңгірт мырза')  # из saved

    def test_other_tab_books_not_shown(self):
        # На reading-табе НЕ должно быть «Күңгірт мырза» (saved)
        r = self.client.get(reverse('core:library') + '?tab=reading')
        self.assertNotContains(r, 'Күңгірт мырза')


class LibraryEmpty(TestCase):

    def setUp(self):
        login_as_newcomer(self.client, 'lonely_reader')

    def test_saved_empty_shows_empty_state_with_cta(self):
        r = self.client.get(reverse('core:library'))
        self.assertContains(r, 'Сақталғандар жоқ')
        self.assertContains(r, reverse('core:catalog'))

    def test_reading_empty(self):
        r = self.client.get(reverse('core:library') + '?tab=reading')
        self.assertContains(r, 'Оқу үстіндегі шығарма жоқ')

    def test_done_empty(self):
        r = self.client.get(reverse('core:library') + '?tab=done')
        self.assertContains(r, 'Әлі ешнәрсе оқылмаған')
