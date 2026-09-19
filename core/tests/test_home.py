"""Главная: порядок фолдов, редакционные блоки, режимы гостя и вошедшего.

Главная — единственная страница, где проверяется **порядок**, а не только
наличие: подросток заходит с телефона, и если первый экран занят поиском,
ценность портала не считывается. Поэтому здесь много `assertLess` по
индексам в разметке — это не хрупкость, а само требование (DEC-31).

Один запрос на класс, а не на утверждение: сценарий «гость открыл
главную» один, и вопросов к нему полтора десятка.
"""

import re
from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core import data
from core.templatetags.qazaqnovel import (
    reading_meta,
    short_date,
    spaced,
    start_label,
    update_meta,
)
from core.tests import factories
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

    def test_new_authors_are_the_ones_who_joined_last(self):
        """Социальное доказательство: подросток должен видеть, что здесь
        пишут такие же начинающие.

        По дате прихода, а не по числу подписчиков (DEC-57): мало
        подписчиков бывает и у того, кто пишет второй год, и ряд звал бы
        читать его как новичка. Проверяется свойство, а не ники — правка
        корпуса не должна ломать тест.
        """
        shown = self.response.context['new_authors']
        joined = [a.date_joined for a in shown]
        self.assertEqual(joined, sorted(joined, reverse=True))
        oldest = min(data.all_authors(), key=lambda a: a.date_joined)
        self.assertNotIn(oldest.username, [a.username for a in shown])
        # Отдельного списка авторов в проекте нет — href="#" был бы тупиком.
        self.assertNotContains(self.response, 'барлық авторлар')

    def test_an_empty_profile_does_not_displace_one_with_a_story(self):
        """DEC-89: карточка аккаунта без работ показывала «0 шығарма ·
        0 жазылушы» — социальное доказательство, доказывающее обратное.
        Пришедший последним, но ничего не опубликовавший, уступает место
        тому, у кого есть что читать.
        """
        now = timezone.now()
        writer = factories.user(username='jazushy', date_joined=now)
        factories.story(author=writer)
        newcomer = factories.user(username='bosprofil',
                                  date_joined=now + timedelta(hours=1))

        shown = [a.username for a in data.new_authors(4)]
        self.assertEqual(shown[0], writer.username)
        self.assertNotIn(newcomer.username, shown)

    def test_the_empty_profile_is_sorted_last_not_filtered_out(self):
        """Это сортировка, а не фильтр: непустой ряд из DEC-57 остаётся.
        Когда заполненных профилей не хватает на `limit`, пустые добирают
        хвост — иначе в тихий месяц ряд на главной исчезал бы совсем.
        """
        newcomer = factories.user(username='bosprofil-2',
                                  date_joined=timezone.now() + timedelta(days=1))
        everyone = [a.username for a in data.new_authors(1000)]
        self.assertIn(newcomer.username, everyone)
        self.assertEqual(everyone[-1], newcomer.username)


class TwoRowsMustNotSayTheSameThing(TestCase):
    """«Көп оқылған» и «Жалғасып жатқан» стояли подряд и подписывались
    одинаково — автор и оқылым. Второй ряд отвечал вопросом первого:
    «сколько читали» он уже сказал, а «жив ли сериал» не говорил никто.
    """

    def test_a_serial_card_names_the_part_and_when_it_came_out(self):
        story = factories.story(author=factories.user(), chapters=3,
                                status='OnProcess')
        self.assertEqual(update_meta(story), '3-бөлім · жаңа ғана')

    def test_the_date_is_the_readers_one_not_the_rows_updated_at(self):
        """`updated_at` двигает любое сохранение строки — пересчёт статуса,
        решение модератора о соседней главе. Берётся дата, с которой часть
        стала видна читателю (BR-79).
        """
        story = factories.story(author=factories.user(), chapters=2)
        shown = story.last_published_at

        story.likes = 7
        story.save(update_fields=['likes', 'updated_at'])
        story.refresh_from_db()

        self.assertGreater(story.updated_at, shown)
        self.assertEqual(story.last_published_at, shown)

    def test_a_work_without_published_parts_has_no_date(self):
        """Черновик в этот ряд не попадает, но подпись обязана пережить
        его и не собраться из `None`."""
        story = factories.story(author=factories.user(), chapters=1,
                                published=False, status='Draft')
        self.assertIsNone(story.last_published_at)
        self.assertEqual(update_meta(story), '0-бөлім')

    def test_the_home_row_uses_it_and_the_popular_one_does_not(self):
        html = self.client.get(reverse('core:home')).content.decode()
        serial_row = html[html.index('Жалғасып жатқан шығармалар'):]
        popular_row = html[html.index('Көп оқылған шығармалар'):
                           html.index('Жалғасып жатқан шығармалар')]
        self.assertIn('-бөлім ·', serial_row)
        self.assertNotIn('-бөлім ·', popular_row)


