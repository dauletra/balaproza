"""Каталог, поиск, жанры, теги, жинақтар — один движок на четыре режима.

DEC-27 свёл `/search/`, `/genres/<slug>/`, `/tag/<slug>/` и `/catalog/` в
одну выдачу с общим набором осей. Поэтому здесь почти нет тестов «на
страницу»: проверяются оси и то, что состояние выбора не теряется при
переходах — именно это ломалось молча, отдавая 200 без половины работ.

Правила осей проверяются на своих данных (`factories`): корпус отвечает
на вопрос «сколько сейчас работ с отметкой 14+», а ось — на вопрос
«накопительная ли она». Корпус остаётся там, где нужен объём: пагинация,
счётчики пресетов, порядок сортировок.
"""

from django.urls import reverse

from core import data
from core.models import Story
from core.tests import factories as make
from core.tests.base import TestCase, login_as
from core.views.catalog import PAGE_SIZE


class SearchAnswersOrExplainsItself(TestCase):

    def _search(self, query=''):
        return self.client.get(reverse('core:search_results') + f'?q={query}')

    def test_without_a_query_it_invites_instead_of_denying(self):
        """«Ештеңе табылмады» на пустом запросе звучит как поломка."""
        response = self._search()
        self.assertContains(response, 'Не іздейміз?')
        self.assertNotContains(response, 'Ештеңе табылмады')

    def test_a_match_is_echoed_and_shown(self):
        story = make.story(chapters=1, title='Жалғыз шам')
        response = self._search('Жалғыз шам')
        self.assertContains(response, 'Жалғыз шам')
        self.assertNotContains(response, 'Ештеңе табылмады')
        self.assertIn(story.slug, [s.slug for s in response.context['results']])

    def test_nothing_found_says_so_and_renders_no_cards(self):
        response = self._search('zzznosuchquery')
        self.assertContains(response, 'Ештеңе табылмады')
        self.assertNotContains(response, 'aria-label="«')

    def test_it_looks_at_the_author_too_and_ignores_case(self):
        """Ради этого и выбран Postgres: у SQLite `LIKE` складывает регистр
        только для ASCII, и «РЫСҚАЛИ» не нашло бы «Рысқали»."""
        author = make.user(name='Рысқали Тест', pen_name='Rudazov Test')
        make.story(author=author, chapters=1)
        upper = data.filter_catalog(query='РЫСҚАЛИ ТЕСТ')
        lower = data.filter_catalog(query='рысқали тест')
        self.assertGreater(len(upper), 0)
        self.assertEqual([s.slug for s in upper], [s.slug for s in lower])
        self.assertTrue(any(s.author.public_name == 'Rudazov Test'
                            for s in data.filter_catalog(query='Rudazov Test')))

    def test_an_empty_query_is_not_an_axis_at_all(self):
        """Пустой запрос — не «ничего не найдено», а «ось не выставлена»:
        страница решает сама, показывать ли idle-состояние."""
        everything = [s.slug for s in data.filter_catalog()]
        self.assertEqual([s.slug for s in data.filter_catalog(query='')], everything)
        self.assertEqual([s.slug for s in data.filter_catalog(query='   ')], everything)


