"""CONT — страницы раздела: список, карточка, участники, афиша.

Конкурс показывается одинаково всюду, где показывается: подпись фазы,
строка сроков и условия собираются одними и теми же функциями, а не
переписываются под каждый экран. Расхождение здесь означало бы, что на
списке и на карточке один конкурс закрывается в разные дни.

Афиша — своя картинка конкурса, и она не обязана быть: без неё карточка
рисует то же, что с ней, только без картинки.
"""


import re
from unittest import mock

from django.urls import reverse

from core import data
from core.templatetags.qazaqnovel import short_date
from core.models import Contest, Story
from core.tests.base import TEMPLATES, TestCase, login_as


# ───────────────────────────────────────────────────────────────────────
# Страницы раздела
# ───────────────────────────────────────────────────────────────────────

class ContestList(TestCase):

    def test_it_shows_both_sections_and_every_open_card_in_order(self):
        response = self.client.get(reverse('core:contest_list'))
        self.assertEqual(response.status_code, 200)
        for word in ('Байқаулар', 'Ағымдағы', 'Аяқталған'):
            with self.subTest(word=word):
                self.assertContains(response, word)
        html = response.content.decode()
        # Приём открыт — значит, выше: список отсортирован по тому, что
        # читатель может сделать прямо сейчас.
        self.assertTrue(data.open_contests()[0].is_accepting)
        positions = []
        for contest in data.open_contests():
            with self.subTest(slug=contest.slug):
                self.assertContains(response, contest.name)
                self.assertContains(response, reverse(
                    'core:contest_detail', kwargs={'slug': contest.slug}))
            positions.append(html.index(contest.name))
        self.assertEqual(positions, sorted(positions))

    def test_a_finished_card_names_its_winners_and_an_open_one_does_not(self):
        response = self.client.get(reverse('core:contest_list'))
        for story in data.contest_by_slug('zhas-aldym-2023').winner_stories:
            with self.subTest(story=story.slug):
                self.assertContains(response, story.title)
        self.assertEqual(response.content.decode().count('Жеңімпаз:'), 1)

    def test_my_submissions_is_offered_only_to_the_signed_in(self):
        self.assertNotContains(self.client.get(reverse('core:contest_list')),
                               reverse('core:my_submissions'))
        login_as(self.client)
        self.assertContains(self.client.get(reverse('core:contest_list')),
                            reverse('core:my_submissions'))

    def test_an_empty_list_still_speaks_kazakh(self):
        """Ветка, которая не рендерится, всё равно должна говорить по-казахски:
        пустое состояние говорило «Әзірге конкурс жоқ» и пережило чистку
        только потому, что конкурсы в корпусе есть всегда."""
        # Патчится фасад: view читает `core.data`, и подмена в модуле
        # запросов до него уже не доходит.
        with mock.patch.object(data, 'open_contests', lambda: []), \
             mock.patch.object(data, 'finished_contests', lambda: []):
            html = self.client.get(reverse('core:contest_list')).content.decode()
        self.assertNotIn('онкурс', html)
        self.assertIn('Әзірге байқау жоқ', html)


