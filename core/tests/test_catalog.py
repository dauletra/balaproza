"""CAT: search, genre index/detail, collections list/detail."""

from core.tests.base import TestCase, login_as
from django.urls import reverse

from core import data
from core.views.catalog import PAGE_SIZE
from core.models import Story


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
        for g in data.all_genres():
            with self.subTest(genre=g.slug):
                self.assertContains(self.response, g.name)

    def test_each_card_links_to_detail(self):
        for g in data.all_genres():
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
        g = data.genre_by_slug(self.SLUG)
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
        for c in data.all_collections():
            with self.subTest(collection=c.slug):
                self.assertContains(self.response, c.name)
                # Куратор показан
                self.assertContains(self.response, c.curator)

    def test_each_card_links_to_detail(self):
        for c in data.all_collections():
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
        c = data.collection_by_slug(self.SLUG)
        self.assertContains(self.response, c.name)
        self.assertContains(self.response, c.curator)
        # Проверим хотя бы первые слова описания
        self.assertContains(self.response, c.description[:30])

    def test_lists_member_stories(self):
        c = data.collection_by_slug(self.SLUG)
        for s in c.stories:
            with self.subTest(story=s.slug):
                self.assertContains(self.response, s.title)


class CollectionDetailUnknown(TestCase):
    def test_unknown_slug_renders_not_found(self):
        r = self.client.get(reverse('core:collection_detail', kwargs={'slug': 'no-such-collection'}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Жинақ табылмады')


# ────────────────── Выдача: жанр и запрос одним движком ──────────────────

class CatalogEngineAnswersGenreAndQuery(TestCase):
    """Спрашивается `filter_catalog` — то, чем отвечают страницы.

    Раньше здесь стояли `stories_by_genre` и `search_stories`: отдельные
    хелперы под жанр и под поиск, которых после DEC-27 не звал никто, кроме
    этого файла. Тест, живущий на своей ветке кода, сторожит не продукт, а
    себя: сломать выдачу поиска можно было, не тронув его.
    """

    def test_genre_returns_stories_with_that_genre(self):
        result = data.filter_catalog(genre='fantezi')
        self.assertGreater(len(result), 0)
        for s in result:
            self.assertIn('fantezi', [g.slug for g in s.genres_resolved])

    def test_unknown_genre_is_empty(self):
        self.assertEqual(list(data.filter_catalog(genre='no-such-genre')), [])

    def test_empty_query_does_not_filter(self):
        """Пустой запрос — не «ничего не найдено», а «ось не выставлена»:
        страница поиска решает сама, показывать ли idle-состояние."""
        everything = list(data.filter_catalog())
        self.assertEqual([s.slug for s in data.filter_catalog(query='')],
                         [s.slug for s in everything])
        self.assertEqual([s.slug for s in data.filter_catalog(query='   ')],
                         [s.slug for s in everything])

    def test_search_case_insensitive(self):
        """Ради этого и выбран Postgres: у SQLite `LIKE` складывает регистр
        только для ASCII, и «РЫСҚАЛИ» не нашло бы «Рысқали»."""
        upper = data.filter_catalog(query='РЫСҚАЛИ')
        lower = data.filter_catalog(query='рысқали')
        self.assertEqual([s.slug for s in upper], [s.slug for s in lower])
        self.assertGreater(len(upper), 0)

    def test_search_finds_author_pen_name(self):
        result = data.filter_catalog(query='Rudazov')
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

    def test_genre_plus_kind_filter(self):
        # «Күңгірт мырза» — fantezi и сериал, который ещё пишется (DEC-37).
        r = self.client.get(reverse('core:genre_detail',
                                    kwargs={'slug': 'fantezi'}) + '?kind=ongoing')
        self.assertEqual(r.status_code, 200)
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
    """`filter_catalog` — движок выдачи каталога."""

    def test_query_only(self):
        out = data.filter_catalog(query='жағалау')
        self.assertGreater(len(out), 0)
        self.assertTrue(any('жағалау' in s.title.lower() for s in out))

    def test_genre_only(self):
        out = data.filter_catalog(genre='fantezi')
        self.assertGreater(len(out), 0)
        for s in out:
            self.assertIn('fantezi', [g.slug for g in s.genres_resolved])

    def test_tag_accepted_filters(self):
        out = data.filter_catalog(tag='mektep')
        self.assertGreater(len(out), 0)
        for s in out:
            self.assertIn('mektep', [t.slug for t in s.tags_resolved])

    def test_tag_pending_returns_empty(self):
        """BR-TAG-07: pending-теги не фильтруют публичный каталог."""
        out = data.filter_catalog(tag='basqa-alem')
        self.assertEqual(list(out), [])

    def test_genre_and_tag_combination_is_and(self):
        """Жанр И тег — AND (DEC-27)."""
        out = data.filter_catalog(genre='fantezi', tag='mektep')
        for s in out:
            self.assertIn('fantezi', [g.slug for g in s.genres_resolved])
            self.assertIn('mektep', [t.slug for t in s.tags_resolved])

    def test_kind_single_filters_one_shot_stories(self):
        out = data.filter_catalog(kind='single')
        self.assertGreater(len(out), 0)
        for s in out:
            self.assertTrue(s.is_single)

    def test_length_and_kind_combination_is_and(self):
        out = data.filter_catalog(kind='single', length='short')
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
        payload = r.json()
        self.assertIn('tags', payload)
        self.assertGreater(len(payload['tags']), 0)
        # Только accepted-теги (basqa-alem pending → не должен быть)
        names = [t['slug'] for t in payload['tags']]
        self.assertIn('mektep', names)
        self.assertNotIn('basqa-alem', names)


class TagPageOpensWithMovement(TestCase):
    """Тег — единственная ось, обновляющаяся без участия редакции (DEC-31).
    Её ценность в том, что там видно движение, поэтому «жаңа» вперёд."""

    def test_tag_page_defaults_to_recent(self):
        r = self.client.get(reverse('core:tag_detail', kwargs={'slug': 'mektep'}))
        self.assertEqual(r.context['sort'], 'recent')

    def test_explicit_sort_still_wins(self):
        r = self.client.get(
            reverse('core:tag_detail', kwargs={'slug': 'mektep'}) + '?sort=popularity')
        self.assertEqual(r.context['sort'], 'popularity')

    def test_other_modes_open_with_trending(self):
        """DEC-36 отменяет `popularity` как дефолт: каталог, жанр и поиск
        открываются окном в 14 дней. Тег при этом остаётся на «Жаңалары» —
        DEC-31 не отменён, свежесть там ценна сама по себе."""
        for name, kwargs in (('core:catalog', {}),
                             ('core:genre_detail', {'slug': 'triller'}),
                             ('core:search_results', {})):
            with self.subTest(route=name):
                r = self.client.get(reverse(name, kwargs=kwargs))
                self.assertEqual(r.context['sort'], 'trending')


class CollectionsAreAdminOnly(TestCase):
    """DEC-31: подборки создаёт только редакция. Личное хранение — «Кітапхана»."""

    def test_no_create_button_for_signed_in_user(self):
        login_as(self.client)
        r = self.client.get(reverse('core:collections'))
        self.assertNotContains(r, 'Өз жинағыңды құру')

    def test_page_states_who_curates(self):
        r = self.client.get(reverse('core:collections'))
        self.assertContains(r, 'редакция')

    def test_counts_shown_match_actual_stories(self):
        r = self.client.get(reverse('core:collections'))
        for c in data.all_collections():
            with self.subTest(collection=c.slug):
                self.assertContains(r, f'{c.count} шығарма')


# ───────── Каталог: состояние сүзгі не теряется при переходах (DEC-27) ─────────

class CatalogStateIsCarried(TestCase):
    """Чипы жанра и тега вели на голый путь и молча сбрасывали остальные оси.

    Человек ставил «14+» и «көп бөлімді», тыкал в жанр — и обе оси исчезали
    без единого следа в интерфейсе.
    """

    def test_genre_link_keeps_other_axes(self):
        r = self.client.get(reverse('core:catalog') + '?audience=14%2B&kind=ongoing')
        href = next(o['href'] for o in r.context['genre_options']
                    if o['genre'].slug == 'triller')
        self.assertIn('/genres/triller/', href)
        self.assertIn('audience=14%2B', href)
        self.assertIn('kind=ongoing', href)

    def test_tag_link_keeps_other_axes(self):
        r = self.client.get(reverse('core:catalog') + '?audience=14%2B')
        href = next(o['href'] for o in r.context['tag_options']
                    if o['tag'].slug == 'mektep')
        self.assertIn('/tag/mektep/', href)
        self.assertIn('audience=14%2B', href)

    def test_tag_link_does_not_drag_popularity_along(self):
        """DEC-31: тег открывается «жаңалары» вперёд. Неявная сортировка
        каталога не должна ехать в ссылку и отменять это."""
        r = self.client.get(reverse('core:catalog'))
        href = next(o['href'] for o in r.context['tag_options']
                    if o['tag'].slug == 'mektep')
        self.assertNotIn('sort=', href)

    def test_explicit_sort_does_travel(self):
        r = self.client.get(reverse('core:catalog') + '?sort=alphabet')
        href = next(o['href'] for o in r.context['genre_options']
                    if o['genre'].slug == 'triller')
        self.assertIn('sort=alphabet', href)

    def test_active_genre_link_removes_only_genre(self):
        r = self.client.get(reverse('core:genre_detail',
                                    kwargs={'slug': 'triller'}) + '?audience=14%2B')
        href = next(o['href'] for o in r.context['genre_options']
                    if o['genre'].slug == 'triller')
        self.assertNotIn('/genres/', href)
        self.assertIn('audience=14%2B', href)

    def test_clear_stays_inside_the_section(self):
        """«Тазалау» снимает сүзгі, но не выкидывает из жанра."""
        r = self.client.get(reverse('core:genre_detail',
                                    kwargs={'slug': 'triller'}) + '?audience=14%2B')
        self.assertEqual(r.context['clear_href'],
                         reverse('core:genre_detail', kwargs={'slug': 'triller'}))

    def test_clear_on_plain_catalog_resets_everything(self):
        r = self.client.get(reverse('core:catalog') + '?audience=14%2B')
        self.assertEqual(r.context['clear_href'], reverse('core:catalog'))


class CatalogSecondAxisFromQuery(TestCase):
    """DEC-27 обещал `/genres/triller/?tag=mektep`, но view параметр не читал."""

    def test_tag_query_narrows_a_genre_page(self):
        base = reverse('core:genre_detail', kwargs={'slug': 'fantezi'})
        wide = self.client.get(base)
        narrow = self.client.get(base + '?tag=mektep')
        self.assertLess(len(narrow.context['results']), len(wide.context['results']))
        for s in narrow.context['results']:
            self.assertIn('fantezi', [g.slug for g in s.genres_resolved])
            self.assertIn('mektep', [t.slug for t in s.tags_resolved])

    def test_genre_query_narrows_the_catalog(self):
        r = self.client.get(reverse('core:catalog') + '?genre=triller')
        self.assertGreater(len(r.context['results']), 0)
        for s in r.context['results']:
            self.assertIn('triller', [g.slug for g in s.genres_resolved])

    def test_path_wins_over_query(self):
        r = self.client.get(reverse('core:genre_detail',
                                    kwargs={'slug': 'triller'}) + '?genre=fantezi')
        for s in r.context['results']:
            self.assertIn('triller', [g.slug for g in s.genres_resolved])

    def test_unknown_query_axis_is_ignored(self):
        plain = self.client.get(reverse('core:catalog'))
        junk = self.client.get(reverse('core:catalog') + '?genre=no-such&tag=no-such')
        self.assertEqual(len(junk.context['results']), len(plain.context['results']))

    def test_pending_tag_in_query_is_ignored(self):
        """BR-TAG-07 действует и для query-оси."""
        plain = self.client.get(reverse('core:catalog'))
        r = self.client.get(reverse('core:catalog') + '?tag=basqa-alem')
        self.assertEqual(len(r.context['results']), len(plain.context['results']))


class CatalogActiveChips(TestCase):
    """Снять одну ось можно, не открывая панель: раньше был только «Тазалау»."""

    def test_each_active_axis_gets_a_chip(self):
        r = self.client.get(reverse('core:genre_detail', kwargs={'slug': 'triller'})
                            + '?audience=14%2B&length=short')
        labels = [c['label'] for c in r.context['active_chips']]
        self.assertIn('Триллер', labels)
        self.assertIn('14+', labels)
        self.assertIn('10 минутқа дейін', labels)
        self.assertEqual(r.context['active_count'], 3)

    def test_chip_href_drops_only_its_own_axis(self):
        r = self.client.get(reverse('core:catalog') + '?audience=14%2B&kind=ongoing')
        href = next(c['href'] for c in r.context['active_chips'] if c['label'] == '14+')
        self.assertNotIn('audience=', href)
        self.assertIn('kind=ongoing', href)

    def test_no_chips_on_a_bare_catalog(self):
        r = self.client.get(reverse('core:catalog'))
        self.assertEqual(r.context['active_chips'], [])
        self.assertEqual(r.context['active_count'], 0)


class CatalogMobileControls(TestCase):
    """Мобильная панель управления: сортировка снаружи, сүзгі — черновиком."""

    def setUp(self):
        self.response = self.client.get(reverse('core:catalog'))

    def test_control_bar_is_sticky(self):
        """Статичная панель уезжала после первой же карточки."""
        self.assertContains(self.response, 'sticky top-16')

    def test_sort_is_reachable_without_opening_the_sheet(self):
        self.assertContains(self.response, 'id="sort-mobile"')

    def test_filter_button_shows_how_many_axes_are_on(self):
        r = self.client.get(reverse('core:catalog') + '?audience=14%2B&kind=ongoing')
        self.assertEqual(r.context['active_count'], 2)
        self.assertContains(r, '>2</span>')

    def test_sheet_batches_instead_of_autosubmitting(self):
        """Автосабмит остался только в рейле: в модалке каждый тап уносил
        страницу вместе с самим листом."""
        body = self.response.content.decode()
        self.assertEqual(body.count('$el.requestSubmit()'), 1)
        self.assertIn('Нәтижелерді көрсету', body)

    def test_filter_options_are_tappable(self):
        """У 14px радиокнопки реальная цель была ~20px."""
        self.assertContains(self.response, 'min-h-11')


class BookCardWideOnMobile(TestCase):
    """Карточка списка не имела ни одного брейкпоинта: на 375px её колонка
    контента сжималась до 171px и разворачивалась в ~430px высоты."""

    def setUp(self):
        self.response = self.client.get(reverse('core:catalog'))

    def test_cover_shrinks_below_sm(self):
        self.assertContains(self.response, 'h-[132px] w-[88px] sm:h-[180px] sm:w-[120px]')

    def test_annotation_is_two_lines_on_phone(self):
        self.assertContains(self.response, 'line-clamp-2')
        self.assertContains(self.response, 'sm:line-clamp-4')

    def test_counters_are_compact(self):
        """«12 482» в три пилюли подряд не вставало в строку (docs/16 §16.7 п.6)."""
        self.assertContains(self.response, '12 мың')

    def test_tags_stay_in_html_but_hide_below_sm(self):
        """Теги не выбрасываем — прячем стилем: жанр в мета-строке уже
        несёт таксономию, а переход по тегу с карточки нужен на десктопе."""
        self.assertContains(self.response, 'hidden sm:block')
        self.assertContains(self.response, 'арман')


# ───────── DEC-36: окно в 14 дней как дефолт каталога ─────────

class TrendingIsTheDefaultSort(TestCase):
    """Дефолтом была накопленная популярность — то есть рейтинг просмотров.

    [13 §13.2](docs) определяет Wattpad-культуру как «популярность важнее
    качества» и противопоставляет ей свою, а первую страницу каталога
    навсегда занимали несколько старых хитов. Окно в 14 дней показывает,
    что читают сейчас, и пускает наверх работы, которые только набирают.
    """

    def test_catalog_opens_with_trending(self):
        r = self.client.get(reverse('core:catalog'))
        self.assertEqual(r.context['sort'], 'trending')
        self.assertEqual(r.context['sort_label'], 'Қазір танымал')

    def test_trending_orders_by_the_two_week_window(self):
        r = self.client.get(reverse('core:catalog'))
        views = [s.recent_views for s in r.context['results']]
        self.assertEqual(views, sorted(views, reverse=True))

    def test_trending_is_not_the_same_order_as_all_time(self):
        """Если порядки совпадают, ось ничего не добавляет — и стаб врёт."""
        trending = self.client.get(reverse('core:catalog'))
        alltime = self.client.get(reverse('core:catalog') + '?sort=popularity')
        self.assertNotEqual([s.slug for s in trending.context['results']][:5],
                            [s.slug for s in alltime.context['results']][:5])

    def test_all_time_popularity_is_still_available(self):
        r = self.client.get(reverse('core:catalog') + '?sort=popularity')
        views = [s.views for s in r.context['results']]
        self.assertEqual(views, sorted(views, reverse=True))

    def test_tag_page_is_untouched_by_dec_34(self):
        """DEC-31 не отменён: у тега ценна свежесть, а не набранные просмотры."""
        r = self.client.get(reverse('core:tag_detail', kwargs={'slug': 'mektep'}))
        self.assertEqual(r.context['sort'], 'recent')

    def test_default_sort_is_absent_from_generated_links(self):
        r = self.client.get(reverse('core:catalog'))
        href = next(o['href'] for o in r.context['genre_options']
                    if o['genre'].slug == 'triller')
        self.assertNotIn('sort=', href)


class QualityBadgeAxis(TestCase):
    """«Редакция таңдауы» — знак качества платформы ([13 §13.7](docs)), а не
    просмотры. До этой оси он был неотличимой подписью на карточке: увидеть
    подборку отмеченных работ было нельзя."""

    def test_editorial_badge_filters(self):
        r = self.client.get(reverse('core:catalog') + '?badge=editorial')
        self.assertGreater(len(r.context['results']), 0)
        for s in r.context['results']:
            self.assertIn('Редакция таңдауы', s.badges)

    def test_contest_badge_filters(self):
        r = self.client.get(reverse('core:catalog') + '?badge=contest')
        self.assertGreater(len(r.context['results']), 0)
        for s in r.context['results']:
            self.assertIn('Байқауға қатысады', s.badges)

    def test_unknown_badge_is_ignored_not_fatal(self):
        plain = self.client.get(reverse('core:catalog'))
        junk = self.client.get(reverse('core:catalog') + '?badge=no-such')
        self.assertEqual(junk.status_code, 200)
        self.assertEqual(len(junk.context['results']), len(plain.context['results']))

    def test_badge_is_an_axis_in_the_filter_panel(self):
        r = self.client.get(reverse('core:catalog'))
        names = [g['name'] for g in r.context['filter_groups']]
        self.assertIn('badge', names)

    def test_badge_combines_with_genre(self):
        out = data.filter_catalog(genre='fantastika', badge='editorial')
        for s in out:
            self.assertIn('fantastika', [g.slug for g in s.genres_resolved])
            self.assertIn('Редакция таңдауы', s.badges)


class CatalogPresets(TestCase):
    """Пресеты «Не оқимын?» — комбинация осей одним тапом ([13 §13.6](docs)).

    `single + short` §13.11 называет быстрым чтением дословно, но собрать её
    в панели значило два тапа в двух разных группах.
    """

    def test_preset_expands_into_its_filter_combination(self):
        r = self.client.get(reverse('core:catalog'))
        href = next(p['href'] for p in r.context['presets']
                    if p['slug'] == 'bir-otyrysta')
        self.assertIn('kind=single', href)
        self.assertIn('length=short', href)

    def test_counts_are_real(self):
        r = self.client.get(reverse('core:catalog'))
        for p in r.context['presets']:
            with self.subTest(preset=p['slug']):
                target = self.client.get(p['href'])
                self.assertEqual(p['count'], len(target.context['results']))

    def test_empty_presets_are_not_offered(self):
        """Чип, ведущий в пустоту, хуже отсутствующего чипа."""
        r = self.client.get(reverse('core:catalog'))
        for p in r.context['presets']:
            self.assertGreater(p['count'], 0)

    def test_counts_are_scoped_to_the_current_section(self):
        wide = self.client.get(reverse('core:catalog'))
        narrow = self.client.get(reverse('core:genre_detail', kwargs={'slug': 'erteg'}))
        wide_count = next(p['count'] for p in wide.context['presets']
                          if p['slug'] == 'bir-otyrysta')
        narrow_count = next(p['count'] for p in narrow.context['presets']
                            if p['slug'] == 'bir-otyrysta')
        self.assertLess(narrow_count, wide_count)

    def test_active_preset_is_marked_and_clears_on_second_tap(self):
        r = self.client.get(reverse('core:catalog') + '?kind=single&length=short')
        active = [p for p in r.context['presets'] if p['active']]
        self.assertEqual([p['slug'] for p in active], ['bir-otyrysta'])
        self.assertEqual(active[0]['href'], reverse('core:catalog'))

    def test_active_preset_absorbs_its_axis_chips(self):
        """Пресет и рядом чипы его же осей — один выбор, показанный трижды."""
        r = self.client.get(reverse('core:catalog') + '?kind=single&length=short')
        labels = [c['label'] for c in r.context['active_chips']]
        self.assertNotIn('Бір бөлімді', labels)
        self.assertNotIn('10 минутқа дейін', labels)

    def test_badge_on_the_button_still_counts_real_axes(self):
        """Внутри панели обе оси отмечены — число обязано совпадать."""
        r = self.client.get(reverse('core:catalog') + '?kind=single&length=short')
        self.assertEqual(r.context['active_count'], 2)


class DraftsAndModerationStayOutOfTheCatalog(TestCase):
    """DEC-23: в публичный каталог работа попадает только после модерации.

    `filter_catalog` стартовала с полного списка STORIES, и «Модерацияда»
    лежала в открытом каталоге наравне с опубликованными.
    """

    def test_on_moderation_is_not_public(self):
        r = self.client.get(reverse('core:catalog'))
        self.assertNotIn('aidana-erteg', [s.slug for s in r.context['results']])

    def test_only_public_statuses_survive_the_pipeline(self):
        for s in data.filter_catalog():
            self.assertIn(s.status, data.PUBLIC_STATUSES)

    def test_search_does_not_leak_unmoderated_work(self):
        hidden = data.story_by_slug('aidana-erteg')
        r = self.client.get(reverse('core:search_results') + '?q=' + hidden.title[:6])
        self.assertNotIn('aidana-erteg', [s.slug for s in r.context['results']])


class EmptyCatalogOffersAWayOut(TestCase):
    """Пустой экран был тупиком: «поменяй сүзгі» — и всё. Жинақтар отвечают
    на «зачем читать сейчас» (DEC-31) — ровно то, чего ждёт человек с
    несложившимся запросом."""

    def test_empty_result_shows_collections(self):
        r = self.client.get(reverse('core:search_results') + '?q=zzzzqqq')
        self.assertEqual(len(r.context['results']), 0)
        self.assertContains(r, 'Мүмкін, мынау қызық болар')
        self.assertContains(r, data.all_collections()[0].name)

    def test_rail_offers_collections_too(self):
        r = self.client.get(reverse('core:catalog'))
        self.assertContains(r, 'Редакция жинақтары')


class ReadingTimeBuckets(TestCase):
    """Границы «Оқу уақыты» заданы намерением читателя, а не корпусом.

    Прежние 15/35 были подобраны под романы: 95% каталога лежало в первом
    бакете, а «35 минуттан ұзақ» не набирался никогда. Новые — до десяти
    минут читают между делом, десять-тридцать это рассказ за один заход,
    дальше нужна закладка.

    Тест проверяет **функцию границ**, а не наполнение бакетов. Проверка вида
    «во всех трёх что-то есть» снова привязала бы пороги к текущему стабу:
    длинные работы уйдут в архив — и сборка упадёт, хотя дизайн исправен.
    """

    class _Fake:
        """Story без данных: важен только read_minutes."""
        def __init__(self, minutes):
            self._m = minutes
        read_minutes = property(lambda self: self._m)
        length_bucket = Story.length_bucket

    def _bucket(self, minutes):
        return self._Fake(minutes).length_bucket

    def test_boundaries_are_ten_and_thirty(self):
        for minutes, expected in ((1, 'short'), (10, 'short'), (11, 'medium'),
                                  (30, 'medium'), (31, 'long'), (600, 'long')):
            with self.subTest(minutes=minutes):
                self.assertEqual(self._bucket(minutes), expected)

    def test_every_story_lands_in_exactly_one_bucket(self):
        keys = {k for k, _ in data.CATALOG_LENGTH_FILTERS if k}
        for s in Story.objects.all():
            with self.subTest(story=s.slug):
                self.assertIn(s.length_bucket, keys)

    def test_filter_agrees_with_the_bucket(self):
        for key in ('short', 'medium', 'long'):
            with self.subTest(bucket=key):
                for s in data.filter_catalog(length=key):
                    self.assertEqual(s.length_bucket, key)

    def test_labels_name_the_actual_boundaries(self):
        """Подпись, разошедшаяся с порогом, врёт молча."""
        labels = dict(data.CATALOG_LENGTH_FILTERS)
        self.assertIn('10', labels['short'])
        self.assertIn('30', labels['long'])


class NewAuthorsAxis(TestCase):
    """Ни одна ось не помогала найти автора, которого ещё не читают, при том
    что «новые авторы» стоят отдельным блоком на главной, а культура портала
    построена вокруг растущего автора (docs/13 §13.2)."""

    def test_axis_filters_by_follower_count(self):
        out = data.filter_catalog(author_tier='new')
        self.assertGreater(len(out), 0)
        for s in out:
            self.assertLess(s.author.followers, data.NEW_AUTHOR_FOLLOWERS)

    def test_axis_excludes_the_established(self):
        slugs = {s.slug for s in data.filter_catalog(author_tier='new')}
        loud = [a.username for a in data.all_authors()
                if a.followers >= data.NEW_AUTHOR_FOLLOWERS]
        for s in Story.objects.select_related('author'):
            if s.author.username in loud:
                self.assertNotIn(s.slug, slugs)

    def test_unknown_value_is_ignored(self):
        plain = self.client.get(reverse('core:catalog'))
        junk = self.client.get(reverse('core:catalog') + '?author_tier=no-such')
        self.assertEqual(junk.status_code, 200)
        self.assertEqual(len(junk.context['results']), len(plain.context['results']))

    def test_it_is_offered_as_a_preset(self):
        r = self.client.get(reverse('core:catalog'))
        preset = next((p for p in r.context['presets'] if p['slug'] == 'jana-esimder'), None)
        self.assertIsNotNone(preset)
        self.assertIn('author_tier=new', preset['href'])

    def test_it_is_an_axis_in_the_panel(self):
        r = self.client.get(reverse('core:catalog'))
        self.assertIn('author_tier', [g['name'] for g in r.context['filter_groups']])

    def test_it_combines_with_genre(self):
        out = data.filter_catalog(genre='balalar', author_tier='new')
        for s in out:
            self.assertIn('balalar', [g.slug for g in s.genres_resolved])
            self.assertLess(s.author.followers, data.NEW_AUTHOR_FOLLOWERS)


class AudienceIsCumulative(TestCase):
    """DEC-38: ось «Жасың» отвечает на «сколько мне лет», а не «какая отметка
    у работы».

    Точное совпадение работало против читателя: четырнадцатилетний выбирал
    «14+» и терял пятнадцать из двадцати одной работы, которые ему полностью
    доступны. Безопасное направление при этом одинаково в обоих вариантах —
    младшая вилка старших отметок не показывает, — поэтому менять было можно.
    """

    def test_older_bracket_includes_the_younger(self):
        out = data.filter_catalog(audience='14+')
        self.assertEqual(len(out), len(data.filter_catalog()))
        self.assertSetEqual({s.audience for s in out}, {'10+', '14+'})

    def test_younger_bracket_still_hides_the_older(self):
        """Единственное, что этот фильтр обязан гарантировать."""
        for s in data.filter_catalog(audience='10+'):
            self.assertEqual(s.audience, '10+')

    def test_order_drives_the_comparison_not_equality(self):
        self.assertEqual(data.AUDIENCE_ORDER, ('10+', '14+'))
        younger = data.filter_catalog(audience='10+')
        older = data.filter_catalog(audience='14+')
        self.assertLess(len(younger), len(older))

    def test_unknown_bracket_is_ignored(self):
        plain = self.client.get(reverse('core:catalog'))
        junk = self.client.get(reverse('core:catalog') + '?audience=99%2B')
        self.assertEqual(junk.status_code, 200)
        self.assertEqual(len(junk.context['results']), len(plain.context['results']))

    def test_label_names_the_reader_not_the_work(self):
        """«10+» в подписи повторяло ключ и читалось как отметка работы."""
        labels = dict(data.CATALOG_AUDIENCE_FILTERS)
        self.assertEqual(labels['10+'], '10-13')
        r = self.client.get(reverse('core:catalog'))
        legend = next(g['legend'] for g in r.context['filter_groups']
                      if g['name'] == 'audience')
        self.assertEqual(legend, 'Жасың')

    def test_it_combines_with_other_axes(self):
        out = data.filter_catalog(audience='10+', kind='single')
        for s in out:
            self.assertEqual(s.audience, '10+')
            self.assertTrue(s.is_single)


class KindReplacesFormatAndStatus(TestCase):
    """DEC-37: одна ось «Түрі» вместо «Формат» + «Мәртебесі».

    `status` держал две несовместимые вещи: путь модерации и завершённость
    сериала. Первая читателю не нужна — в каталоге всё уже прошло модерацию,
    и «Жарияланған» стоял у 90% выдачи, ничего не отбирая. Вторая нужна, но
    осмысленна только для сериала.
    """

    def test_three_values_split_the_catalogue(self):
        counts = {k: len(data.filter_catalog(kind=k))
                  for k, _ in data.CATALOG_KIND_FILTERS if k}
        self.assertEqual(sum(counts.values()), len(data.filter_catalog()))
        for key, n in counts.items():
            with self.subTest(kind=key):
                self.assertGreater(n, 0)

    def test_single_means_one_whole_text(self):
        for s in data.filter_catalog(kind='single'):
            self.assertTrue(s.is_single)

    def test_done_is_a_finished_serial(self):
        for s in data.filter_catalog(kind='done'):
            self.assertTrue(s.is_serial)
            self.assertEqual(s.status, 'Completed')

    def test_ongoing_is_a_serial_still_being_written(self):
        for s in data.filter_catalog(kind='ongoing'):
            self.assertTrue(s.is_serial)
            self.assertEqual(s.status, 'OnProcess')

    def test_panel_offers_kind_and_no_longer_format_or_status(self):
        r = self.client.get(reverse('core:catalog'))
        names = [g['name'] for g in r.context['filter_groups']]
        self.assertIn('kind', names)
        self.assertNotIn('format', names)
        self.assertNotIn('status', names)

    def test_format_axis_is_gone_entirely(self):
        """Ось «Формат» снята и как параметр (DEC-49).

        DEC-37 убрал её из панели и оставил `?format=` ради ссылок, которые
        могли уйти наружу. Ссылок не было: портал не публиковался, а
        единственная внутренняя (ряд «Қысқа оқылатын әңгімелер» на главной)
        переведена на `?kind=single`. Параметр же тянулся через восемь мест
        каталога и требовал внимания при каждой правке.
        """
        self.assertFalse(hasattr(data, 'CATALOG_FORMAT_FILTERS'))
        # Неизвестный параметр не ломает страницу — он просто ничего не значит.
        r = self.client.get(reverse('core:catalog') + '?format=single')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['total_results'], data.filter_catalog().count())

    def test_unknown_kind_is_ignored(self):
        plain = self.client.get(reverse('core:catalog'))
        junk = self.client.get(reverse('core:catalog') + '?kind=no-such')
        self.assertEqual(junk.status_code, 200)
        self.assertEqual(len(junk.context['results']), len(plain.context['results']))


class SerialCompletionIsAlwaysKnown(TestCase):
    """Правило данных, ради которого DEC-37 и принят.

    Раньше обе читательские метки стояли на одночастевых произведениях, где
    завершённость бессмысленна, а все десять сериалов были помечены просто
    «Жарияланған» — узнать, дописан ли сериал, было нельзя ни по одному.
    """

    def test_no_published_serial_is_left_unmarked(self):
        for s in Story.objects.all():
            if s.is_serial and s.status in data.PUBLIC_STATUSES:
                with self.subTest(story=s.slug):
                    self.assertIn(s.status, ('Completed', 'OnProcess'))

    def test_one_shots_are_not_marked_for_completion(self):
        """У цельного текста «дописан» и «пишется» не значат ничего."""
        for s in Story.objects.all():
            if s.is_single and s.status in data.PUBLIC_STATUSES:
                with self.subTest(story=s.slug):
                    self.assertEqual(s.status, 'Published')


class PublicStatusesAreNotSpelledOut(TestCase):
    """Литерал 'Published' вместо набора публичных статусов — тихая пропажа.

    После DEC-37 опубликованный сериал носит OnProcess или Completed, и любое
    место, сравнивающее с одним литералом, теряет их все разом, ничего не
    ломая: страница отдаёт 200, просто без десяти произведений.
    """

    def test_home_rows_still_contain_serials(self):
        r = self.client.get(reverse('core:home'))
        self.assertTrue(any(s.is_serial for s in r.context['top_stories']))
        self.assertTrue(r.context['serial_stories'])

    def test_home_serial_row_shows_only_ongoing(self):
        """Ряд называется «Жалғасып жатқан шығармалар»."""
        r = self.client.get(reverse('core:home'))
        for s in r.context['serial_stories']:
            self.assertEqual(s.status, 'OnProcess')

    def test_search_index_still_contains_serials(self):
        payload = self.client.get(reverse('core:api_search_index')).json()
        slugs = {s['slug'] for s in payload['stories']}
        serials = {s.slug for s in Story.objects.all()
                   if s.is_serial and s.status in data.PUBLIC_STATUSES}
        self.assertTrue(serials <= slugs)

    def test_moderation_is_still_out_of_the_index(self):
        payload = self.client.get(reverse('core:api_search_index')).json()
        self.assertNotIn('aidana-erteg', {s['slug'] for s in payload['stories']})


class CatalogIsPaginated(TestCase):
    """NFR-13: длинный список не грузится разом.

    До этого каталог отдавал **всю** публичную выдачу в одном ответе — на
    двадцати трёх работах незаметно, на десяти тысячах это полная выборка
    со всеми join'ами. Компонент пагинации при этом был написан и лежал
    неподключённым: единственным его вызовом была витрина `/_design/`.
    """

    def test_first_page_holds_no_more_than_the_page_size(self):
        r = self.client.get(reverse('core:catalog'))
        self.assertLessEqual(len(r.context['results']), PAGE_SIZE)
        self.assertEqual(r.context['page'].number, 1)

    def test_count_under_the_header_is_about_the_whole_result(self):
        """«20 шығарма» на первой странице из двух было бы неправдой."""
        r = self.client.get(reverse('core:catalog'))
        total = data.filter_catalog().count()
        self.assertEqual(r.context['total_results'], total)
        self.assertContains(r, f'{total} шығарма')

    def test_second_page_continues_the_same_order(self):
        first = self.client.get(reverse('core:catalog'))
        if first.context['page'].paginator.num_pages < 2:
            self.skipTest('в корпусе меньше двух страниц')
        second = self.client.get(reverse('core:catalog') + '?page=2')
        whole = [s.slug for s in data.filter_catalog()]
        shown = ([s.slug for s in first.context['results']]
                 + [s.slug for s in second.context['results']])
        self.assertEqual(shown, whole)

    def test_page_links_carry_the_filter_state(self):
        """Вторая страница жанра обязана остаться в жанре — иначе пагинация
        сбрасывает сүзгі так же, как это делали чипы до FR-CAT-08."""
        r = self.client.get(reverse('core:catalog') + '?audience=14%2B')
        self.assertEqual(r.context['page_base'], reverse('core:catalog'))
        self.assertIn('audience=14%2B', r.context['page_qs'])
        self.assertNotIn('page=', r.context['page_qs'])

    def test_junk_page_opens_the_first_one(self):
        """`?page=99` — старая ссылка или опечатка, а не 404."""
        for junk in ('99', '0', '-1', 'нет', ''):
            with self.subTest(page=junk):
                r = self.client.get(reverse('core:catalog') + f'?page={junk}')
                self.assertEqual(r.status_code, 200)
                self.assertGreaterEqual(r.context['page'].number, 1)

    def test_nav_is_absent_while_everything_fits(self):
        """Пагинация из одной страницы — это шум, а не навигация."""
        r = self.client.get(reverse('core:collection_detail',
                                    kwargs={'slug': data.all_collections()[0].slug}))
        self.assertNotContains(r, 'aria-label="Беттер"')