class GenreAndCollectionPages(TestCase):

    def test_the_index_lists_every_genre_and_links_to_it(self):
        response = self.client.get(reverse('core:genre_index'))
        for genre in data.all_genres():
            with self.subTest(genre=genre.slug):
                self.assertContains(response, genre.name)
                self.assertContains(response, reverse(
                    'core:genre_detail', kwargs={'slug': genre.slug}))

    def test_a_genre_page_shows_its_own_work_and_a_way_back(self):
        genre = data.genre_by_slug('fantezi')
        story = make.story(chapters=1, primary_genre=genre, title='Жанр сынағы')
        response = self.client.get(reverse('core:genre_detail',
                                           kwargs={'slug': 'fantezi'}))
        self.assertContains(response, genre.name)
        self.assertContains(response, story.title)
        self.assertContains(response, reverse('core:genre_index'))

    def test_collections_are_editorial_and_count_themselves(self):
        """Пользовательских подборок нет (DEC-31): личное хранение — это
        «Кітапхана»."""
        login_as(self.client)
        response = self.client.get(reverse('core:collections'))
        self.assertNotContains(response, 'Өз жинағыңды құру')
        self.assertContains(response, 'редакция')
        for collection in data.all_collections():
            with self.subTest(collection=collection.slug):
                self.assertContains(response, collection.name)
                self.assertContains(response, f'{collection.count} шығарма')
                self.assertContains(response, reverse(
                    'core:collection_detail', kwargs={'slug': collection.slug}))

    def test_a_collection_page_names_its_curator_and_its_stories(self):
        collection = data.all_collections()[0]
        response = self.client.get(reverse('core:collection_detail',
                                           kwargs={'slug': collection.slug}))
        self.assertContains(response, collection.name)
        self.assertContains(response, collection.curator)
        for story in collection.stories:
            with self.subTest(story=story.slug):
                self.assertContains(response, story.title)

    def test_an_unknown_slug_says_what_was_not_found(self):
        for name, kwargs, message in (
            ('core:genre_detail', {'slug': 'no-such-genre'}, 'Жанр табылмады'),
            ('core:collection_detail', {'slug': 'no-such'}, 'Жинақ табылмады'),
            ('core:tag_detail', {'slug': 'no-such-tag'}, 'Тег табылмады'),
        ):
            with self.subTest(route=name):
                response = self.client.get(reverse(name, kwargs=kwargs))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, message)


class TagPagesShowMovement(TestCase):
    """Тег — единственная ось, обновляющаяся без участия редакции (DEC-31).
    Её ценность в том, что там видно движение, поэтому «жаңа» вперёд."""

    def test_the_page_lists_its_stories_with_the_panel_and_a_way_out(self):
        tag = make.tag()
        story = make.story(chapters=1)
        story.tags.add(tag)
        response = self.client.get(reverse('core:tag_detail', kwargs={'slug': tag.slug}))
        self.assertContains(response, tag.name)
        self.assertContains(response, story.title)
        self.assertContains(response, 'Сүзгілер')
        self.assertContains(response, reverse('core:catalog'))

    def test_a_pending_tag_has_no_public_page_or_index_entry(self):
        """BR-TAG-07: тег ещё не прошёл модератора, и его страницы для
        постороннего не существует."""
        pending = make.tag(status='pending')
        make.story(chapters=1).tags.add(pending)

        response = self.client.get(reverse('core:tag_detail',
                                           kwargs={'slug': pending.slug}))
        self.assertContains(response, 'Тег табылмады')
        self.assertEqual(list(data.filter_catalog(tag=pending.slug)), [])

        payload = self.client.get(reverse('core:api_search_index')).json()
        slugs = [t['slug'] for t in payload['tags']]
        self.assertNotIn(pending.slug, slugs)
        self.assertIn('mektep', slugs)

    def test_a_tag_opens_on_recent_while_the_rest_open_on_trending(self):
        """DEC-36 сделал дефолтом окно в 14 дней. Тег при этом остаётся на
        «Жаңалары»: DEC-31 не отменён, свежесть там ценна сама по себе."""
        tag_page = self.client.get(reverse('core:tag_detail', kwargs={'slug': 'mektep'}))
        self.assertEqual(tag_page.context['sort'], 'recent')

        explicit = self.client.get(
            reverse('core:tag_detail', kwargs={'slug': 'mektep'}) + '?sort=popularity')
        self.assertEqual(explicit.context['sort'], 'popularity')

        for name, kwargs in (('core:catalog', {}),
                             ('core:genre_detail', {'slug': 'triller'}),
                             ('core:search_results', {})):
            with self.subTest(route=name):
                self.assertEqual(
                    self.client.get(reverse(name, kwargs=kwargs)).context['sort'],
                    'trending')


