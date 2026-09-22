"""LIB — полки читателя.

Работа лежит ровно на одной полке: «оқып жатырмын» и «оқығым келеді»
взаимно исключают друг друга, и переносит её между ними само чтение, а
не кнопка.
"""


from django.urls import reverse

from core import data
from core.tests.base import TestCase, login_as, login_as_newcomer, user


def _titles(entries):
    return {e.story.slug: e.story.title for e in entries}


# ───────────────────────────────────────────────────────────────────────
# LIB — библиотека читателя: три непересекающиеся полки (BR-60/61)
# ───────────────────────────────────────────────────────────────────────

class LibraryShelves(TestCase):

    KINDS = ('saved', 'reading', 'done')

    def test_the_shelves_partition_the_library(self):
        everything = data.library_of(user('aidana'))
        by_kind = {k: data.library_of(user('aidana'), k) for k in self.KINDS}
        self.assertEqual(sum(len(v) for v in by_kind.values()), len(everything))
        slugs = [e.story.slug for shelf in by_kind.values() for e in shelf]
        self.assertEqual(len(slugs), len(set(slugs)), 'работа лежит на двух полках')
        self.assertTrue(all(by_kind.values()), 'у aidana пустая полка')
        self.assertEqual(data.library_of(user('no-such-user')), [])
        for entry in by_kind['reading']:
            with self.subTest(entry=entry.story.slug):
                self.assertGreaterEqual(entry.progress_chapter, 1)
                self.assertLessEqual(entry.progress_chapter, entry.story.chapters)

    def test_a_guest_sees_a_gate_instead_of_someone_elses_shelf(self):
        response = self.client.get(reverse('core:library'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'кір')
        for entry in data.library_of(user('aidana')):
            with self.subTest(story=entry.story.slug):
                self.assertNotContains(response, entry.story.title)

    def test_each_tab_shows_its_own_shelf_and_nothing_else(self):
        login_as(self.client)
        everything = _titles(data.library_of(user('aidana')))
        for kind, cta in (('saved', None), ('reading', 'Жалғастыру'),
                          ('done', 'Қайта оқу')):
            shelf = data.library_of(user('aidana'), kind)
            response = self.client.get(reverse('core:library') + f'?tab={kind}')
            with self.subTest(tab=kind):
                self.assertContains(response, f'?tab={kind}')
                if cta:
                    self.assertContains(response, cta)
                mine = {e.story.slug for e in shelf}
                for entry in shelf:
                    self.assertContains(response, entry.story.title)
                for slug, title in everything.items():
                    if slug not in mine:
                        self.assertNotContains(response, title)
        # Прогресс «N / M бөлім» считается, а не хранится (DEC-52).
        reading = self.client.get(reverse('core:library') + '?tab=reading')
        for entry in data.library_of(user('aidana'), 'reading'):
            with self.subTest(story=entry.story.slug):
                self.assertContains(
                    reading,
                    f'{entry.progress_chapter} / {entry.story.chapters} бөлім')

    def test_an_unknown_tab_falls_back_to_saved(self):
        login_as(self.client)
        response = self.client.get(reverse('core:library') + '?tab=garbage')
        self.assertEqual(response.status_code, 200)
        for entry in data.library_of(user('aidana'), 'saved'):
            with self.subTest(story=entry.story.slug):
                self.assertContains(response, entry.story.title)

    def test_every_empty_shelf_explains_itself(self):
        login_as_newcomer(self.client, 'lonely_reader')
        for kind, words in (('saved', 'Сақталғандар жоқ'),
                            ('reading', 'Оқу үстіндегі шығарма жоқ'),
                            ('done', 'Әлі ешнәрсе оқылмаған')):
            with self.subTest(tab=kind):
                response = self.client.get(
                    reverse('core:library') + f'?tab={kind}')
                self.assertContains(response, words)
        self.assertContains(self.client.get(reverse('core:library')),
                            reverse('core:catalog'))
