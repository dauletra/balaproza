"""Поиск: где он ищет и что говорит, когда не нашёл.

Отдельного режима у поиска нет — это `?q=` на `/catalog/`, тот же движок
и те же оси (DEC-65); `/search/` остался рабочим редирект-адресом для
старых ссылок.

Два вопроса, на которые отвечает этот файл. **Где искать**: человек
помнит не название, а «про что было», — значит по аннотации и тегам, а
не по одному заголовку. **Что сказать, когда пусто**: не тупик, а
дорога дальше.

Быстрый поиск из шапки спрашивает сервер, а не носит с собой индекс
каталога: цена ответа не должна расти вместе с порталом. Одна буква до
базы не доходит вовсе — она находит половину каталога и не подсказывает
ничего.
"""


from django.urls import reverse

from core import data
from core.models import StoryTag, Tag
from core.tests import factories as make
from core.tests.base import TestCase


class SearchAnswersOrExplainsItself(TestCase):
    """DEC-65: поиск — `?q=` на `/catalog/`, без своего режима и пустого
    idle-состояния — без запроса это просто каталог."""

    def _search(self, query=''):
        return self.client.get(reverse('core:catalog') + f'?q={query}')

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
        author = make.user(pen_name='Рысқали Тест')
        make.story(author=author, chapters=1)
        upper = data.filter_catalog(query='РЫСҚАЛИ ТЕСТ')
        lower = data.filter_catalog(query='рысқали тест')
        self.assertGreater(len(upper), 0)
        self.assertEqual([s.slug for s in upper], [s.slug for s in lower])

    def test_an_empty_query_is_not_an_axis_at_all(self):
        """Пустой запрос — не «ничего не найдено», а «ось не выставлена»:
        страница решает сама, показывать ли idle-состояние."""
        everything = [s.slug for s in data.filter_catalog()]
        self.assertEqual([s.slug for s in data.filter_catalog(query='')], everything)
        self.assertEqual([s.slug for s in data.filter_catalog(query='   ')], everything)


class QuickSearchAsksTheServer(TestCase):
    """Подсказки Cmd+K: сервер ищет, браузер показывает.

    Раньше сервер отдавал **весь** индекс — все работы, всех авторов, все
    принятые теги, — а фильтровал его клиент. Проверять там было нечего,
    кроме состава выгрузки; теперь проверяется сам поиск, и заодно то,
    ради чего всё затевалось: выдача ограничена и не растёт с каталогом.
    """

    def _get(self, query: str) -> dict:
        return self.client.get(
            reverse('core:api_search') + f'?q={query}').json()

    def test_it_finds_by_title_and_by_author(self):
        author = make.user(pen_name='Айгерім Қасым')
        story = make.story(author=author, chapters=1, title='Жаңбырлы қала')

        by_title = self._get('Жаңбырлы')
        self.assertIn(story.slug, {s['slug'] for s in by_title['stories']})

        # Та же выдача, что у каталога: работа находится и по имени автора.
        by_author = self._get('Айгерім')
        self.assertIn(story.slug, {s['slug'] for s in by_author['stories']})
        self.assertIn(author.username,
                      {a['username'] for a in by_author['authors']})

    def test_a_short_query_does_not_reach_the_database(self):
        """Одна буква находит половину каталога и ничего не подсказывает."""
        for query in ('', 'а'):
            with self.subTest(query=query):
                with self.assertNumQueries(0):
                    found = self._get(query)
                self.assertEqual(found,
                                 {'stories': [], 'authors': [], 'tags': []})

    def test_the_answer_is_bounded_whatever_the_catalogue_size(self):
        """То, ради чего эндпоинт и переписан: цена ответа не зависит от
        числа работ на портале."""
        for number in range(8):
            make.story(chapters=1, title=f'Бірдей атау {number}')

        found = self._get('Бірдей атау')

        self.assertEqual(len(found['stories']), 5)

    def test_it_never_suggests_what_the_reader_cannot_open(self):
        hidden = make.story(chapters=1, status='NotPublished',
                            title='Жасырын жоба')
        pending = make.tag(status='pending', slug='kupiya', name='Құпия')

        self.assertEqual(self._get(hidden.title)['stories'], [])
        self.assertEqual(self._get('kupiya')['tags'], [])
        self.assertEqual(self._get(pending.name)['tags'], [])

    def test_a_tag_is_found_by_its_latin_slug(self):
        found = self._get('mektep')

        self.assertIn('mektep', {t['slug'] for t in found['tags']})


class SearchLooksWhereTheReaderLooks(TestCase):
    """Поиск искал по названию и имени автора. Читатель ищет не по имени
    работы, которого он не знает, а по тому, о чём она.

    Заодно чинится расхождение: быстрый поиск (Cmd+K) теги искал, а
    каталог — нет, и одно и то же слово давало разный результат в двух
    местах одного портала.
    """

    def setUp(self):
        super().setUp()
        self.author = make.user(username='searchable_author', pen_name='Іздеуші')
        self.story = make.story(
            slug='mektep-turaly', author=self.author, chapters=1,
            title='Атауында сөз жоқ',
            annotation='Мектеп туралы қысқа әңгіме.')
        self.tag = Tag.objects.create(slug='qorqynyshty', name='қорқынышты',
                                      status='accepted')
        StoryTag.objects.create(story=self.story, tag=self.tag)

    def _found(self, query):
        return [s.slug for s in data.filter_catalog(query=query)]

    def test_the_annotation_is_searched(self):
        self.assertIn(self.story.slug, self._found('мектеп'))

    def test_the_tag_is_searched(self):
        self.assertIn(self.story.slug, self._found('қорқынышты'))

    def test_a_tag_is_found_by_its_latin_slug_too(self):
        """Тег пишется по-казахски, а ищут его часто латиницей — ровно
        так же ведёт себя быстрый поиск."""
        self.assertIn(self.story.slug, self._found('qorqyn'))

    def test_the_title_and_the_author_still_work(self):
        self.assertIn(self.story.slug, self._found('Атауында'))
        self.assertIn(self.story.slug, self._found('Іздеуші'))

    def test_a_pending_tag_does_not_make_a_work_findable(self):
        """Непринятый тег публично не существует, и находиться по нему
        работа не должна."""
        hidden = Tag.objects.create(slug='kutude', name='күтудегі',
                                    status='pending')
        StoryTag.objects.create(story=self.story, tag=hidden)

        self.assertNotIn(self.story.slug, self._found('күтудегі'))

    def test_two_matching_tags_do_not_double_the_work(self):
        """`Exists`, а не join: совпади два тега, join вернул бы работу
        дважды, и каталог показал бы её две строки подряд."""
        second = Tag.objects.create(slug='qorqynyshty-2', name='қорқыныш',
                                    status='accepted')
        StoryTag.objects.create(story=self.story, tag=second)

        found = self._found('қорқыныш')

        self.assertEqual(found.count(self.story.slug), 1)

    def test_nothing_matching_finds_nothing(self):
        self.assertEqual(self._found('ешқашан-кездеспейтін-сөз'), [])