class ContestDetail(TestCase):

    SLUG = 'bolashak-mektebi'

    def test_it_names_the_contest_its_conditions_and_its_jury(self):
        contest = data.contest_by_slug(self.SLUG)
        response = self.client.get(
            reverse('core:contest_detail', kwargs={'slug': self.SLUG}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, contest.name)
        self.assertContains(response, contest.subtitle)
        # Призовой фонд в ₸ — с разрядами через неразрывный пробел
        # (фильтр `spaced`); `stringformat:"d"` печатал «500000» сплошняком.
        self.assertEqual(contest.prize_kzt, 500_000)
        self.assertContains(response, data.spaced_number(contest.prize_kzt))
        self.assertContains(response, '₸')
        for word in ('Республикалық', 'Шарттар', 'Кезеңдер', 'Қазір'):
            with self.subTest(word=word):
                self.assertContains(response, word)
        for member in contest.jury:
            with self.subTest(name=member.name):
                self.assertContains(response, member.name)
                self.assertContains(response, member.role)

    def test_the_hero_speaks_by_phase(self):
        cases = {
            'bolashak-mektebi': None,                    # accepting → кнопка
            'qys-ertegisi': 'opens_on',                  # upcoming
            'altyn-qalam': 'results_on',                 # judging
            'zhas-aldym-2023': None,                     # finished
        }
        for slug, field in cases.items():
            contest = data.contest_by_slug(slug)
            response = self.client.get(
                reverse('core:contest_detail', args=[slug]))
            submit = reverse('core:contest_submit', args=[slug])
            with self.subTest(slug=slug, phase=contest.phase):
                if contest.is_accepting:
                    self.assertContains(response, submit)
                    self.assertContains(response, f'{contest.days_left} күн қалды')
                else:
                    self.assertNotContains(response, submit)
                if field:
                    self.assertContains(response,
                                        short_date(getattr(contest, field)))

    def test_an_unknown_slug_is_not_a_page(self):
        """404, а не 200 с карточкой внутри: страницы такого конкурса нет,
        и делиться с неё нечем."""
        response = self.client.get(
            reverse('core:contest_detail', kwargs={'slug': 'ghost'}))
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, 'Бөлісу', status_code=404)

    def test_every_phase_can_be_shared(self):
        """FR-CONT-12: конкурс живёт тем, что о нём рассказывают."""
        for contest in data.all_contests():
            with self.subTest(contest=contest.slug):
                self.assertContains(
                    self.client.get(reverse('core:contest_detail',
                                            args=[contest.slug])),
                    'Бөлісу')

    def test_the_section_never_says_konkurs(self):
        """Одна сущность — одно слово: в интерфейсе «байқау», не «конкурс».

        Шапка, нижнее меню, футер и баннер главной всегда говорили
        «Байқаулар», а сам раздел называл себя «Конкурстар» — в h1, во всех
        хлебных крошках, в кнопках и в пустом состоянии.
        """
        urls = ('/contests/', '/contests/bolashak-mektebi/',
                '/contests/zhas-aldym-2023/',
                '/contests/bolashak-mektebi/submit/',
                '/contests/my-submissions/', '/contests/unknown-slug/')
        for signed_in in (False, True):
            if signed_in:
                login_as(self.client)
            for url in urls:
                with self.subTest(url=url, signed_in=signed_in):
                    self.assertNotIn(
                        'онкурс', self.client.get(url).content.decode())


class ContestRail(TestCase):
    """Правый рейл конкурса: не копия страницы и не пустая колонка (DEC-25)."""

    def test_the_rail_appears_only_when_it_has_something_to_say(self):
        # Неизвестного конкурса больше нет как страницы — рейлу не на чем
        # появиться: 404 (FR-CONT-14).
        for url in ('/contests/unknown-slug/', '/contests/unknown-slug/submit/'):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        # У «Жас алдым — 2023» все этапы позади: рейлу нечего сказать.
        self.assertFalse(self.client.get(reverse(
            'core:contest_detail', args=['zhas-aldym-2023'])
        ).context['has_right_rail'])

    def test_the_active_rail_names_the_next_stage_and_repeats_no_prize(self):
        response = self.client.get(
            reverse('core:contest_detail', args=['bolashak-mektebi']))
        self.assertTrue(response.context['has_right_rail'])
        html = response.content.decode()
        self.assertIn('Қазылар қарауы', html)   # следующий этап — только в рейле
        # Сыйақы написан в хиро; вторая копия в рейле — дубль, не дополнение.
        self.assertEqual(html.count(data.spaced_number(500_000)), 1)

    def test_the_submit_page_rail_has_no_cta_to_itself(self):
        login_as(self.client)
        target = reverse('core:contest_submit', args=['bolashak-mektebi'])
        response = self.client.get(target)
        self.assertTrue(response.context['hide_submit_cta'])
        # Ссылка на подачу остаётся ровно одна — action самой формы.
        self.assertEqual(response.content.decode().count(f'"{target}"'), 1)


