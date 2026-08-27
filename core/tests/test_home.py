"""Главная: порядок фолдов, редакционные блоки, режимы гостя и вошедшего.

Главная — единственная страница, где проверяется **порядок**, а не только
наличие: подросток заходит с телефона, и если первый экран занят поиском,
ценность портала не считывается. Поэтому здесь много `assertLess` по
индексам в разметке — это не хрупкость, а само требование (DEC-31).

Один запрос на класс, а не на утверждение: сценарий «гость открыл
главную» один, и вопросов к нему полтора десятка.
"""

import re

from django.urls import reverse

from core import data
from core.templatetags.balaproza import spaced
from core.tests.base import TestCase, login_as


class GuestSeesTheEditorialFront(TestCase):
    """Первый фолд: hero, полоса жанров, жинақтар, наполненный ряд.

    Порядок задан DEC-31: жанр — вывеска, а вопрос о настроении идёт
    вперёд ряда обложек.
    """

    def setUp(self):
        self.response = self.client.get(reverse('core:home'))
        self.html = self.response.content.decode()

    def test_hero_states_the_scale_and_who_writes_here(self):
        stats = self.response.context['portal_stats']
        self.assertEqual(stats['genres'], 12)
        self.assertGreater(stats['stories'], 0)
        self.assertContains(self.response, f"{stats['stories']} шығарма")
        self.assertContains(self.response, f"{stats['authors']} автор")
        self.assertContains(self.response, 'Бүгін не оқимыз?')
        self.assertContains(self.response, 'Құрдастарың жазған')
        self.assertContains(self.response, 'Шығарма, автор, жанр немесе тег')

    def test_the_folds_come_in_the_order_the_reader_needs(self):
        """hero → полоса жанров → жинақтар → ряды → книга недели →
        конкурс → новые имена → призыв стать автором.

        «Автор болу» больше не занимает бюджет первого фолда, а одна
        сильная рекомендация идёт раньше конкурса.
        """
        order = ['aria-label="Жанрлар"', 'Қазір не оқығың келеді?',
                 'Қысқа оқылатын', 'Аптаның кітабы', 'Белсенді байқау',
                 'Жаңа авторлар', 'Сенің әңгімең']
        positions = [self.html.index(marker) for marker in order]
        self.assertEqual(positions, sorted(positions), order)

    def test_the_four_rows_are_the_ones_the_editors_chose(self):
        """Жанровый скроллер убран (DEC-31) — осталась полоса-вывеска."""
        for present in ('Қазір не оқығың келеді?', 'Көп оқылған шығармалар',
                        'Қысқа оқылатын әңгімелер', 'Жалғасып жатқан шығармалар'):
            self.assertContains(self.response, present)
        for gone in ('Жанрлар бойынша', 'Жаңа шығармалар',
                     '10+ оқырманға', 'Жас авторлар'):
            self.assertNotContains(self.response, gone)

    def test_the_shelves_hold_what_they_promise(self):
        """Пустой ряд в первом фолде убивает всю раскладку: долгое время
        здесь лежало ровно одно произведение."""
        short = self.response.context['short_stories']
        serial = self.response.context['serial_stories']
        self.assertGreaterEqual(len(short), 4)
        self.assertTrue(all(s.is_single for s in short))
        self.assertTrue(serial)
        self.assertTrue(all(s.is_serial for s in serial))

    def test_a_row_offers_a_way_out_without_swiping_it_whole(self):
        self.assertContains(self.response, 'барлығы →')
        self.assertNotContains(self.response, 'hidden lg:inline')
        # Длительность живёт на обложке, а не внутри обрезаемого заголовка.
        self.assertContains(self.response, 'мин')
        self.assertContains(self.response, 'бөлім')


class TheGenreStripIsASignNotNavigation(TestCase):
    """Двенадцать цветных слов за пару секунд объясняют, что это
    литературный портал. Чип ведёт на страницу жанра, а не переключает
    состояние внутри главной (DEC-31)."""

    def setUp(self):
        self.html = self.client.get(reverse('core:home')).content.decode()

    def test_all_twelve_lead_straight_to_their_page(self):
        for genre in data.all_genres():
            with self.subTest(genre=genre.slug):
                self.assertIn(f'/genres/{genre.slug}/', self.html)
        self.assertNotIn('?genre=', self.html)
        self.assertNotIn('id="zhanrlar"', self.html)

    def test_no_chip_leads_into_emptiness(self):
        """Подросток тапает жанр и упирается в заглушку — тупик."""
        for genre in data.all_genres():
            with self.subTest(genre=genre.slug):
                self.assertTrue(data.filter_catalog(genre=genre.slug))

    def test_an_old_genre_query_no_longer_changes_the_page(self):
        response = self.client.get(reverse('core:home') + '?genre=triller')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('active_genre', response.context)