class TheEngineCombinesAxesWithAnd(TestCase):
    """`filter_catalog` — то, чем отвечают все четыре режима. Отдельных
    хелперов под жанр и под поиск нет: тест, живущий на своей ветке кода,
    сторожит себя, а не продукт."""

    def test_each_axis_narrows_and_they_stack(self):
        genre = data.genre_by_slug('fantezi')
        tag = make.tag()
        wanted = make.story(chapters=1, primary_genre=genre, chars=600)
        wanted.tags.add(tag)
        make.story(chapters=1, primary_genre=genre)          # без тега
        make.story(chapters=1)                               # без жанра

        both = data.filter_catalog(genre='fantezi', tag=tag.slug)
        self.assertEqual([s.slug for s in both], [wanted.slug])
        for story in data.filter_catalog(genre='fantezi'):
            self.assertIn('fantezi', [g.slug for g in story.genres_resolved])

    def test_length_and_kind_stack_too(self):
        for story in data.filter_catalog(kind='single', length='short'):
            with self.subTest(story=story.slug):
                self.assertTrue(story.is_single)
                self.assertEqual(story.length_bucket, 'short')

    def test_an_unknown_axis_value_empties_or_is_ignored(self):
        """Неизвестный жанр — пустая выдача (такого раздела нет),
        неизвестное значение оси — просто ничего не значит."""
        self.assertEqual(list(data.filter_catalog(genre='no-such-genre')), [])
        plain = self.client.get(reverse('core:catalog')).context['total_results']
        for junk in ('?badge=no-such', '?author_tier=no-such', '?kind=no-such',
                     '?audience=99%2B', '?genre=no-such&tag=no-such',
                     '?format=single'):
            with self.subTest(query=junk):
                response = self.client.get(reverse('core:catalog') + junk)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['total_results'], plain)


class TheCatalogPageRendersItsParts(TestCase):

    def setUp(self):
        self.response = self.client.get(reverse('core:catalog'))

    def test_hero_panel_and_mobile_trigger(self):
        self.assertContains(self.response, 'Каталог')
        self.assertContains(self.response, 'Сүзгілер')
        self.assertContains(self.response, 'open-catalog-filters')
        self.assertContains(self.response, 'Тегтер')

    def test_a_card_carries_annotation_tags_and_reading_time(self):
        first = self.response.context['results'][0]
        self.assertContains(self.response, first.annotation[:40])
        self.assertContains(self.response, 'минут оқу')
        for tag in first.tags_resolved[:1]:
            self.assertContains(self.response, tag.name)

    def test_the_card_survives_a_narrow_screen(self):
        """На 375px колонка контента сжималась до 171px и разворачивалась
        в ~430px высоты: у карточки не было ни одного брейкпоинта."""
        self.assertContains(self.response, 'h-[132px] w-[88px] sm:h-[180px] sm:w-[120px]')
        self.assertContains(self.response, 'line-clamp-2')
        self.assertContains(self.response, 'sm:line-clamp-4')
        # Теги не выбрасываем — прячем стилем: жанр в мета-строке уже несёт
        # таксономию, а переход по тегу нужен на десктопе.
        self.assertContains(self.response, 'hidden sm:block')

    def test_the_mobile_control_bar_keeps_sort_outside_the_sheet(self):
        """Автосабмит остался только в рейле: в модалке каждый тап уносил
        страницу вместе с самим листом."""
        body = self.response.content.decode()
        self.assertContains(self.response, 'sticky top-16')
        self.assertContains(self.response, 'id="sort-mobile"')
        self.assertEqual(body.count('$el.requestSubmit()'), 1)
        self.assertIn('Нәтижелерді көрсету', body)
        # У 14px радиокнопки реальная цель была ~20px.
        self.assertContains(self.response, 'min-h-11')


