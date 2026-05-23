"""CAT: search, genre index/detail, collections list/detail."""

from django.test import TestCase
from django.urls import reverse

from core import stub_data


# ───────────────────────── Search ─────────────────────────

class SearchResultsEmptyQuery(TestCase):
    def setUp(self):
        self.response = self.client.get(reverse('core:search_results'))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_shows_idle_hint(self):
        """Без ?q= показываем подсказку, не «ничего не найдено»."""
        self.assertContains(self.response, 'Не іздейміз?')
        self.assertNotContains(self.response, 'Ештеңе табылмады')


class SearchResultsWithMatches(TestCase):
    def setUp(self):
        # «Алыс жағалауларда» — точно матчится по подстроке
        self.response = self.client.get(reverse('core:search_results') + '?q=жағалау')

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_query_echo(self):
        self.assertContains(self.response, 'жағалау')

    def test_shows_matching_story(self):
        self.assertContains(self.response, 'Алыс жағалауларда')

    def test_no_empty_state(self):
        self.assertNotContains(self.response, 'Ештеңе табылмады')


class SearchResultsNoMatches(TestCase):
    def setUp(self):
        self.response = self.client.get(reverse('core:search_results') + '?q=zzznosuchquery')

    def test_shows_empty_state(self):
        self.assertContains(self.response, 'Ештеңе табылмады')

    def test_does_not_render_book_cards(self):
        # Карточек никаких не должно быть. Проверим по характерному классу wide-карточки.
        self.assertNotContains(self.response, 'aria-label="«')


class SearchByAuthorName(TestCase):
    def test_matches_author(self):
        r = self.client.get(reverse('core:search_results') + '?q=Рысқали')
        self.assertEqual(r.status_code, 200)
        # У Рысқали в стабе есть «Тас уәделер» и «Сиқыршы»
        self.assertContains(r, 'Тас уәделер')


# ───────────────────────── Genre index ─────────────────────────

class GenreIndex(TestCase):
    def setUp(self):
        self.response = self.client.get(reverse('core:genre_index'))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_lists_all_12_genres(self):
        for g in stub_data.GENRES:
            with self.subTest(genre=g.slug):
                self.assertContains(self.response, g.name)

    def test_each_card_links_to_detail(self):
        for g in stub_data.GENRES:
            with self.subTest(genre=g.slug):
                url = reverse('core:genre_detail', kwargs={'slug': g.slug})
                self.assertContains(self.response, f'href="{url}"')


# ───────────────────────── Genre detail ─────────────────────────

class GenreDetailKnown(TestCase):
    SLUG = 'fantezi'   # есть в STORIES хотя бы у одной книги

    def setUp(self):
        self.response = self.client.get(reverse('core:genre_detail', kwargs={'slug': self.SLUG}))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_shows_genre_name_in_header(self):
        g = stub_data.GENRES_BY_SLUG[self.SLUG]
        self.assertContains(self.response, g.name)

    def test_shows_filtered_stories(self):
        # «Күңгірт мырза»: genres=('fantezi','horror') → должен быть в выдаче
        self.assertContains(self.response, 'Күңгірт мырза')

    def test_back_to_genres_link(self):
        self.assertContains(self.response, reverse('core:genre_index'))


class GenreDetailUnknown(TestCase):
    def test_unknown_slug_renders_not_found(self):
        r = self.client.get(reverse('core:genre_detail', kwargs={'slug': 'no-such-genre'}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Жанр табылмады')


# ───────────────────────── Collections list ─────────────────────────

class CollectionsList(TestCase):
    def setUp(self):
        self.response = self.client.get(reverse('core:collections'))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_lists_all_collections(self):
        for c in stub_data.COLLECTIONS:
            with self.subTest(collection=c.slug):
                self.assertContains(self.response, c.name)
                # Куратор показан
                self.assertContains(self.response, c.curator)

    def test_each_card_links_to_detail(self):
        for c in stub_data.COLLECTIONS:
            with self.subTest(collection=c.slug):
                url = reverse('core:collection_detail', kwargs={'slug': c.slug})
                self.assertContains(self.response, f'href="{url}"')


# ───────────────────────── Collection detail ─────────────────────────

class CollectionDetailKnown(TestCase):
    SLUG = 'kazak-avt'

    def setUp(self):
        self.response = self.client.get(reverse('core:collection_detail', kwargs={'slug': self.SLUG}))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_shows_name_curator_description(self):
        c = stub_data.COLLECTIONS_BY_SLUG[self.SLUG]
        self.assertContains(self.response, c.name)
        self.assertContains(self.response, c.curator)
        # Проверим хотя бы первые слова описания
        self.assertContains(self.response, c.description[:30])

    def test_lists_member_stories(self):
        c = stub_data.COLLECTIONS_BY_SLUG[self.SLUG]
        for s in c.stories:
            with self.subTest(story=s.slug):
                self.assertContains(self.response, s.title)


class CollectionDetailUnknown(TestCase):
    def test_unknown_slug_renders_not_found(self):
        r = self.client.get(reverse('core:collection_detail', kwargs={'slug': 'no-such-collection'}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Жинақ табылмады')


# ───────────────────────── Stub-data helpers ─────────────────────────

class HelperFunctions(TestCase):
    def test_stories_by_genre_returns_stories_with_that_genre(self):
        result = stub_data.stories_by_genre('fantezi')
        self.assertGreater(len(result), 0)
        for s in result:
            self.assertIn('fantezi', s.genres)

    def test_stories_by_unknown_genre_is_empty(self):
        self.assertEqual(stub_data.stories_by_genre('no-such-genre'), [])

    def test_search_empty_query_returns_empty(self):
        self.assertEqual(stub_data.search_stories(''), [])
        self.assertEqual(stub_data.search_stories('   '), [])

    def test_search_case_insensitive(self):
        upper = stub_data.search_stories('РЫСҚАЛИ')
        lower = stub_data.search_stories('рысқали')
        self.assertEqual([s.slug for s in upper], [s.slug for s in lower])
        self.assertGreater(len(upper), 0)