class RailContentSurvivesOnAPhone(TestCase):
    """Правый рейл скрыт до xl. Всё, что в нём живёт, обязано иметь дубль
    в потоке — и ровно один: два одинаковых блока на десктопе читаются как
    сбой вёрстки."""

    def setUp(self):
        self.response = self.client.get(reverse('core:home'))
        self.html = self.response.content.decode()

    def test_the_contest_appears_in_the_flow_and_hides_on_desktop(self):
        contest = self.response.context['hero_contest']
        self.assertEqual(self.html.count('Белсенді байқау'), 2)   # поток + рейл
        self.assertContains(self.response, f'{contest.days_left} күн')
        # Разряды через неразрывный пробел, а не «500000» сплошняком.
        self.assertContains(self.response, f'{spaced(contest.prize_kzt)} ₸')
        self.assertIsNotNone(re.search(
            r'<div class="xl:hidden">\s*<a[^>]*>[\s\S]*?Белсенді байқау', self.html))

    def test_both_tag_showcases_reach_the_flow(self):
        """Теги — единственная ось, обновляющаяся без редакции (DEC-31),
        поэтому накопленной популярности мало: нужен срез недели, и списки
        обязаны различаться."""
        trending = self.response.context['trending_tags']
        popular = self.response.context['popular_tags']
        self.assertTrue(trending and popular)
        self.assertTrue(all(t.status == 'accepted' for t in trending))
        self.assertTrue(all(t.weekly_count > 0 for t in trending))
        self.assertNotEqual([t.slug for t in trending],
                            [t.slug for t in popular[:len(trending)]])
        self.assertEqual(self.html.count('Осы аптада'), 2)
        self.assertGreaterEqual(self.html.count(f'#</span>{popular[0].name}'), 2)

    def test_the_tag_block_sits_inside_its_own_xl_hidden_wrapper(self):
        """Якорь — eyebrow секции, а не «Танымал тегтер»: между началом
        блока и накопленными тегами стоит недельный срез."""
        idx = self.html.index('қызығушылық бойынша')
        wrapper = self.html.rindex('<div class="xl:hidden">', 0, idx)
        self.assertLess(idx - wrapper, 800)

    def test_school_links_are_not_duplicated_into_the_flow(self):
        """Три вхождения — заголовок виджета в рейле плюс заголовок и
        aria-label списка в подвале. Четвёртое означало бы новый блок."""
        self.assertEqual(self.html.count('Авторлар мектебі'), 3)


class TheContestsSectionIsAnOverview(TestCase):
    """Обзор нескольких конкурсов, а не только ближайшего по дедлайну —
    того показывает баннер рядом. Карточка ведёт прямо на страницу
    конкурса: отдельной сущности под конкурс нет (DEC-50)."""

    def test_open_first_capped_and_linked_to_their_pages(self):
        response = self.client.get(reverse('core:home'))
        html = response.content.decode()
        contests = response.context['home_contests']

        self.assertContains(response, 'Байқаулар')
        self.assertTrue(contests)
        self.assertLessEqual(len(contests), 4)

        finished_seen = False
        for contest in contests:
            with self.subTest(contest=contest.slug):
                self.assertIn(reverse('core:contest_detail', args=[contest.slug]), html)
                if contest.is_finished:
                    finished_seen = True
                else:
                    self.assertFalse(
                        finished_seen,
                        'завершённый конкурс встретился раньше открытого')


class EditorialBlocksAreWiredUp(TestCase):
    """«Книга недели» и «Новые авторы» были написаны, но не подключены."""

    def setUp(self):
        self.response = self.client.get(reverse('core:home'))
        self.html = self.response.content.decode()

    def test_the_book_of_the_week_names_its_story_and_its_genre(self):
        story = self.response.context['book_of_week'].story
        self.assertContains(self.response, 'Аптаның кітабы')
        self.assertContains(self.response, f'«{story.title}»')
        # `genre_chip` по документации ведёт на /genres/<slug>/, а отдавал '#'.
        self.assertContains(self.response, reverse(
            'core:genre_detail', kwargs={'slug': story.primary_genre.slug}))

    def test_new_authors_are_the_least_followed_ones(self):
        """Социальное доказательство: подросток должен видеть, что здесь
        пишут такие же начинающие. Проверяется свойство, а не ники —
        числа подписчиков считаются по строкам `Follow`, и правка графа
        в корпусе меняла бы литерал."""
        shown = self.response.context['new_authors']
        counts = [a.followers for a in shown]
        self.assertEqual(counts, sorted(counts))
        most_followed = max(data.all_authors(), key=lambda a: a.followers)
        self.assertNotIn(most_followed.username, [a.username for a in shown])
        # Отдельного списка авторов в проекте нет — href="#" был бы тупиком.
        self.assertNotContains(self.response, 'барлық авторлар')