class TheContestBannerGivesEnoughToDecide(TestCase):
    """«N күн қалды» не говорит, до какого числа — срок в днях нельзя
    записать в календарь; и не говорит, пусто там или туда все идут.
    """

    def setUp(self):
        super().setUp()
        self.contest = factories.contest(
            phase='accepting', prize_kzt=150_000,
            closes_on=timezone.localdate() + timedelta(days=3))

    def _banner(self):
        html = self.client.get(reverse('core:home')).content.decode()
        return html[html.index('Белсенді байқау'):html.index('Барлық байқаулар')]

    def test_it_names_the_closing_date_next_to_the_days_left(self):
        banner = self._banner()
        self.assertIn('3 күн', banner)
        self.assertIn(f'{short_date(self.contest.closes_on)} дейін', banner)

    def test_the_count_appears_only_once_someone_has_sent_something(self):
        """«0 жұмыс» в промо-блоке сообщает ровно обратное тому, зачем
        блок стоит, — та же беда, что у карточки автора с нулями (DEC-89).
        """
        self.assertNotIn('жұмыс жіберілді', self._banner())

        author = factories.user()
        data.create_submission(
            author, self.contest, factories.story(author=author, chapters=1),
            ai_declaration='none', age_confirmed=True, rules_confirmed=True)

        self.assertIn('1 жұмыс жіберілді', self._banner())

    def test_the_count_costs_no_extra_query(self):
        """Число приходит аннотацией той же выдачи (`with_counts`), а не
        походом за составом: баннеру состав не нужен."""
        contest = data.hero_contest()
        with self.assertNumQueries(0):
            contest.submission_count


class TheWeeklyPickSaysWhatOpens(TestCase):
    """«Оқуды бастау» честна для одночастной работы — открывается она
    сама. У сериала то же слово не говорило, куда попадёшь: к списку
    частей, к последней или к первой.
    """

    def test_a_serial_names_the_first_part(self):
        self.assertEqual(
            start_label(factories.story(author=factories.user(), chapters=4)),
            '1-бөлімді оқу')

    def test_a_single_work_keeps_the_plain_invitation(self):
        """Минут на кнопке нет намеренно: рядом стоит `reading_meta`, и
        «7 минут оқу» было бы дословным повтором строки над ней."""
        story = factories.story(author=factories.user(), chapters=1)
        self.assertEqual(start_label(story), 'Оқуды бастау')
        self.assertIn('минут оқу', reading_meta(story))

    def test_the_block_renders_the_label_of_its_own_pick(self):
        response = self.client.get(reverse('core:home'))
        self.assertContains(response,
                            start_label(response.context['book_of_week'].story))


class TheCardCarriesWhatTheReaderAlreadyDid(TestCase):
    """BR-96: закладка и прогресс прямо на карточке. На телефоне наведения
    нет, и действие, которое появляется только на hover, не существует.
    """

    def setUp(self):
        super().setUp()
        self.reader = factories.user(username='oqyrman')
        self.story = factories.story(author=factories.user(), chapters=4,
                                     status='OnProcess')

    def test_a_guest_gets_no_bookmark_at_all(self):
        """Полки у гостя нет, и кнопка, уводящая на вход, обещала бы не то,
        что делает."""
        html = self.client.get(reverse('core:home')).content.decode()
        self.assertNotIn('Кітапханаға сақтау', html)

    def _one_card(self):
        """Каталог, суженный до одной работы: на главной свежая работа
        может не попасть в первую пятёрку ряда, и тест проверял бы
        состав корпуса вместо кнопки."""
        url = f"{reverse('core:catalog')}?q={self.story.title}"
        return self.client.get(url).content.decode()

    def test_the_button_shows_the_state_it_will_change(self):
        login_as(self.client, self.reader.username)
        self.assertIn('Кітапханаға сақтау', self._one_card())

        data.toggle_library_entry(self.reader, self.story)
        self.assertIn('Кітапханадан алу', self._one_card())

    def test_saving_returns_where_it_was_pressed(self):
        """Без `next` сохранение с главной уносило читателя на страницу
        работы — кнопка «сохранить на потом» открывала это самое «потом».
        """
        login_as(self.client, self.reader.username)
        response = self.client.post(
            reverse('core:library_toggle', kwargs={'slug': self.story.slug}),
            {'next': reverse('core:home')})
        self.assertRedirects(response, reverse('core:home'))

    def test_the_open_redirect_door_stays_shut(self):
        login_as(self.client, self.reader.username)
        response = self.client.post(
            reverse('core:library_toggle', kwargs={'slug': self.story.slug}),
            {'next': '//evil.example/phish'})
        self.assertRedirects(response, reverse('core:home'))

    def test_progress_is_drawn_for_a_serial_and_never_for_a_single(self):
        """У одночастной работы `chapters` равна единице, и любая начатая
        превращалась бы в «100%»: запись о прогрессе там значит «открыл»,
        а не «дочитал».
        """
        single = factories.story(author=self.story.author, chapters=1)
        for story in (self.story, single):
            data.record_reading_progress(self.reader, story, 1,
                                         list(story.chapter_set.all()))

        shown = {s.slug: s for s in data.public_stories(viewer=self.reader)}
        self.assertEqual(shown[self.story.slug].read_up_to, 1)
        self.assertEqual(shown[self.story.slug].viewer_progress_pct, 25)
        self.assertEqual(shown[single.slug].viewer_progress_pct, 0)

    def test_marks_are_set_for_a_guest_too_rather_than_left_off(self):
        """Незаданная метка читается как «не сохранено» — ответ не
        «неизвестно», а неверный. Поэтому `for_viewer(None)` проставляет
        её значениями, и промах остаётся видимым (`viewer_mark`).
        """
        story = data.public_stories(viewer=None).get(slug=self.story.slug)
        self.assertFalse(story.viewer_saved)
        self.assertEqual(story.viewer_chapter, 0)


