"""CONT — подача работы на конкурс и свои заявки.

Главное правило: **форма ничего не отклоняет** (BR-24). У кандидатов
бывают заметки — про объём, про занятость другим конкурсом, — но решение
принимает человек. Прежняя версия гасила радио и кнопку, то есть
отказывала от имени конкурса до всякого жюри.

Отклоняет только фаза: приём закрыт — подать нечего, и об этом сказано
до формы, а не после кнопки.
"""


import contextlib
from datetime import date
from unittest import mock

from django.test import Client
from django.urls import reverse

from core import data, views
from core.templatetags.qazaqnovel import ago, short_date
from core.models import Contest, Submission, User
from core.tests.base import TestCase, login_as, login_as_newcomer, user
# Помощники живут там, где живёт объект конкурса: подпись условий и
# срез заявок по авторам нужны обоим файлам, а дублировать их значило бы
# однажды поправить одну копию.
from core.tests.test_contests import _all_submissions, _eligibility


# ───────────────────────────────────────────────────────────────────────
# Подача работы: кандидаты, заметки, чек-лист
# ───────────────────────────────────────────────────────────────────────

class SubmissionHelpers(TestCase):

    def test_candidates_are_the_public_works_and_nothing_else(self):
        """Черновик и работа на модерации на конкурс не выставляются
        (DEC-23): их нельзя ни дать прочитать жюри, ни показать читателю
        рядом с победителями. Это единственное, что список сужает — всё
        остальное заметки, не запреты (BR-24)."""
        items = data.submission_candidates(user('aidana'), 'altyn-qalam')
        self.assertEqual([i['story'].slug for i in items],
                         [s.slug for s in data.public_stories_of(user('aidana'))])
        for item in items:
            with self.subTest(story=item['story'].slug):
                self.assertTrue(item['story'].is_public)
                self.assertEqual(set(item), {'story', 'chars', 'notes'})
                for note in item['notes']:
                    self.assertEqual(set(note), {'key', 'text'})
                    self.assertIn(note['key'], data.SUBMISSION_NOTES)
        self.assertEqual(data.submission_candidates(user('aidana'), 'no-such'), [])
        self.assertEqual(data.submission_candidates(user('ghost'), 'altyn-qalam'), [])

    def test_the_submission_lookup_answers_both_ways(self):
        self.assertEqual(len(data.submissions_of(user('aidana'))), 2)
        self.assertEqual(list(data.submissions_of(user('ghost'))), [])
        self.assertTrue(data.has_submission(user('aidana'), 'altyn-qalam'))
        self.assertFalse(data.has_submission(user('aidana'), 'bolashak-mektebi'))

    def test_the_checklist_marks_volume_and_demands_the_declaration(self):
        contest = data.contest_by_slug('altyn-qalam')
        # Кандидат на конкурс — работа автора, и берётся она авторской
        # дверью: `aidana-erteg` стоит на модерации, читателю её нет (BR-76).
        def mine(slug):
            return data.story_by_slug_for_author(slug, user('aidana'))

        for slug in ('aidana-koshe',   # 4 750 знаков — меньше порога
                     'aidana-kus'):    # ни одной главы — ноль знаков
            checklist = data.submission_checklist(mine(slug), contest)
            volume = next(i for i in checklist if i['key'] == 'volume')
            with self.subTest(story=slug):
                self.assertFalse(volume['passed'])
        self.assertIn('Көлемі тым аз',
                      next(i for i in data.submission_checklist(
                          mine('aidana-koshe'), contest)
                          if i['key'] == 'volume')['hint'])
        declaration = next(i for i in data.submission_checklist(
            mine('aidana-tan'), contest) if i['key'] == 'ai_decl')
        self.assertFalse(declaration['passed'])
        self.assertTrue(declaration.get('required'))

    def test_the_numbers_in_the_hint_are_spaced_and_come_from_the_contest(self):
        contest = data.contest_by_slug('altyn-qalam')
        story = data.story_by_slug('aidana-tan')
        volume = next(i for i in data.submission_checklist(story, contest)
                      if i['key'] == 'volume')
        self.assertIn(data.spaced_number(contest.min_chars), volume['label'])
        self.assertIn(data.spaced_number(contest.max_chars), volume['label'])
        total = sum(c.char_count for c in data.chapters_of(story.slug))
        self.assertIn(data.spaced_number(total), volume['hint'])
        self.assertNotIn(str(total), volume['hint'])