class GuestHeaderAndBottomNav(TestCase):
    """Нижнее меню — единственная постоянная навигация на телефоне, поэтому
    слоты проверяются явно (docs/07 §7.6). Самый заметный слот не должен
    требовать регистрации до получения ценности."""

    def _nav(self, html):
        start = html.index('aria-label="Мобильді мәзір"')
        return html[start:html.index('</nav>', start)]

    def test_a_guest_sees_the_way_in_but_no_private_items(self):
        response = self.client.get(reverse('core:home'))
        self.assertContains(response, 'Кіру')
        self.assertNotContains(response, 'Шығу')
        self.assertNotContains(response, 'Менің заявкаларым')
        self.assertNotContains(response, 'Менің шығармаларым')
        self.assertNotContains(response, 'Жалғастыру')
        self.assertContains(response, reverse('core:catalog'))

    def test_the_guest_fab_is_search_and_the_slots_are_labelled(self):
        html = self.client.get(reverse('core:home')).content.decode()
        nav = self._nav(html)
        fab = html[html.index('bg-brand text-white shadow-tg-btn') - 400:]
        self.assertIn('aria-label="Іздеу"', fab)
        self.assertNotIn('aria-label="Кіру"', html)
        self.assertEqual(nav.count('aria-label="Іздеу"'), 1)
        for label in ('Басты', 'Оқу', 'Байқау', 'Кіру'):
            with self.subTest(label=label):
                self.assertIn(f'>{label}</span>', nav)
        # Конкурсы помечены трофеем, как в шапке, а не «ползунками».
        self.assertIn('#icon-trophy', nav)
        self.assertNotIn('#icon-adjustments', nav)

    def test_an_author_gets_a_write_fab_and_their_own_slots(self):
        login_as(self.client)
        nav = self._nav(self.client.get(reverse('core:home')).content.decode())
        self.assertIn('aria-label="Жаңа шығарма"', nav)
        for label in ('Басты', 'Кітапхана', 'Байқау', 'Профиль'):
            with self.subTest(label=label):
                self.assertIn(f'>{label}</span>', nav)

    def test_the_header_and_footer_carry_the_site_map(self):
        """DEC-25: единственная контент-ссылка в шапке — «Байқаулар»,
        остальные разделы живут в подвале."""
        response = self.client.get(reverse('core:home'))
        self.assertContains(response, reverse('core:contest_list'))
        self.assertContains(response, 'Байқаулар')
        self.assertContains(response, reverse('core:genre_index'))
        self.assertContains(response, 'Жанрлар')
        self.assertContains(response, reverse('core:collections'))
        self.assertContains(response, 'Жинақтар')
        self.assertEqual(self.client.get(reverse('core:contest_list')).status_code, 200)


class GuestCtaKeepsTheIntent(TestCase):
    """Гостевые CTA расходились: hero вёл на signup, become_author — на login.
    Форма signup — профиль уже вошедшего; вход только через Telegram."""

    def test_both_lead_to_login_and_come_back_where_promised(self):
        response = self.client.get(reverse('core:home'))
        self.assertNotContains(response, reverse('core:signup'))
        self.assertContains(response, reverse('core:login'))

        target = reverse('core:new_story')
        self.assertContains(response, f"{reverse('core:login')}?next={target}")
        self.assertRedirects(
            self.client.post(f"{reverse('core:login')}?next={target}"), target)


class ReturningHomeAsksWhatYouWereDoing(TestCase):
    """У вошедшего свой hero: он продолжает то, что начал. Фокус выбирается
    по данным — начатая работа важнее начатого чтения, потому что дописать
    её больше некому."""

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:home'))

    def test_writing_is_primary_when_there_is_an_unfinished_work(self):
        # DEC-37: одночастевая «aidana-koshe» больше не «жазылып жатыр» —
        # незакончен теперь сериал, он и есть активная работа.
        active = self.response.context['active_work']
        self.assertEqual(self.response.context['hero_focus'], 'writing')
        self.assertContains(self.response, 'Мәтінің күтіп тұр')
        self.assertContains(self.response, 'Жазуды жалғастыру')
        self.assertContains(self.response, reverse(
            'core:manage_story', kwargs={'slug': active.slug}))
        self.assertNotContains(self.response, 'Бүгін не оқимыз?')
        self.assertContains(self.response, 'Шығу')
        self.assertContains(self.response, 'Хабарламалар')

    def test_reading_progress_stays_visible_on_a_phone(self):
        """Правый рейл скрыт до xl — иначе пишущий автор теряет
        «продолжить чтение» на телефоне целиком."""
        html = self.response.content.decode()
        self.assertIsNotNone(self.response.context['progress'])
        self.assertContains(self.response, 'Оқуды жалғастыру')
        self.assertIn('xl:hidden', html)
        self.assertEqual(html.count('Оқу үстінде'), 2)   # поток + рейл

    def test_the_three_demo_states_each_offer_their_own_next_step(self):
        """`?hero_state=` — витрина для дизайн-обзора: у настоящего
        читателя эти состояния достигаются данными, а не параметром."""
        cases = {
            'empty':   ('Бүгін неден бастаймыз?', 'Жаңа шығарма'),
            'reading': ('Оқуды жалғастыру', 'Жазып көру'),
            'writing': ('Мәтінің күтіп тұр', 'Оқуға шығарма табу'),
        }
        for state, (primary, secondary) in cases.items():
            with self.subTest(state=state):
                response = self.client.get(f"{reverse('core:home')}?hero_state={state}")
                self.assertEqual(response.context['hero_focus'], state)
                self.assertContains(response, primary)
                self.assertContains(response, secondary)
        self.assertIsNone(
            self.client.get(f"{reverse('core:home')}?hero_state=reading")
            .context['active_work'])