class ChoiceSurvivesEveryTransition(TestCase):
    """Чипы жанра и тега вели на голый путь и молча сбрасывали остальные оси:
    человек ставил «14+» и «көп бөлімді», тыкал в жанр — и обе оси исчезали
    без единого следа в интерфейсе (FR-CAT-08)."""

    def _href(self, response, key, slug):
        return next(o['href'] for o in response.context[f'{key}_options']
                    if o[key].slug == slug)

    def test_a_genre_or_tag_link_carries_the_other_axes(self):
        response = self.client.get(
            reverse('core:catalog') + '?audience=14%2B&kind=ongoing')
        genre_href = self._href(response, 'genre', 'triller')
        self.assertIn('/genres/triller/', genre_href)
        self.assertIn('audience=14%2B', genre_href)
        self.assertIn('kind=ongoing', genre_href)

        tag_href = self._href(response, 'tag', 'mektep')
        self.assertIn('/tag/mektep/', tag_href)
        self.assertIn('audience=14%2B', tag_href)

    def test_only_an_explicit_sort_travels(self):
        """DEC-31: тег открывается «жаңалары» вперёд. Неявная сортировка
        каталога не должна ехать в ссылку и отменять это."""
        plain = self.client.get(reverse('core:catalog'))
        self.assertNotIn('sort=', self._href(plain, 'tag', 'mektep'))
        self.assertNotIn('sort=', self._href(plain, 'genre', 'triller'))

        chosen = self.client.get(reverse('core:catalog') + '?sort=alphabet')
        self.assertIn('sort=alphabet', self._href(chosen, 'genre', 'triller'))

    def test_the_active_axis_link_and_clear_stay_inside_the_section(self):
        """«Тазалау» снимает сүзгі, но не выкидывает из жанра."""
        inside = self.client.get(
            reverse('core:genre_detail', kwargs={'slug': 'triller'}) + '?audience=14%2B')
        href = self._href(inside, 'genre', 'triller')
        self.assertNotIn('/genres/', href)
        self.assertIn('audience=14%2B', href)
        self.assertEqual(inside.context['clear_href'],
                         reverse('core:genre_detail', kwargs={'slug': 'triller'}))

        bare = self.client.get(reverse('core:catalog') + '?audience=14%2B')
        self.assertEqual(bare.context['clear_href'], reverse('core:catalog'))

    def test_the_second_axis_may_arrive_as_a_query(self):
        """DEC-27 обещал `/genres/triller/?tag=mektep`, но view параметр не
        читал. Путь при этом сильнее query — канонический адрес остаётся
        источником истины."""
        base = reverse('core:genre_detail', kwargs={'slug': 'fantezi'})
        wide = self.client.get(base)
        narrow = self.client.get(base + '?tag=mektep')
        self.assertLess(narrow.context['total_results'], wide.context['total_results'])
        for story in narrow.context['results']:
            self.assertIn('fantezi', [g.slug for g in story.genres_resolved])
            self.assertIn('mektep', [t.slug for t in story.tags_resolved])

        collision = self.client.get(
            reverse('core:genre_detail', kwargs={'slug': 'triller'}) + '?genre=fantezi')
        for story in collision.context['results']:
            self.assertIn('triller', [g.slug for g in story.genres_resolved])

    def test_each_active_axis_gets_a_chip_that_drops_only_itself(self):
        """Снять одну ось можно, не открывая панель: раньше был только
        «Тазалау»."""
        response = self.client.get(
            reverse('core:genre_detail', kwargs={'slug': 'triller'})
            + '?audience=14%2B&length=short')
        labels = [c['label'] for c in response.context['active_chips']]
        self.assertIn('Триллер', labels)
        self.assertIn('14+', labels)
        self.assertIn('10 минутқа дейін', labels)
        self.assertEqual(response.context['active_count'], 3)

        two = self.client.get(reverse('core:catalog') + '?audience=14%2B&kind=ongoing')
        href = next(c['href'] for c in two.context['active_chips']
                    if c['label'] == '14+')
        self.assertNotIn('audience=', href)
        self.assertIn('kind=ongoing', href)
        self.assertContains(two, '>2</span>')       # бейдж на кнопке сүзгі

        bare = self.client.get(reverse('core:catalog'))
        self.assertEqual(bare.context['active_chips'], [])
        self.assertEqual(bare.context['active_count'], 0)


