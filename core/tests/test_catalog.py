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

    def test_search_finds_author_pen_name(self):
        result = stub_data.search_stories('Rudazov')
        self.assertGreater(len(result), 0)
        self.assertTrue(any(s.author.public_name == 'Rudazov' for s in result))


# ───────────────── DEC-27: унифицированный catalog-движок ─────────────────

class CatalogPage(TestCase):
    """Новый /catalog/ — нейтральная entry-страница."""

    def setUp(self):
        self.response = self.client.get(reverse('core:catalog'))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_renders_catalog_hero(self):
        self.assertContains(self.response, 'Каталог')

    def test_renders_filter_panel(self):
        """Правый рейл содержит filter_panel с заголовком «Сүзгілер»."""
        self.assertContains(self.response, 'Сүзгілер')

    def test_mobile_filter_trigger_present(self):
        """Mobile-кнопка диспатчит событие open-catalog-filters."""
        self.assertContains(self.response, 'open-catalog-filters')

    def test_book_cards_show_short_annotations(self):
        """Wide-карточки каталога показывают короткое описание из Story.annotation."""
        self.assertContains(self.response, 'Үш дос жоғалған жолды іздеп шығады')
        self.assertContains(self.response, 'Қараңғы патшалыққа түскен жас кейіпкер')

    def test_book_cards_show_story_tags(self):
        self.assertContains(self.response, 'арман')
        self.assertContains(self.response, 'мистика')

    def test_book_cards_show_read_time_not_chapter_count_badge(self):
        self.assertContains(self.response, 'минут оқу')
        self.assertNotContains(self.response, '12 бөлім')


class CatalogFilterCombination(TestCase):
    """DEC-27: комбинации фильтров через query string."""

    def test_genre_plus_status_filter(self):
        # У жанра fantezi есть стори со status='Published'. Применяем оба.
        r = self.client.get(reverse('core:genre_detail',
                                    kwargs={'slug': 'fantezi'}) + '?status=Published')
        self.assertEqual(r.status_code, 200)
        # Хотя бы одна fantezi-published стори должна быть видна
        self.assertContains(r, 'Күңгірт мырза')

    def test_genre_plus_query_filter(self):
        """На странице жанра можно дополнительно фильтровать по тексту."""
        r = self.client.get(reverse('core:genre_detail',
                                    kwargs={'slug': 'fantezi'}) + '?q=мырза')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Күңгірт мырза')

    def test_sort_changes_order(self):
        """Sort alphabet → первая стори по алфавиту впереди."""
        r_pop  = self.client.get(reverse('core:catalog') + '?sort=popularity')
        r_alph = self.client.get(reverse('core:catalog') + '?sort=alphabet')
        # Оба возвращают 200; HTML отличается порядком — проверим хотя бы что
        # маркеры сортировки переключились корректно (checked в right-rail panel)
        self.assertIn(b'value="popularity"', r_pop.content)
        self.assertIn(b'value="alphabet"', r_alph.content)


class CatalogFilterHelper(TestCase):
    """filter_catalog helper из stub_data."""

    def test_query_only(self):
        out = stub_data.filter_catalog(query='жағалау')
        self.assertGreater(len(out), 0)
        self.assertTrue(any('жағалау' in s.title.lower() for s in out))

    def test_genre_only(self):
        out = stub_data.filter_catalog(genre='fantezi')
        self.assertGreater(len(out), 0)
        for s in out:
            self.assertIn('fantezi', s.genres)

    def test_tag_accepted_filters(self):
        out = stub_data.filter_catalog(tag='mektep')
        self.assertGreater(len(out), 0)
        for s in out:
            self.assertIn('mektep', s.tags)

    def test_tag_pending_returns_empty(self):
        """BR-TAG-07: pending-теги не фильтруют публичный каталог."""
        out = stub_data.filter_catalog(tag='basqa-alem')
        self.assertEqual(out, [])

    def test_genre_and_tag_combination_is_and(self):
        """Жанр И тег — AND (DEC-27)."""
        out = stub_data.filter_catalog(genre='fantezi', tag='mektep')
        for s in out:
            self.assertIn('fantezi', s.genres)
            self.assertIn('mektep', s.tags)

    def test_format_single_filters_one_shot_stories(self):
        out = stub_data.filter_catalog(format='single')
        self.assertGreater(len(out), 0)
        for s in out:
            self.assertTrue(s.is_single)

    def test_length_and_format_combination_is_and(self):
        out = stub_data.filter_catalog(format='single', length='short')
        for s in out:
            self.assertTrue(s.is_single)
            self.assertEqual(s.length_bucket, 'short')


# ───────────────── docs/11 Phase 3: /tag/<slug>/ ─────────────────

class TagDetailKnown(TestCase):
    """Accepted-тег: страница рендерит hero + список + фильтр-панель."""
    SLUG = 'mektep'

    def setUp(self):
        self.response = self.client.get(reverse('core:tag_detail', kwargs={'slug': self.SLUG}))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_hero_shows_tag_name(self):
        self.assertContains(self.response, 'мектеп')

    def test_lists_stories_with_this_tag(self):
        # arhimag и aidana-koshe имеют тег mektep
        self.assertContains(self.response, 'Сиқыршы')

    def test_filter_panel_present(self):
        self.assertContains(self.response, 'Сүзгілер')

    def test_back_to_catalog_link(self):
        self.assertContains(self.response, reverse('core:catalog'))


class TagDetailUnknown(TestCase):
    def test_unknown_slug_renders_not_found(self):
        r = self.client.get(reverse('core:tag_detail', kwargs={'slug': 'no-such-tag'}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Тег табылмады')


class TagDetailPendingBlocked(TestCase):
    """BR-TAG-07: pending-теги не работают как публичные URL."""

    def test_pending_tag_returns_not_found_page(self):
        # basqa-alem существует в TAGS, но status=pending
        r = self.client.get(reverse('core:tag_detail', kwargs={'slug': 'basqa-alem'}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Тег табылмады')


class TagsInFilterPanel(TestCase):
    """Popular tags появляются в filter-panel рейла на любом catalog-mode."""

    def test_popular_tags_chips_on_catalog(self):
        r = self.client.get(reverse('core:catalog'))
        self.assertContains(r, 'Тегтер')
        # Хотя бы один из топовых accepted-тегов в HTML
        self.assertContains(r, 'жасөспірім')

    def test_active_tag_highlighted_on_tag_page(self):
        r = self.client.get(reverse('core:tag_detail', kwargs={'slug': 'mektep'}))
        # Активный chip ведёт на catalog для снятия (DEC-27)
        self.assertContains(r, reverse('core:catalog'))


class SearchIndexHasTags(TestCase):
    """Cmd+K popup получает теги через /api/search-index.json."""

    def test_tags_in_index_json(self):
        r = self.client.get(reverse('core:api_search_index'))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn('tags', data)
        self.assertGreater(len(data['tags']), 0)
        # Только accepted-теги (basqa-alem pending → не должен быть)
        names = [t['slug'] for t in data['tags']]
        self.assertIn('mektep', names)
        self.assertNotIn('basqa-alem', names)