class SubmitFormShowsWhatCanBeSent(TestCase):

    OPEN = 'bolashak-mektebi'    # на этот aidana НЕ подавала
    DONE = 'altyn-qalam'         # а на этот подавала

    def test_a_guest_gets_a_gate_and_no_form(self):
        response = self.client.get(
            reverse('core:contest_submit', kwargs={'slug': self.OPEN}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'кір')
        self.assertNotContains(response, 'name="story_slug"')

    def test_the_form_offers_the_public_works_with_their_notes(self):
        login_as(self.client)
        response = self.client.get(
            reverse('core:contest_submit', kwargs={'slug': self.OPEN}))
        self.assertEqual(response.status_code, 200)
        for story in data.public_stories_of(user('aidana')):
            with self.subTest(slug=story.slug):
                self.assertContains(response, f'value="{story.slug}"')
        for story in data.my_stories_of(user('aidana')):
            if not story.is_public:
                with self.subTest(hidden=story.slug):
                    self.assertNotContains(response, f'value="{story.slug}"')
        # Работа короче порога получает заметку, но остаётся выбираемой.
        self.assertContains(response, data.SUBMISSION_NOTES['too_short'])
        self.assertContains(response, 'value="aidana-koshe"')

    def test_the_form_carries_the_checklist_the_declaration_and_the_consents(self):
        login_as(self.client)
        response = self.client.get(
            reverse('core:contest_submit', kwargs={'slug': self.OPEN}))
        for marker in ('Сәйкестік чек-листі', 'Тіл — қазақша', 'AI-декларация',
                       'name="ai_used"', 'value="no"', 'value="partial"',
                       'value="yes"', 'name="confirm_age"',
                       'name="confirm_rules"'):
            with self.subTest(marker=marker):
                self.assertContains(response, marker)

    def test_an_author_who_already_applied_is_told_so_instead(self):
        login_as(self.client)
        submit = self.client.get(
            reverse('core:contest_submit', kwargs={'slug': self.DONE}))
        self.assertContains(submit, 'Сен бұл байқауға өтінім бергенсің')
        self.assertNotContains(submit, 'name="story_slug"')
        self.assertContains(submit, reverse('core:my_submissions'))

        detail = self.client.get(
            reverse('core:contest_detail', kwargs={'slug': self.DONE}))
        self.assertContains(detail, 'Өтінім берілген')
        self.assertNotContains(
            detail, '>\n                        Қатысу\n                    </a>')

    def test_an_unknown_slug_is_not_a_page(self):
        login_as(self.client)
        self.assertEqual(
            self.client.get(reverse('core:contest_submit',
                                    kwargs={'slug': 'ghost'})).status_code, 404)


class SubmitIsGatedByPhase(TestCase):
    """Форма подачи живёт только в фазе приёма (DEC-45).

    Прямая ссылка открывалась в любой момент и предлагала подать работу в
    конкурс, который ещё не начался или уже ушёл на судейство.
    """

    # Голого `<form` мало: базовый шаблон несёт свои формы (поиск, жалоба).
    # Признак именно формы подачи — поле выбора произведения.
    FIELD = 'name="story_slug"'

    def setUp(self):
        super().setUp()
        # Не aidana: у неё уже есть заявка в «Алтын қалам», и страница
        # показала бы блок «өтінім бергенсің» раньше, чем блок фазы.
        login_as(self.client, 'bekzhan_t')

    def test_outside_the_acceptance_window_there_is_no_form(self):
        for slug, message in (('qys-ertegisi', 'Өтінім қабылдау әлі басталған жоқ'),
                              ('altyn-qalam', 'Өтінім қабылдау жабылды'),
                              ('zhas-aldym-2023', None)):
            response = self.client.get(
                reverse('core:contest_submit', args=[slug]))
            with self.subTest(slug=slug):
                self.assertNotContains(response, self.FIELD)
                if message:
                    self.assertContains(response, message)

    def test_while_it_accepts_the_form_is_there(self):
        self.assertContains(
            self.client.get(reverse('core:contest_submit',
                                    args=['bolashak-mektebi'])),
            self.FIELD)


class SubmissionNotesInformButDoNotBlock(TestCase):
    """Форма ничего не отклоняет — она сообщает (BR-24).

    Раньше работа короче порога или занятая другим конкурсом приходила с
    `disabled`, а кнопка отправки гасла: отказ от имени конкурса,
    вынесенный до жюри и без права возразить. Заметка осталась, запрет
    ушёл — её видит автор здесь и админ в заявке.
    """

    def _items(self, username, slug='bolashak-mektebi'):
        return {i['story'].slug: i
                for i in data.submission_candidates(user(username), slug)}

    @staticmethod
    def _keys(item):
        return {n['key'] for n in item['notes']}

    def test_a_short_work_and_a_busy_one_are_noted_not_removed(self):
        mine = self._items('aidana')
        short = mine['aidana-koshe']
        self.assertIn('too_short', self._keys(short))
        self.assertIn(data.SUBMISSION_NOTES['too_short'],
                      short['notes'][0]['text'])
        # Одним текстом идти в двух конкурсах — повод для разговора,
        # а не для молча закрытой двери (BR-23a).
        busy = mine['aidana-tan']
        self.assertIn('busy', self._keys(busy))
        self.assertIn('Алтын қалам',
                      next(n['text'] for n in busy['notes']
                           if n['key'] == 'busy'))
        # Чистая работа заметок не носит.
        self.assertEqual(self._items('bekzhan_t')['tunge-deiin']['notes'], [])

    def test_all_the_notes_are_named_not_just_the_first(self):
        """Прежняя цепочка `elif` называла одну причину и молчала об
        остальных: работа и короткая, и занятая другим конкурсом сообщала
        только про объём — второе всплывало бы уже у админа."""
        Contest.objects.filter(slug='bolashak-mektebi').update(min_chars=10_000)
        self.assertEqual(self._keys(self._items('aidana')['aidana-tan']),
                         {'too_short', 'busy'})

    def test_neither_a_finished_contest_nor_this_one_counts_as_busy(self):
        # Работа своё отучаствовала — заметки о ней больше нет.
        self.assertIsNone(data.busy_contest_of(user('bekzhan_t'), 'temniy-lord'))
        self.assertIsNone(data.busy_contest_of(user('aidana'), 'aidana-tan',
                                               besides='altyn-qalam'))

    def test_no_radio_is_disabled_and_every_note_stands_next_to_its_work(self):
        """Заметка стоит у работы, а не внизу формы: отдельный блок внизу
        объяснял, почему гаснет кнопка. Кнопка больше не гаснет, а заметка
        внизу относилась неизвестно к какой из работ."""
        login_as(self.client, 'rudazov')   # все работы короче порога
        html = self.client.get(
            reverse('core:contest_submit',
                    args=['bolashak-mektebi'])).content.decode()
        picker = html[html.index('name="story_slug"'):
                      html.index('Сәйкестік чек-листі')]
        self.assertNotIn('disabled', picker)
        self.assertIn('Өтінім беру', html)
        items = data.submission_candidates(user('rudazov'), 'bolashak-mektebi')
        self.assertTrue(any(i['notes'] for i in items),
                        'корпус потерял работы с заметками')
        for item in items:
            for note in item['notes']:
                with self.subTest(story=item['story'].slug, note=note['key']):
                    self.assertIn(note['text'], picker)


class ChecklistFollowsTheChoice(TestCase):
    """FR-CONT-04: чек-лист пересчитывается при смене работы, не застывает."""

    def test_the_view_ships_volume_data_for_every_candidate(self):
        login_as(self.client, 'bekzhan_t')
        response = self.client.get(
            reverse('core:contest_submit', args=['bolashak-mektebi']))
        volumes = response.context['volumes']
        candidates = {i['story'].slug for i in response.context['candidates']}
        self.assertEqual(set(volumes), candidates)
        for slug, volume in volumes.items():
            with self.subTest(story=slug):
                self.assertEqual(set(volume), {'passed', 'hint', 'title'})
        self.assertContains(response, 'id="submit-volumes"')
        self.assertContains(response, 'x-model="picked"')

    def test_the_initial_choice_is_a_work_without_notes(self):
        """Отклонять форма ничего не отклоняет, но начинать выбор с работы,
        о которой есть что сказать, незачем."""
        login_as(self.client, 'bekzhan_t')
        response = self.client.get(
            reverse('core:contest_submit', args=['bolashak-mektebi']))
        slug = response.context['initial_slug']
        item = next(i for i in response.context['candidates']
                    if i['story'].slug == slug)
        self.assertEqual(item['notes'], [])

    def test_it_survives_when_no_work_fits(self):
        """Раньше при отсутствии подходящей работы исчезали AI-декларация и
        оба согласия: чек-лист считался только для подходящей, а форма без
        него выглядела обрубленной."""
        login_as(self.client, 'rudazov')   # все работы короче порога
        response = self.client.get(
            reverse('core:contest_submit', args=['bolashak-mektebi']))
        self.assertTrue(all(i['notes'] for i in response.context['candidates']))
        for marker in ('Сәйкестік чек-листі', 'name="ai_used"',
                       'name="confirm_age"', 'name="confirm_rules"',
                       'Өтінім беру'):
            with self.subTest(marker=marker):
                self.assertContains(response, marker)


class WorkPickerScalesToManyWorks(TestCase):
    """Поиск по своим работам — только когда список длинный.

    У автора с тремя работами поле над ними отнимает строку и не решает
    ничего: список виден целиком. У автора с сорока выбор превращается в
    прокрутку, и нужная работа может быть сороковой.
    """

    @staticmethod
    def _picker(html):
        """Только блок выбора работы.

        Проверять по всей странице нельзя: `type="search"` есть у Cmd+K
        popup в `base.html`, а `style="display:none"` — у значков
        чек-листа. Оба ответили бы за поиск по работам, которого нет.
        """
        return html[html.index('Шығарманы таңдау'):
                    html.index('Сәйкестік чек-листі')]

    def _submit_html(self, username='aidana', stories=None):
        """Длинный список подделывается на снимке автора, а не на хелпере.

        Работы кандидатов приходят из `User.authored` — того самого снимка,
        который страница собирает один раз и раздаёт. Подменять надо его:
        подмена отдельного хелпера сторожила бы имя, а не источник.
        """
        login_as(self.client, username)
        ctx = (mock.patch.object(User, 'authored',
                                 property(lambda self: stories))
               if stories is not None else contextlib.nullcontext())
        with ctx:
            response = self.client.get(
                reverse('core:contest_submit', args=['bolashak-mektebi']))
        return response, response.content.decode()

    def test_a_short_list_gets_no_search(self):
        response, html = self._submit_html()
        self.assertLessEqual(len(response.context['candidates']),
                             views.PICKER_SEARCH_FROM)
        self.assertFalse(response.context['picker_search'])
        self.assertNotIn('type="search"', self._picker(html))

    def test_a_long_list_gets_one_that_hides_nothing_without_js(self):
        many = list(data.public_stories_of(user('aidana'))) * 4   # > порога
        response, html = self._submit_html(stories=many)
        self.assertTrue(response.context['picker_search'])
        picker = self._picker(html)
        self.assertIn('type="search"', picker)
        # Фильтрация — по данным, а не по тексту разметки метки.
        self.assertIn('x-show="match(', picker)
        for volume in response.context['volumes'].values():
            self.assertTrue(volume['title'])
        # Без JS `x-show` не срабатывает, и список остаётся целым.
        for story in data.public_stories_of(user('aidana')):
            with self.subTest(story=story.slug):
                self.assertIn(story.title, picker)
        self.assertNotIn('style="display:none"', picker)


# ───────────────────────────────────────────────────────────────────────
# Ф15, Этап 5: настоящий POST — `Submission` создаётся и отзывается
# ───────────────────────────────────────────────────────────────────────

class ContestSubmitCreatesSubmission(TestCase):

    SLUG = 'bolashak-mektebi'   # accepting, возрастная вилка непустая
    STORY_SLUG = 'tunge-deiin'  # bekzhan_t-нікі, кандидат бойынша таза

    def setUp(self):
        super().setUp()
        login_as(self.client, 'bekzhan_t')

    def _post(self, slug=None, **overrides):
        payload = {'story_slug': self.STORY_SLUG, 'ai_used': 'no',
                   'confirm_age': 'on', 'confirm_rules': 'on'}
        payload.update(overrides)
        return self.client.post(
            reverse('core:contest_submit', kwargs={'slug': slug or self.SLUG}),
            payload)

    def _count(self, slug=None, username='bekzhan_t'):
        return Submission.objects.filter(contest__slug=slug or self.SLUG,
                                         author__username=username).count()

    def test_it_stores_the_posted_fields_and_comes_back(self):
        response = self._post()
        self.assertRedirects(
            response, reverse('core:contest_submit', kwargs={'slug': self.SLUG}))
        sub = Submission.objects.get(contest__slug=self.SLUG,
                                     author__username='bekzhan_t')
        self.assertEqual(sub.story.slug, self.STORY_SLUG)
        self.assertEqual(sub.status, 'reviewing')
        self.assertEqual(sub.submitted_on, date.today())
        self.assertEqual(sub.ai_declaration, 'no')
        self.assertTrue(sub.age_confirmed)
        self.assertTrue(sub.rules_confirmed)

    def test_the_declaration_is_stored_as_posted(self):
        self._post(ai_used='partial')
        self.assertEqual(
            Submission.objects.get(contest__slug=self.SLUG,
                                   author__username='bekzhan_t').ai_declaration,
            'partial')

    def test_a_missing_or_forged_field_creates_nothing(self):
        """BR-24 не блокирует выбор работы, но не отменяет обязательные поля."""
        cases = {
            'нет работы': {'story_slug': ''},
            # 'aidana-tan' — чужая работа, в кандидатах bekzhan_t её нет.
            'чужая работа': {'story_slug': 'aidana-tan'},
            'нет декларации': {'ai_used': ''},
            'мусор в декларации': {'ai_used': 'garbage'},
            'нет согласия с правилами': {'confirm_rules': ''},
            'нет подтверждения возраста': {'confirm_age': ''},
        }
        self.assertTrue(_eligibility(Contest.objects.get(slug=self.SLUG)))
        for label, overrides in cases.items():
            with self.subTest(case=label):
                self._post(**overrides)
                self.assertEqual(self._count(), 0)
        self.assertRedirects(
            self._post(story_slug='', ai_used='', confirm_rules=''),
            reverse('core:contest_submit', kwargs={'slug': self.SLUG}))

    def test_the_age_box_is_not_required_where_the_contest_has_no_bracket(self):
        Contest.objects.filter(slug=self.SLUG).update(min_age=None, max_age=None)
        self._post(confirm_age='')
        self.assertEqual(self._count(), 1)

    def test_a_direct_post_cannot_bypass_the_phase_or_the_one_entry_rule(self):
        """DEC-45 и BR-23: то, что форма прячет, POST обойти не должен."""
        for slug in ('altyn-qalam', 'qys-ertegisi'):
            with self.subTest(contest=slug):
                self._post(slug=slug)
                self.assertEqual(self._count(slug), 0)

        login_as(self.client)   # aidana уже подала на altyn-qalam
        self.assertEqual(self._count('altyn-qalam', 'aidana'), 1)
        self._post(slug='altyn-qalam', story_slug='aidana-tan')
        self.assertEqual(self._count('altyn-qalam', 'aidana'), 1)

    def test_a_guest_creates_nothing(self):
        before = Submission.objects.filter(contest__slug=self.SLUG).count()
        Client().post(reverse('core:contest_submit', args=[self.SLUG]), {
            'story_slug': self.STORY_SLUG, 'ai_used': 'no',
            'confirm_age': 'on', 'confirm_rules': 'on'})
        self.assertEqual(
            Submission.objects.filter(contest__slug=self.SLUG).count(), before)


class WithdrawSubmission(TestCase):
    """BR-23b: одна работа на конкурс — но заявку можно забрать назад."""

    OPEN = 'bolashak-mektebi'   # dina_books подала, приём идёт

    def test_withdrawal_is_open_only_while_the_contest_accepts(self):
        self.assertTrue(data.can_withdraw(user('dina_books'), self.OPEN))
        self.assertFalse(data.can_withdraw(user('aidana'), 'altyn-qalam'))
        self.assertFalse(data.can_withdraw(user('bekzhan_t'), 'zhas-aldym-2023'))
        self.assertFalse(data.can_withdraw(user('bekzhan_t'), self.OPEN))

    def test_the_button_appears_only_where_withdrawal_is_open(self):
        login_as(self.client, 'dina_books')
        mine = self.client.get(reverse('core:my_submissions'))
        self.assertContains(mine, 'Қайтарып алу')
        self.assertContains(mine, 'open-withdraw-confirm')
        login_as(self.client)   # у aidana судейство уже идёт
        self.assertNotContains(self.client.get(reverse('core:my_submissions')),
                               'open-withdraw-confirm')

    def test_a_post_deletes_the_row_and_leaves_the_neighbour_alone(self):
        # Заводим вторую заявку на тот же конкурс — отзыв dina_books не
        # должен задеть чужую строку.
        data.create_submission(
            User.objects.get(username='aidana'),
            Contest.objects.get(slug=self.OPEN),
            data.story_by_slug('aidana-tan'),
            ai_declaration='no', age_confirmed=True, rules_confirmed=True)

        login_as(self.client, 'dina_books')
        response = self.client.post(
            reverse('core:contest_withdraw', args=[self.OPEN]))
        self.assertRedirects(response, reverse('core:my_submissions'))
        self.assertFalse(Submission.objects.filter(
            contest__slug=self.OPEN, author__username='dina_books').exists())
        self.assertTrue(Submission.objects.filter(
            contest__slug=self.OPEN, author__username='aidana').exists())

    def test_nothing_else_withdraws_anything(self):
        # GET отвечает «не тот метод», а не тихо ничего не делает.
        login_as(self.client, 'dina_books')
        self.assertEqual(
            self.client.get(reverse('core:contest_withdraw',
                                    args=[self.OPEN])).status_code, 405)
        self.assertTrue(Submission.objects.filter(
            contest__slug=self.OPEN, author__username='dina_books').exists())
        # Гость уходит на вход, а не в тихий редирект «как будто получилось».
        guest = Client().post(reverse('core:contest_withdraw', args=[self.OPEN]))
        self.assertIn('/auth/login/', guest['Location'])
        self.assertTrue(Submission.objects.filter(
            contest__slug=self.OPEN, author__username='dina_books').exists())
        # Судейство уже идёт
        login_as(self.client)
        response = self.client.post(
            reverse('core:contest_withdraw', args=['altyn-qalam']))
        self.assertRedirects(response, reverse('core:my_submissions'))
        self.assertEqual(Submission.objects.filter(
            contest__slug='altyn-qalam', author__username='aidana').count(), 1)
        # Заявки нет вовсе
        login_as(self.client, 'bekzhan_t')
        self.client.post(reverse('core:contest_withdraw', args=[self.OPEN]))
        self.assertFalse(Submission.objects.filter(
            contest__slug=self.OPEN, author__username='bekzhan_t').exists())


# ───────────────────────────────────────────────────────────────────────
# Свои заявки
# ───────────────────────────────────────────────────────────────────────

class MySubmissions(TestCase):

    def test_a_guest_gets_a_gate_and_a_newcomer_an_empty_state(self):
        self.assertContains(self.client.get(reverse('core:my_submissions')),
                            'кір')
        login_as_newcomer(self.client, 'lonely_writer')
        empty = self.client.get(reverse('core:my_submissions'))
        self.assertContains(empty, 'Әлі өтінім жоқ')
        self.assertContains(empty, reverse('core:contest_list'))

    def test_it_lists_every_submission_with_its_verdict(self):
        login_as(self.client)
        response = self.client.get(reverse('core:my_submissions'))
        self.assertEqual(response.status_code, 200)
        for sub in data.submissions_of(user('aidana')):
            with self.subTest(slug=sub.contest.slug):
                self.assertContains(response, sub.contest.name)
                self.assertContains(response, sub.story.title)
                self.assertContains(response, reverse(
                    'core:contest_detail', kwargs={'slug': sub.contest.slug}))
        # У aidana: 1 reviewing + 1 rejected, у отказа — заметка жюри.
        self.assertContains(response, 'Қаралуда')
        self.assertContains(response, 'Қабылданбады')
        self.assertContains(response, 'Көлемі шарттан аз')

    def test_it_names_the_dates_behind_the_verdict(self):
        """«Қаралуда» без даты не отвечает на «а когда узнаю»."""
        login_as(self.client, 'dina_books')
        accepting = data.contest_by_slug('bolashak-mektebi')
        response = self.client.get(reverse('core:my_submissions'))
        self.assertContains(response, short_date(accepting.closes_on))
        self.assertContains(response, short_date(accepting.results_on))
        login_as(self.client)
        self.assertContains(
            self.client.get(reverse('core:my_submissions')),
            short_date(data.contest_by_slug('altyn-qalam').results_on))

    def test_accepted_stays_the_jury_word(self):
        """«Қабылданды» — решение жюри (BR-41), а не факт получения формы.

        Тост подачи говорил именно это слово, и автор читал отправку как
        победу в первом же круге. Одна сущность — одно слово (docs/ui.md).
        """
        login_as(self.client)
        story = data.public_stories_of(user('aidana'))[0]
        html = self.client.post(
            reverse('core:contest_submit', args=['bolashak-mektebi']),
            {'story_slug': story.slug, 'ai_used': 'no',
             'confirm_age': 'on', 'confirm_rules': 'on'},
            follow=True).content.decode()
        self.assertNotIn('Өтінім қабылданды', html)
        self.assertIn('Өтінім жіберілді', html)

        login_as(self.client, 'dina_books')
        self.assertContains(self.client.get(reverse('core:my_submissions')),
                            data.CONTEST_RESULT_LABELS['accepted'])


class SubmissionIntegrity(TestCase):

    def test_a_submission_belongs_to_its_author_and_stands_alone(self):
        """BR-23: один автор — не больше одной заявки на конкретный конкурс."""
        for username, subs in _all_submissions().items():
            slugs = [s.contest.slug for s in subs]
            with self.subTest(user=username):
                self.assertEqual(len(slugs), len(set(slugs)))
            for sub in subs:
                with self.subTest(user=username, story=sub.story.slug):
                    self.assertIsNotNone(data.contest_by_slug(sub.contest.slug))
                    self.assertEqual(
                        data.story_by_slug(sub.story.slug).author.username,
                        username)

    def test_the_contest_badge_and_the_submission_imply_each_other(self):
        """Данные расходились в обе стороны: у `igra-kuklovoda` бейдж стоял
        без единой заявки, а у `aidana-tan` заявка на активный «Алтын қалам»
        была, но бейджа не было — каталог по оси `badge=contest` работу не
        находил."""
        label = 'Байқауға қатысады'
        active = {c.slug for c in data.open_contests()}
        expected = {sub.story.slug
                    for subs in _all_submissions().values()
                    for sub in subs if sub.contest.slug in active}
        for story in data.public_stories():
            if label in story.badges:
                with self.subTest(story=story.slug):
                    self.assertIn(story.slug, expected)
        for slug in expected:
            with self.subTest(story=slug):
                self.assertIn(label, data.story_by_slug(slug).badges)

    def test_the_date_is_a_date_and_lies_inside_the_window(self):
        """Хранимое `submitted_relative="6 ай бұрын"` стояло у заявки на
        конкурс, закрывшийся в декабре 2023-го: подача приходилась на
        полгода позже дедлайна, и заметить это было нечем (BR-41a)."""
        stored = {f.name for f in Submission._meta.get_fields()}
        self.assertNotIn('submitted_relative', stored,
                         '`submitted_relative` снова стало полем')
        self.assertIn('submitted_on', stored)
        for username, subs in _all_submissions().items():
            for sub in subs:
                with self.subTest(user=username, contest=sub.contest.slug):
                    self.assertGreaterEqual(sub.submitted_on,
                                            sub.contest.opens_on)
                    self.assertLessEqual(sub.submitted_on, sub.contest.closes_on)

    def test_the_label_follows_the_date(self):
        fresh = data.submissions_of(user('aidana'))[0]
        self.assertEqual(ago(fresh.submitted_on),
                         data.kk_ago((date.today() - fresh.submitted_on).days))
        # Заявка 2023 года в 2026-м — не «1 жыл бұрын».
        old = data.submissions_of(user('bekzhan_t'))[0]
        years = (date.today() - old.submitted_on).days // 365
        self.assertEqual(ago(old.submitted_on), f'{years} жыл бұрын')

    def test_the_rejection_note_names_the_side_of_the_threshold(self):
        sub = next(s for s in data.submissions_of(user('aidana'))
                   if s.status == 'rejected')
        total = sum(c.char_count for c in data.chapters_of(sub.story.slug))
        self.assertLess(total, sub.contest.min_chars)
        self.assertIn('аз', sub.note)