class TrendingIsTheDefaultSort(TestCase):
    """Дефолтом была накопленная популярность — то есть рейтинг просмотров.

    docs/13 §13.2 определяет Wattpad-культуру как «популярность важнее
    качества» и противопоставляет ей свою, а первую страницу каталога
    навсегда занимали несколько старых хитов. Окно в 14 дней показывает,
    что читают сейчас, и пускает наверх работы, которые только набирают.
    """

    def test_the_catalog_opens_on_the_two_week_window(self):
        response = self.client.get(reverse('core:catalog'))
        self.assertEqual(response.context['sort'], 'trending')
        self.assertEqual(response.context['sort_label'], 'Қазір танымал')
        recent = [s.recent_views for s in response.context['results']]
        self.assertEqual(recent, sorted(recent, reverse=True))
        # Дефолт не уезжает в генерируемые ссылки.
        href = next(o['href'] for o in response.context['genre_options']
                    if o['genre'].slug == 'triller')
        self.assertNotIn('sort=', href)

    def test_all_time_popularity_is_a_different_order_and_still_available(self):
        """Если порядки совпадают, ось ничего не добавляет."""
        trending = self.client.get(reverse('core:catalog'))
        alltime = self.client.get(reverse('core:catalog') + '?sort=popularity')
        views = [s.views for s in alltime.context['results']]
        self.assertEqual(views, sorted(views, reverse=True))
        self.assertNotEqual([s.slug for s in trending.context['results']][:5],
                            [s.slug for s in alltime.context['results']][:5])


class QualityIsAnAxisOfItsOwn(TestCase):
    """«Редакция таңдауы» — знак качества платформы (docs/13 §13.7), а не
    просмотры. До этой оси он был неотличимой подписью на карточке."""

    def test_each_badge_selects_the_works_carrying_it(self):
        for value, label in (('editorial', 'Редакция таңдауы'),
                             ('contest', 'Байқауға қатысады')):
            with self.subTest(badge=value):
                results = self.client.get(
                    reverse('core:catalog') + f'?badge={value}').context['results']
                self.assertGreater(len(results), 0)
                for story in results:
                    self.assertIn(label, story.badges)

    def test_it_is_an_axis_in_the_panel_and_stacks_with_genre(self):
        response = self.client.get(reverse('core:catalog'))
        self.assertIn('badge', [g['name'] for g in response.context['filter_groups']])
        for story in data.filter_catalog(genre='fantastika', badge='editorial'):
            self.assertIn('fantastika', [g.slug for g in story.genres_resolved])
            self.assertIn('Редакция таңдауы', story.badges)


class PresetsAreOneTapCombinations(TestCase):
    """«Не оқимын?» — комбинация осей одним тапом (docs/13 §13.6).
    `single + short` §13.11 называет быстрым чтением дословно, но собрать
    её в панели значило два тапа в двух разных группах."""

    def test_a_preset_expands_into_its_axes(self):
        response = self.client.get(reverse('core:catalog'))
        href = next(p['href'] for p in response.context['presets']
                    if p['slug'] == 'bir-otyrysta')
        self.assertIn('kind=single', href)
        self.assertIn('length=short', href)

    def test_counts_are_real_scoped_and_never_zero(self):
        """Счётчик — про всю выдачу пресета, а не про её первую страницу;
        чип, ведущий в пустоту, хуже отсутствующего."""
        response = self.client.get(reverse('core:catalog'))
        for preset in response.context['presets']:
            with self.subTest(preset=preset['slug']):
                self.assertGreater(preset['count'], 0)
                target = self.client.get(preset['href'])
                self.assertEqual(preset['count'], target.context['total_results'])

        narrow = self.client.get(reverse('core:genre_detail', kwargs={'slug': 'erteg'}))
        self.assertLess(
            next(p['count'] for p in narrow.context['presets']
                 if p['slug'] == 'bir-otyrysta'),
            next(p['count'] for p in response.context['presets']
                 if p['slug'] == 'bir-otyrysta'))

    def test_an_active_preset_absorbs_its_own_chips(self):
        """Пресет и рядом чипы его же осей — один выбор, показанный трижды.
        Бейдж на кнопке при этом продолжает считать настоящие оси."""
        response = self.client.get(reverse('core:catalog') + '?kind=single&length=short')
        active = [p for p in response.context['presets'] if p['active']]
        self.assertEqual([p['slug'] for p in active], ['bir-otyrysta'])
        self.assertEqual(active[0]['href'], reverse('core:catalog'))

        labels = [c['label'] for c in response.context['active_chips']]
        self.assertNotIn('Бір бөлімді', labels)
        self.assertNotIn('10 минутқа дейін', labels)
        self.assertEqual(response.context['active_count'], 2)