class WinnersAndNominationsOnDetail(TestCase):
    """FR-CONT-08. `winner_stories` существовал и не был отрендерен нигде."""

    def test_the_winners_section_names_every_winner_and_links_out(self):
        contest = data.contest_by_slug('zhas-aldym-2023')
        response = self.client.get(
            reverse('core:contest_detail', args=[contest.slug]))
        # Именно заголовок секции: «Жеңімпаздар» — ещё и подпись последнего
        # этапа в таймлайне активного конкурса, по голому слову не отличить.
        self.assertContains(response, '>Жеңімпаздар</h2>')
        # Итоги известны — таймлайн свёрнут.
        self.assertContains(response, '<summary')
        for story in contest.winner_stories:
            with self.subTest(story=story.slug):
                self.assertContains(response, story.title)
                self.assertContains(response, reverse('core:story_detail',
                                                      args=[story.slug]))
                self.assertContains(response, reverse(
                    'core:profile_other', args=[story.author.username]))
        for grant in contest.grants:
            with self.subTest(award=grant.award.slug):
                self.assertContains(response, grant.award.title)
                if grant.award.image:
                    self.assertContains(response,
                                        f'/media/{grant.award.image.name}')

    def test_nominations_are_shown_before_the_results_and_not_after(self):
        open_ = self.client.get(
            reverse('core:contest_detail', args=['bolashak-mektebi']))
        self.assertContains(open_, 'Марапаттар')
        self.assertContains(open_, 'Бас жүлде')
        self.assertEqual(open_.context['grants'], [])
        self.assertNotContains(open_, '>Жеңімпаздар</h2>')
        # У завершённого номинации уже перечислены победителями.
        self.assertNotContains(
            self.client.get(reverse('core:contest_detail',
                                    args=['zhas-aldym-2023'])),
            'Марапаттар')


class ContestParticipants(TestCase):
    """Список участников после описания — все допущенные работы, не только
    победители (BR-74a). Это и есть чтение байқауды как коллекции
    произведений, без отдельной сущности Collection под конкурс.
    """

    def test_a_finished_contest_lists_the_accepted_work_but_not_the_refused(self):
        response = self.client.get(
            reverse('core:contest_detail', args=['zhas-aldym-2023']))
        self.assertContains(response, 'Қатысушылар')
        for slug in ('temniy-lord', 'igra-kuklovoda'):
            with self.subTest(story=slug):
                self.assertContains(response, Story.objects.get(slug=slug).title)
        # aidana подавала «aidana-kysh» на этот же конкурс, и её отклонили —
        # BR-74a запрещает публично показывать отказ.
        self.assertNotContains(response,
                               Story.objects.get(slug='aidana-kysh').title)

    def test_participation_does_not_wait_for_the_results(self):
        """«Жас алдым — 2026» — идущий конкурс с реальными участниками:
        приём открыт, победители ещё не названы, но принятые работы уже
        видны (FR-CONT-16)."""
        contest = data.contest_by_slug('zhas-aldym-2026')
        self.assertTrue(contest.is_accepting)
        response = self.client.get(
            reverse('core:contest_detail', args=[contest.slug]))
        for slug in ('kunnin-songy-sagaty', 'atam-aityp-berdi'):
            with self.subTest(story=slug):
                self.assertContains(response, Story.objects.get(slug=slug).title)
        for participant in response.context['participants']:
            with self.subTest(story=participant['story'].slug):
                self.assertEqual(participant['result'], 'accepted')
        self.assertEqual(contest.winners, ())

    def test_a_contest_without_accepted_work_shows_an_empty_state(self):
        response = self.client.get(
            reverse('core:contest_detail', args=['altyn-qalam']))
        self.assertEqual(response.context['participants'], [])
        self.assertContains(response, 'Әзірге қатысушы жоқ')