class GuestHeaderAndBottomNav(TestCase):
    """Нижнее меню — единственная постоянная навигация на телефоне, поэтому
    слоты проверяются явно (docs/ui.md). Самый заметный слот не должен
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

    def test_the_guest_fab_is_write_and_the_slots_are_labelled(self):
        """DEC-88: в центре «Жазу», а не поиск. Поиск у гостя был доступен
        ещё из двух мест первого экрана (иконка в шапке и поле в hero), а
        намерения писать не было видно ниоткуда. Барьер входа остаётся, но
        `next` ведёт человека в редактор сразу после входа."""
        html = self.client.get(reverse('core:home')).content.decode()
        nav = self._nav(html)
        self.assertIn('aria-label="Шығарма жазу"', nav)
        self.assertNotIn('aria-label="Кіру"', html)
        # Поиск ушёл из меню целиком — в шапке и hero он остался.
        self.assertNotIn('aria-label="Іздеу"', nav)
        self.assertIn(f"{reverse('core:login')}?next={reverse('core:new_story')}", nav)
        for label in ('Басты', 'Оқу', 'Байқау', 'Кіру'):
            with self.subTest(label=label):
                self.assertIn(f'>{label}</span>', nav)
        # Конкурсы помечены трофеем, как в шапке, а не «ползунками».
        self.assertIn('#icon-trophy', nav)
        self.assertNotIn('#icon-adjustments', nav)

    def test_search_stays_reachable_without_the_fab(self):
        """Слот отдан письму, но поиск не должен исчезнуть с экрана:
        иконка в шапке сквозная, поле в hero объясняет, что искать."""
        html = self.client.get(reverse('core:home')).content.decode()
        header = html[html.index('<header'):html.index('</header>')]
        self.assertIn('aria-label="Іздеу"', header)
        self.assertIn('Шығарма, автор, жанр немесе тег', html)

    def test_an_author_gets_a_write_fab_and_their_own_slots(self):
        login_as(self.client)
        nav = self._nav(self.client.get(reverse('core:home')).content.decode())
        self.assertIn('aria-label="Жаңа шығарма"', nav)
        for label in ('Басты', 'Кітапхана', 'Байқау', 'Профиль'):
            with self.subTest(label=label):
                self.assertIn(f'>{label}</span>', nav)

    def test_the_footer_accordion_is_open_in_the_markup(self):
        """DEC-90: сворачивает группы Alpine при инициализации, а разметка
        приходит раскрытой. Обратный порядок (`hidden` в HTML, скрипт
        снимает) без JS прятал бы карту сайта навсегда — а footer и есть
        единственная карта сайта после DEC-25.
        """
        html = self.client.get(reverse('core:home')).content.decode()
        footer = html[html.index('<footer'):]
        self.assertIn("{ 'hidden': !open }", footer)
        self.assertNotIn('hidden sm:!block', footer)
        self.assertNotIn('hidden sm:!flex', footer)

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
    Вход и регистрация — одна и та же дверь Telegram (DEC-83), отдельного
    signup-адреса больше нет вовсе."""

    def test_both_lead_to_login_with_next_preserved(self):
        """Что вход, придя из `?next=`, действительно возвращает туда —
        проверяет `test_auth.TelegramCallback` (там есть настоящий
        провайдер, которого форма демо-входа не знала)."""
        response = self.client.get(reverse('core:home'))
        self.assertContains(response, reverse('core:login'))

        target = reverse('core:new_story')
        self.assertContains(response, f"{reverse('core:login')}?next={target}")


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

    @override_settings(DEBUG=True)
    def test_the_three_demo_states_each_offer_their_own_next_step(self):
        """`?hero_state=` — витрина для дизайн-обзора: у настоящего
        читателя эти состояния достигаются данными, а не параметром.

        `DEBUG=True` здесь обязателен: параметр закрыт им (A5), иначе на
        живом сайте `?hero_state=empty` показывал бы вошедшему автору
        пустой экран «начни писать» поверх его же работ.
        """
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

    def test_the_demo_states_do_not_work_on_the_live_site(self):
        """Иначе посторонний параметр перерисовывает автору его главную."""
        response = self.client.get(f"{reverse('core:home')}?hero_state=empty")

        self.assertEqual(response.context['hero_focus'], 'writing')