class NothingUnmoderatedLeaksOut(TestCase):
    """DEC-23: в публичный каталог работа попадает только после модерации.
    `filter_catalog` стартовала с полного списка, и «Модерацияда» лежала в
    открытом каталоге наравне с опубликованными."""

    def test_a_draft_and_a_work_under_review_are_invisible_everywhere(self):
        hidden = [make.story(chapters=1, status='NotPublished', title='Жасырын жоба'),
                  make.story(chapters=1, status='OnModeration', title='Тексерудегі')]
        catalog = self.client.get(reverse('core:catalog')).context['results']
        index = self.client.get(reverse('core:api_search_index')).json()

        for story in hidden:
            with self.subTest(story=story.slug):
                self.assertNotIn(story.slug, [s.slug for s in catalog])
                self.assertNotIn(story.slug, {s['slug'] for s in index['stories']})
                found = self.client.get(
                    reverse('core:search_results') + f'?q={story.title}')
                self.assertNotIn(story.slug,
                                 [s.slug for s in found.context['results']])

        for story in data.filter_catalog():
            self.assertIn(story.status, data.PUBLIC_STATUSES)


class AnEmptyResultIsNotADeadEnd(TestCase):
    """Пустой экран предлагал «поменяй сүзгі» — и всё. Жинақтар отвечают на
    «зачем читать сейчас» (DEC-31), ровно то, чего ждёт человек с
    несложившимся запросом."""

    def test_collections_are_offered_in_the_empty_state_and_in_the_rail(self):
        empty = self.client.get(reverse('core:search_results') + '?q=zzzzqqq')
        self.assertEqual(len(empty.context['results']), 0)
        self.assertContains(empty, 'Мүмкін, мынау қызық болар')
        self.assertContains(empty, data.all_collections()[0].name)
        self.assertContains(self.client.get(reverse('core:catalog')),
                            'Редакция жинақтары')


class ReadingTimeHasThreeBuckets(TestCase):
    """Границы заданы намерением читателя, а не корпусом: до десяти минут
    читают между делом, десять-тридцать это рассказ за один заход, дальше
    нужна закладка.

    Прежние 15/35 были подобраны под романы — 95 % каталога лежало в первом
    бакете, а «35 минуттан ұзақ» не набирался никогда.
    """

    class _Fake:
        """Story без данных: важен только `read_minutes`."""
        def __init__(self, minutes):
            self._m = minutes
        read_minutes = property(lambda self: self._m)
        length_bucket = Story.length_bucket

    def test_the_boundaries_are_ten_and_thirty(self):
        for minutes, expected in ((1, 'short'), (10, 'short'), (11, 'medium'),
                                  (30, 'medium'), (31, 'long'), (600, 'long')):
            with self.subTest(minutes=minutes):
                self.assertEqual(self._Fake(minutes).length_bucket, expected)

    def test_the_labels_name_the_actual_boundaries(self):
        """Подпись, разошедшаяся с порогом, врёт молча."""
        labels = dict(data.CATALOG_LENGTH_FILTERS)
        self.assertIn('10', labels['short'])
        self.assertIn('30', labels['long'])

    def test_every_work_lands_in_exactly_one_bucket_and_the_filter_agrees(self):
        keys = {k for k, _ in data.CATALOG_LENGTH_FILTERS if k}
        for story in Story.objects.all():
            with self.subTest(story=story.slug):
                self.assertIn(story.length_bucket, keys)
        for key in keys:
            with self.subTest(bucket=key):
                for story in data.filter_catalog(length=key):
                    self.assertEqual(story.length_bucket, key)