class ContestPosterIsItsOwn(TestCase):
    """Афиша конкурса — своя, а не фотография чужой книги (FR-CONT-11).

    В `static/img/bookN.jpg` лежат книжные обложки; четыре конкурса
    различались тем, чья книга досталась каждому.
    """

    def test_no_template_pulls_a_static_book_photo(self):
        for name in ('components/contest_card.html',
                     'pages/contests/contest_detail.html'):
            with self.subTest(template=name):
                body = (TEMPLATES / name).read_text(encoding='utf-8')
                self.assertNotIn('img/book', body)
                self.assertNotIn('contest.cover', body)
        fields = {f.name for f in Contest._meta.get_fields()}
        self.assertNotIn('cover', fields)
        self.assertIn('poster', fields)

    def test_the_poster_renders_and_uploaded_files_live_in_media(self):
        for url in ('/contests/', '/contests/bolashak-mektebi/'):
            with self.subTest(url=url):
                self.assertIn('oklch(', self.client.get(url).content.decode(),
                              'типографическая афиша не отрендерилась')
        # Афишу грузит админ в MEDIA_ROOT, как эмблему награды (BR-46).
        for contest in data.all_contests():
            if contest.poster:
                with self.subTest(contest=contest.slug):
                    self.assertTrue(contest.poster.name.startswith('contests/'))
                    self.assertFalse(contest.poster.name.endswith('.svg'))


class PosterStripHasAWidthBudget(TestCase):
    """Пилюли на афише карточки не наезжают друг на друга.

    Бейдж фазы с отсчётом занимают ~264px, пилюля приза — 78px, а полоса
    трёхколоночной карточки даёт 252px. Пока это были две абсолютные
    группы в противоположных углах (`left-3 top-3` и `right-3 top-3`),
    ширину не считал никто: при двух колонках они перекрывались на 8px,
    при трёх — на 90.

    Геометрию тест проверить не может — только правило, из которого она
    следует: одна полоса с распоркой вместо двух углов, и ряд статуса
    переносится.
    """

    @staticmethod
    def _markup(path):
        """Шаблон без `{% comment %}`-блоков.

        Объяснение в комментарии называет ту самую пару классов, которую
        правило запрещает, — иначе тест ловил бы собственную документацию.
        """
        return re.sub(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', '',
                      path.read_text(encoding='utf-8'), flags=re.S)

    def test_the_card_uses_one_strip_not_two_corners(self):
        body = self._markup(TEMPLATES / 'components' / 'contest_card.html')
        self.assertIn('inset-x-3', body)
        for corner in ('left-3 top-3', 'right-3 top-3'):
            with self.subTest(corner=corner):
                self.assertNotIn(corner, body,
                                 'абсолютный угол вернулся — соседняя пилюля '
                                 'снова окажется под ним')

    def test_the_status_row_wraps(self):
        body = self._markup(TEMPLATES / 'components' / 'contest_status.html')
        self.assertIn('flex-wrap', body,
                      'без переноса отсчёт не помещается в полосу узкой карточки')


class CountdownIconMeansTime(TestCase):
    """Иконка отсчёта — часы, а не ползунки фильтра.

    `adjustments` стояла перед «12 күн қалды» потому, что часов в спрайте
    не было, а добавить `<symbol>` было лень. Иконка, взятая по наличию,
    не значит ничего — CLAUDE.md и docs/ui.md запрещают ровно это.
    """

    def test_the_countdown_wears_the_clock_and_adjustments_stays_on_the_filter(self):
        countdown = (TEMPLATES / 'components' / 'countdown.html'
                     ).read_text(encoding='utf-8')
        self.assertIn('name="clock"', countdown)
        self.assertNotIn('name="adjustments"', countdown)
        sprite = (TEMPLATES / 'components' / 'icons' / '_sprite.html'
                  ).read_text(encoding='utf-8')
        self.assertIn('id="icon-clock"', sprite)
        # У кнопки сүзгі каталога ползунки — на своём месте.
        catalog = (TEMPLATES / 'pages' / 'catalog' / 'catalog.html'
                   ).read_text(encoding='utf-8')
        self.assertIn('name="adjustments"', catalog)