class TheNewAuthorAxisFindsWhoIsNotReadYet(TestCase):
    """Ни одна ось не помогала найти автора, которого ещё не читают, при том
    что «новые имена» стоят отдельным блоком на главной, а культура портала
    построена вокруг растущего автора (docs/13 §13.2)."""

    def test_it_selects_by_follower_count_and_stacks_with_genre(self):
        genre = data.genre_by_slug('balalar')
        newcomer = make.story(author=make.user(followers=0), chapters=1,
                              primary_genre=genre)
        established = make.story(
            author=make.user(followers=data.NEW_AUTHOR_FOLLOWERS + 1),
            chapters=1, primary_genre=genre)

        slugs = {s.slug for s in data.filter_catalog(author_tier='new')}
        self.assertIn(newcomer.slug, slugs)
        self.assertNotIn(established.slug, slugs)
        for story in data.filter_catalog(genre='balalar', author_tier='new'):
            self.assertIn('balalar', [g.slug for g in story.genres_resolved])
            self.assertLess(story.author.followers, data.NEW_AUTHOR_FOLLOWERS)

    def test_it_is_offered_both_as_a_preset_and_as_an_axis(self):
        response = self.client.get(reverse('core:catalog'))
        preset = next((p for p in response.context['presets']
                       if p['slug'] == 'jana-esimder'), None)
        self.assertIsNotNone(preset)
        self.assertIn('author_tier=new', preset['href'])
        self.assertIn('author_tier',
                      [g['name'] for g in response.context['filter_groups']])


class TheAgeAxisIsCumulative(TestCase):
    """DEC-38: «Жасың» отвечает на «сколько мне лет», а не «какая отметка у
    работы».

    Точное совпадение работало против читателя: четырнадцатилетний выбирал
    «14+» и терял три четверти каталога, которые ему полностью доступны.
    Безопасное направление при этом одинаково в обоих вариантах — младшая
    вилка старших отметок не показывает.
    """

    def test_the_older_bracket_includes_the_younger_and_not_the_other_way(self):
        younger = make.story(chapters=1, audience='10+')
        older = make.story(chapters=1, audience='14+')

        adult = {s.slug for s in data.filter_catalog(audience='14+')}
        self.assertIn(younger.slug, adult)
        self.assertIn(older.slug, adult)

        child = {s.slug for s in data.filter_catalog(audience='10+')}
        self.assertIn(younger.slug, child)
        self.assertNotIn(older.slug, child)
        for story in data.filter_catalog(audience='10+'):
            self.assertEqual(story.audience, '10+')

    def test_the_label_names_the_reader_not_the_work(self):
        """«10+» в подписи повторяло ключ и читалось как отметка работы."""
        self.assertEqual(data.AUDIENCE_ORDER, ('10+', '14+'))
        self.assertEqual(dict(data.CATALOG_AUDIENCE_FILTERS)['10+'], '10-13')
        legend = next(g['legend'] for g in
                      self.client.get(reverse('core:catalog')).context['filter_groups']
                      if g['name'] == 'audience')
        self.assertEqual(legend, 'Жасың')


class KindReplacedFormatAndStatus(TestCase):
    """DEC-37: одна ось «Түрі» вместо «Формат» + «Мәртебесі».

    `status` держал две несовместимые вещи: путь модерации и завершённость
    сериала. Первая читателю не нужна — в каталоге всё уже прошло
    модерацию, — вторая осмысленна только для сериала.
    """

    def test_the_three_values_split_the_whole_catalogue(self):
        counts = {k: data.filter_catalog(kind=k).count()
                  for k, _ in data.CATALOG_KIND_FILTERS if k}
        self.assertEqual(sum(counts.values()), data.filter_catalog().count())
        for key, number in counts.items():
            with self.subTest(kind=key):
                self.assertGreater(number, 0)

    def test_each_value_means_exactly_one_thing(self):
        for story in data.filter_catalog(kind='single'):
            self.assertTrue(story.is_single)
        for story in data.filter_catalog(kind='done'):
            self.assertTrue(story.is_serial)
            self.assertEqual(story.status, 'Completed')
        for story in data.filter_catalog(kind='ongoing'):
            self.assertTrue(story.is_serial)
            self.assertEqual(story.status, 'OnProcess')

    def test_the_old_axes_are_gone_from_the_panel_and_from_the_code(self):
        """Ось «Формат» снята и как параметр (DEC-49): она тянулась через
        восемь мест каталога и требовала внимания при каждой правке."""
        names = [g['name'] for g in
                 self.client.get(reverse('core:catalog')).context['filter_groups']]
        self.assertIn('kind', names)
        self.assertNotIn('format', names)
        self.assertNotIn('status', names)
        self.assertFalse(hasattr(data, 'CATALOG_FORMAT_FILTERS'))

    def test_completion_of_a_public_serial_is_always_known(self):
        """Правило данных, ради которого DEC-37 и принят (BR-10a). Раньше
        все сериалы были помечены просто «Жарияланған», и узнать, дописан
        ли сериал, было нельзя ни по одному."""
        for story in Story.objects.all():
            if story.status not in data.PUBLIC_STATUSES:
                continue
            with self.subTest(story=story.slug):
                if story.is_serial:
                    self.assertIn(story.status, ('Completed', 'OnProcess'))
                else:
                    self.assertEqual(story.status, 'Published')


class SerialsDoNotVanishFromAnySurface(TestCase):
    """Литерал `'Published'` вместо `PUBLIC_STATUSES` — тихая пропажа: после
    DEC-37 опубликованный сериал носит `OnProcess` или `Completed`, и место,
    сравнивающее с одним литералом, теряет их все разом, ничего не ломая.
    Страница отдаёт 200, просто без половины работ."""

    def test_home_rows_and_the_search_index_still_carry_them(self):
        home = self.client.get(reverse('core:home'))
        self.assertTrue(any(s.is_serial for s in home.context['top_stories']))
        self.assertTrue(home.context['serial_stories'])
        for story in home.context['serial_stories']:
            self.assertEqual(story.status, 'OnProcess')   # ряд «Жалғасып жатқан»

        indexed = {s['slug'] for s in
                   self.client.get(reverse('core:api_search_index')).json()['stories']}
        serials = {s.slug for s in Story.objects.all()
                   if s.is_serial and s.status in data.PUBLIC_STATUSES}
        self.assertTrue(serials <= indexed)


class TheCatalogIsPaginated(TestCase):
    """NFR-13: длинный список не грузится разом. До этого каталог отдавал
    **всю** публичную выдачу в одном ответе — на двадцати трёх работах
    незаметно, на десяти тысячах это полная выборка со всеми join'ами.
    Компонент пагинации при этом был написан и лежал неподключённым."""

    def test_a_page_is_capped_but_the_count_is_about_everything(self):
        """«20 шығарма» на первой странице из двух было бы неправдой."""
        response = self.client.get(reverse('core:catalog'))
        total = data.filter_catalog().count()
        self.assertLessEqual(len(response.context['results']), PAGE_SIZE)
        self.assertEqual(response.context['page'].number, 1)
        self.assertEqual(response.context['total_results'], total)
        self.assertContains(response, f'{total} шығарма')

    def test_the_next_page_continues_the_same_order_and_keeps_the_filters(self):
        first = self.client.get(reverse('core:catalog'))
        if first.context['page'].paginator.num_pages < 2:
            self.skipTest('в корпусе меньше двух страниц')
        second = self.client.get(reverse('core:catalog') + '?page=2')
        self.assertEqual([s.slug for s in first.context['results']]
                         + [s.slug for s in second.context['results']],
                         [s.slug for s in data.filter_catalog()])

        filtered = self.client.get(reverse('core:catalog') + '?audience=14%2B')
        self.assertEqual(filtered.context['page_base'], reverse('core:catalog'))
        self.assertIn('audience=14%2B', filtered.context['page_qs'])
        self.assertNotIn('page=', filtered.context['page_qs'])

    def test_a_junk_page_opens_the_first_one_and_a_short_list_has_no_nav(self):
        """`?page=99` — старая ссылка или опечатка, а не 404; пагинация из
        одной страницы — шум, а не навигация."""
        for junk in ('99', '0', '-1', 'нет', ''):
            with self.subTest(page=junk):
                response = self.client.get(reverse('core:catalog') + f'?page={junk}')
                self.assertEqual(response.status_code, 200)
                self.assertGreaterEqual(response.context['page'].number, 1)

        short = self.client.get(reverse('core:collection_detail',
                                        kwargs={'slug': data.all_collections()[0].slug}))
        self.assertNotContains(short, 'aria-label="Беттер"')
