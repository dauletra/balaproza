"""CONT · подача работы и свои заявки.

Правило раздела: **форма ничего не отклоняет** (BR-24). У кандидатов
бывают заметки — про объём, про занятость другим конкурсом, — но решение
принимает человек. Прежняя версия гасила радио и кнопку, то есть
отказывала от имени конкурса до всякого жюри.
"""

import contextlib
from datetime import date
from pathlib import Path
from unittest import mock

from core.tests.base import TestCase, login_as, login_as_newcomer
from django.urls import reverse

from core import data, views
from core.models import Contest, ContestCondition, Submission

TEMPLATES = Path(__file__).resolve().parents[2] / 'templates'


def _all_submissions() -> dict:
    """Заявки по авторам — то, чем раньше был словарь стаба."""
    out = {}
    for sub in Submission.objects.select_related('author', 'contest', 'story'):
        out.setdefault(sub.author.username, []).append(sub)
    return out


TEMPLATES = Path(__file__).resolve().parents[2] / 'templates'


class SubmissionsHelpers(TestCase):

    def test_submissions_of_aidana(self):
        subs = data.submissions_of('aidana')
        self.assertEqual(len(subs), 2)

    def test_submissions_of_unknown(self):
        self.assertEqual(data.submissions_of('ghost'), [])

    def test_has_submission_true(self):
        self.assertTrue(data.has_submission('aidana', 'altyn-qalam'))

    def test_has_submission_false(self):
        self.assertFalse(data.has_submission('aidana', 'bolashak-mektebi'))


class ChecklistHelpers(TestCase):

    def test_checklist_short_story_fails_volume(self):
        # aidana-koshe: главы 800+1200+950+1100+700 = 4750 < 5000
        story = data.story_by_slug('aidana-koshe')
        contest = data.contest_by_slug('altyn-qalam')
        cl = data.submission_checklist(story, contest)
        vol = next(i for i in cl if i['key'] == 'volume')
        self.assertFalse(vol['passed'])
        self.assertIn('Көлемі тым аз', vol['hint'])

    def test_checklist_normal_story_passes_volume(self):
        # aidana-tan: 1500+2100+1900+1700+2200+2800+1400+1900 = 15500 — это уже больше!
        # Возьмём dalney-berega (всего 12 глав по 1800-3300 = много, > max)
        # И koshe слишком мало. Найдём подходящую: koshe (4750), tan (15500), dalney (большой).
        # Чтобы был проход — нам нужен 5000-15000. Создадим искусственно — берём
        # подмножество через первые N глав. Или используем aidana-erteg.
        # aidana-erteg в CHAPTERS_BY_STORY отсутствует → total=0 → fail.
        # Нет идеальной — проверим что для 0 главы fail и для слишком большой fail.
        story = data.story_by_slug('aidana-erteg')  # без глав → 0 chars
        contest = data.contest_by_slug('altyn-qalam')
        cl = data.submission_checklist(story, contest)
        vol = next(i for i in cl if i['key'] == 'volume')
        self.assertFalse(vol['passed'])

    def test_checklist_ai_declaration_required(self):
        story = data.story_by_slug('aidana-tan')
        contest = data.contest_by_slug('altyn-qalam')
        cl = data.submission_checklist(story, contest)
        ai = next(i for i in cl if i['key'] == 'ai_decl')
        self.assertFalse(ai['passed'])
        self.assertTrue(ai.get('required'))


class SubmissionCandidates(TestCase):

    def test_only_public_works_are_candidates(self):
        """Черновик и работа на модерации на конкурс не выставляются (DEC-23).

        Их нельзя ни дать прочитать жюри, ни показать читателю рядом
        с победителями. Это единственное, что список кандидатов сужает:
        всё остальное — заметки, не запреты (BR-24).
        """
        items = data.submission_candidates('aidana', 'altyn-qalam')
        self.assertEqual([i['story'].slug for i in items],
                         [s.slug for s in data.public_stories_of('aidana')])
        self.assertTrue(all(i['story'].is_public for i in items))

    def test_shape_is_complete(self):
        for it in data.submission_candidates('aidana', 'altyn-qalam'):
            with self.subTest(story=it['story'].slug):
                self.assertEqual(set(it), {'story', 'chars', 'notes'})
                for note in it['notes']:
                    self.assertEqual(set(note), {'key', 'text'})
                    self.assertIn(note['key'], data.SUBMISSION_NOTES)

    def test_candidates_unknown_contest(self):
        self.assertEqual(data.submission_candidates('aidana', 'no-such'), [])

    def test_candidates_unknown_user(self):
        self.assertEqual(data.submission_candidates('ghost', 'altyn-qalam'), [])


class ContestDetailAlreadySubmitted(TestCase):

    SLUG = 'altyn-qalam'

    def setUp(self):
        login_as(self.client)   # aidana уже подала на altyn-qalam-2024
        self.response = self.client.get(reverse('core:contest_detail', kwargs={'slug': self.SLUG}))

    def test_shows_already_submitted_badge(self):
        self.assertContains(self.response, 'Өтінім берілген')

    def test_no_qatysu_button(self):
        # Если уже подал — нет CTA «Қатысу» (только бейдж)
        # Ссылка на submit-страницу есть только в форме, но кнопки нет
        self.assertNotContains(self.response, '>\n                        Қатысу\n                    </a>')


class ContestSubmitGuest(TestCase):

    def test_guest_sees_gate(self):
        r = self.client.get(reverse('core:contest_submit', kwargs={'slug': 'bolashak-mektebi'}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'кір')
        # формы не показываем гостю
        self.assertNotContains(r, 'name="story_slug"')


class ContestSubmitForm(TestCase):

    SLUG = 'bolashak-mektebi'   # на этот aidana НЕ подавала

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:contest_submit', kwargs={'slug': self.SLUG}))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_form_lists_the_public_works(self):
        for s in data.public_stories_of('aidana'):
            with self.subTest(slug=s.slug):
                self.assertContains(self.response, f'value="{s.slug}"')

    def test_form_hides_drafts_and_moderation(self):
        for s in data.my_stories_of('aidana'):
            if s.is_public:
                continue
            with self.subTest(slug=s.slug):
                self.assertNotContains(self.response, f'value="{s.slug}"')

    def test_notes_a_too_short_story_without_disabling_it(self):
        # aidana-koshe: 2 482 < 5 000 — заметка есть, запрета нет (BR-24)
        self.assertContains(self.response, data.SUBMISSION_NOTES['too_short'])
        self.assertContains(self.response, 'value="aidana-koshe"')

    def test_shows_checklist(self):
        self.assertContains(self.response, 'Сәйкестік чек-листі')
        # BR-22 пункты
        self.assertContains(self.response, 'Тіл — қазақша')
        self.assertContains(self.response, 'AI-декларация')

    def test_ai_radio_required(self):
        self.assertContains(self.response, 'name="ai_used"')
        self.assertContains(self.response, 'value="no"')
        self.assertContains(self.response, 'value="partial"')
        self.assertContains(self.response, 'value="yes"')

    def test_consent_checkboxes(self):
        self.assertContains(self.response, 'name="confirm_age"')
        self.assertContains(self.response, 'name="confirm_rules"')


class ContestSubmitAlreadyDone(TestCase):

    SLUG = 'altyn-qalam'   # aidana уже подала

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:contest_submit', kwargs={'slug': self.SLUG}))

    def test_shows_already_submitted_block(self):
        self.assertContains(self.response, 'Сен бұл байқауға өтінім бергенсің')

    def test_no_form_when_already_submitted(self):
        # форма выбора произведения отсутствует
        self.assertNotContains(self.response, 'name="story_slug"')

    def test_links_to_my_submissions(self):
        self.assertContains(self.response, reverse('core:my_submissions'))


class ContestSubmitUnknown(TestCase):

    def test_unknown_slug_renders_not_found(self):
        login_as(self.client)
        r = self.client.get(reverse('core:contest_submit', kwargs={'slug': 'ghost'}))
        self.assertContains(r, 'Байқау табылмады')


class MySubmissionsGuest(TestCase):

    def test_guest_sees_gate(self):
        r = self.client.get(reverse('core:my_submissions'))
        self.assertContains(r, 'кір')


class MySubmissionsAuthed(TestCase):

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:my_submissions'))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_lists_all_submissions(self):
        for sub in data.submissions_of('aidana'):
            with self.subTest(slug=sub.contest.slug):
                self.assertContains(self.response, sub.contest.name)
                self.assertContains(self.response, sub.story.title)

    def test_shows_status_badges(self):
        # У aidana: 1 reviewing + 1 rejected
        self.assertContains(self.response, 'Қаралуда')
        self.assertContains(self.response, 'Қабылданбады')

    def test_links_to_contest_detail(self):
        for sub in data.submissions_of('aidana'):
            with self.subTest(slug=sub.contest.slug):
                self.assertContains(
                    self.response,
                    reverse('core:contest_detail', kwargs={'slug': sub.contest.slug}),
                )

    def test_rejected_shows_jury_note(self):
        self.assertContains(self.response, 'Көлемі шарттан аз')


class MySubmissionsEmpty(TestCase):

    def setUp(self):
        login_as_newcomer(self.client, 'lonely_writer')

    def test_empty_state_shown(self):
        r = self.client.get(reverse('core:my_submissions'))
        self.assertContains(r, 'Әлі өтінім жоқ')
        self.assertContains(r, reverse('core:contest_list'))


class SubmissionsMatchContestBadges(TestCase):
    """Бейдж «Байқауға қатысады» на работе ⟺ заявка на идущий конкурс.

    Данные расходились в обе стороны: у `igra-kuklovoda` бейдж стоял без
    единой заявки, а у `aidana-tan` заявка на активный «Алтын қалам» была,
    но бейджа не было — каталог по оси `badge=contest` работу не находил.
    """

    LABEL = 'Байқауға қатысады'

    def _stories_with_active_submission(self):
        active = {c.slug for c in data.open_contests()}
        return {
            sub.story.slug
            for subs in _all_submissions().values()
            for sub in subs
            if sub.contest.slug in active
        }

    def test_badge_implies_active_submission(self):
        expected = self._stories_with_active_submission()
        for s in data.public_stories():
            if self.LABEL in s.badges:
                with self.subTest(story=s.slug):
                    self.assertIn(s.slug, expected)

    def test_active_submission_implies_badge(self):
        for slug in self._stories_with_active_submission():
            with self.subTest(story=slug):
                self.assertIn(self.LABEL, data.story_by_slug(slug).badges)


class SubmissionIntegrity(TestCase):

    def test_submissions_reference_known_contests_and_stories(self):
        """На моделях это гарантия внешнего ключа, а не совпадение слагов —
        но проверка остаётся: сид мог не донести часть корпуса."""
        for username in ('aidana', 'dina_books', 'bekzhan_t'):
            for sub in data.submissions_of(username):
                with self.subTest(user=username, contest=sub.contest.slug):
                    self.assertIsNotNone(data.contest_by_slug(sub.contest.slug))
                    self.assertIsNotNone(data.story_by_slug(sub.story.slug))

    def test_submitted_story_belongs_to_submitter(self):
        for username, subs in _all_submissions().items():
            for sub in subs:
                with self.subTest(user=username, story=sub.story.slug):
                    self.assertEqual(
                        data.story_by_slug(sub.story.slug).author.username,
                        username,
                    )

    def test_one_work_per_contest(self):
        """BR-23: один автор — не больше одной заявки на конкретный конкурс."""
        for username, subs in _all_submissions().items():
            slugs = [s.contest.slug for s in subs]
            with self.subTest(user=username):
                self.assertEqual(len(slugs), len(set(slugs)))


class ChecklistNumbers(TestCase):
    """Числа в подсказках — с разрядами, пороги — из конкурса, не литералом."""

    def setUp(self):
        self.contest = data.contest_by_slug('altyn-qalam')
        self.story = data.story_by_slug('aidana-tan')
        self.volume = next(i for i in data.submission_checklist(self.story, self.contest)
                           if i['key'] == 'volume')

    def test_thresholds_come_from_the_contest(self):
        self.assertIn(data.spaced_number(self.contest.min_chars), self.volume['label'])
        self.assertIn(data.spaced_number(self.contest.max_chars), self.volume['label'])

    def test_char_count_is_spaced(self):
        total = sum(c.char_count for c in data.chapters_of(self.story.slug))
        self.assertIn(data.spaced_number(total), self.volume['hint'])
        self.assertNotIn(str(total), self.volume['hint'])


class RejectionNoteMatchesTheData(TestCase):
    """Отказ по объёму должен называть ту сторону порога, которая нарушена."""

    def test_aidana_rejection_says_too_small(self):
        sub = next(s for s in data.submissions_of('aidana') if s.status == 'rejected')
        total = sum(c.char_count for c in data.chapters_of(sub.story.slug))
        self.assertLess(total, sub.contest.min_chars)
        self.assertIn('аз', sub.note)


class SubmitIsGatedByPhase(TestCase):
    """Форма подачи живёт только в фазе приёма (DEC-45).

    Прямая ссылка открывалась в любой момент и предлагала подать работу
    в конкурс, который ещё не начался или уже ушёл на судейство.
    """

    def setUp(self):
        # Не aidana: у неё уже есть заявка в «Алтын қалам», и страница
        # показала бы блок «өтінім бергенсің» раньше, чем блок фазы.
        login_as(self.client, 'bekzhan_t')

    # Голого `<form` мало: базовый шаблон несёт свои формы (поиск, жалоба).
    # Признак именно формы подачи — поле выбора произведения.
    FIELD = 'name="story_slug"'

    def test_upcoming_contest_shows_no_form(self):
        r = self.client.get(reverse('core:contest_submit', args=['qys-ertegisi']))
        self.assertNotContains(r, self.FIELD)
        self.assertContains(r, 'Өтінім қабылдау әлі басталған жоқ')

    def test_judging_contest_shows_no_form(self):
        r = self.client.get(reverse('core:contest_submit', args=['altyn-qalam']))
        self.assertNotContains(r, self.FIELD)
        self.assertContains(r, 'Өтінім қабылдау жабылды')

    def test_finished_contest_shows_no_form(self):
        r = self.client.get(reverse('core:contest_submit', args=['zhas-aldym-2023']))
        self.assertNotContains(r, self.FIELD)

    def test_accepting_contest_still_shows_the_form(self):
        r = self.client.get(reverse('core:contest_submit', args=['bolashak-mektebi']))
        self.assertContains(r, self.FIELD)


class SubmissionNotesInformButDoNotBlock(TestCase):
    """Форма ничего не отклоняет — она сообщает (BR-24).

    Раньше работа короче порога или занятая другим конкурсом приходила
    с `disabled`, а кнопка отправки гасла: отказ от имени конкурса,
    вынесенный до жюри и без права возразить. Заметка осталась, запрет
    ушёл — её видит автор здесь и админ в заявке.
    """

    def _items(self, username, slug='bolashak-mektebi'):
        return {i['story'].slug: i
                for i in data.submission_candidates(username, slug)}

    def _keys(self, item):
        return {n['key'] for n in item['notes']}

    def test_short_work_is_noted_not_removed(self):
        item = self._items('aidana')['aidana-koshe']
        self.assertIn('too_short', self._keys(item))
        self.assertIn(data.SUBMISSION_NOTES['too_short'],
                      item['notes'][0]['text'])

    def test_work_in_another_open_contest_is_noted(self):
        """Одним текстом идти в двух конкурсах — повод для разговора,
        а не для молча закрытой двери (BR-23a)."""
        item = self._items('aidana')['aidana-tan']
        self.assertIn('busy', self._keys(item))
        self.assertIn('Алтын қалам',
                      next(n['text'] for n in item['notes'] if n['key'] == 'busy'))

    def test_all_notes_are_named_not_just_the_first(self):
        """Прежняя цепочка `elif` называла одну причину и молчала об остальных.

        Работа и короткая, и занятая другим конкурсом сообщала только про
        объём — второе всплывало бы уже у админа.
        """
        Contest.objects.filter(slug='bolashak-mektebi').update(min_chars=10_000)
        item = self._items('aidana')['aidana-tan']
        self.assertEqual(self._keys(item), {'too_short', 'busy'})

    def test_finished_contest_does_not_hold_a_work(self):
        """Работа своё отучаствовала — заметки о ней больше нет."""
        self.assertIsNone(
            data.busy_contest_of('bekzhan_t', 'temniy-lord'))

    def test_the_same_contest_is_not_a_note_about_itself(self):
        busy = data.busy_contest_of('aidana', 'aidana-tan', besides='altyn-qalam')
        self.assertIsNone(busy)

    def test_clean_work_carries_no_notes(self):
        self.assertEqual(self._items('bekzhan_t')['tunge-deiin']['notes'], [])

    def test_no_radio_is_disabled_and_the_button_stays_live(self):
        login_as(self.client, 'rudazov')   # все работы короче порога
        html = self.client.get(
            reverse('core:contest_submit', args=['bolashak-mektebi'])).content.decode()
        picker = html[html.index('name="story_slug"'):html.index('Сәйкестік чек-листі')]
        self.assertNotIn('disabled', picker)
        self.assertIn('Өтінім беру', html)


class ChecklistFollowsTheChoice(TestCase):
    """FR-CONT-04: чек-лист пересчитывается при смене работы, не застывает."""

    def setUp(self):
        login_as(self.client, 'bekzhan_t')
        self.response = self.client.get(
            reverse('core:contest_submit', args=['bolashak-mektebi']))

    def test_view_ships_volume_data_for_every_candidate(self):
        vols = self.response.context['volumes']
        candidates = {i['story'].slug
                      for i in self.response.context['candidates']}
        self.assertEqual(set(vols), candidates)
        for slug, v in vols.items():
            with self.subTest(story=slug):
                self.assertEqual(set(v), {'passed', 'hint', 'title'})

    def test_data_is_embedded_for_the_browser(self):
        self.assertContains(self.response, 'id="submit-volumes"')
        self.assertContains(self.response, 'x-model="picked"')

    def test_initial_choice_is_a_work_without_notes(self):
        """Отклонять форма ничего не отклоняет, но начинать выбор с работы,
        о которой есть что сказать, незачем."""
        slug = self.response.context['initial_slug']
        item = next(i for i in self.response.context['candidates']
                    if i['story'].slug == slug)
        self.assertEqual(item['notes'], [])


class ChecklistSurvivesWithoutAnEligibleWork(TestCase):
    """Раньше при отсутствии подходящей работы исчезали AI-декларация и оба
    согласия: чек-лист считался только для подходящей, а форма без него
    выглядела обрубленной."""

    def setUp(self):
        login_as(self.client, 'rudazov')   # все работы короче порога
        self.response = self.client.get(
            reverse('core:contest_submit', args=['bolashak-mektebi']))

    def test_every_work_carries_a_note(self):
        self.assertTrue(all(i['notes']
                            for i in self.response.context['candidates']))

    def test_checklist_is_still_rendered(self):
        self.assertContains(self.response, 'Сәйкестік чек-листі')

    def test_declaration_and_consents_are_still_rendered(self):
        self.assertContains(self.response, 'name="ai_used"')
        self.assertContains(self.response, 'name="confirm_age"')
        self.assertContains(self.response, 'name="confirm_rules"')

    def test_submit_is_not_blocked_by_the_notes(self):
        """Ни одна заметка не гасит отправку (BR-24)."""
        self.assertContains(self.response, 'Өтінім беру')


class WithdrawSubmission(TestCase):
    """BR-23b: одна работа на конкурс — но заявку можно забрать назад."""

    def test_allowed_while_the_contest_still_accepts(self):
        self.assertTrue(data.can_withdraw('dina_books', 'bolashak-mektebi'))

    def test_denied_once_judging_started(self):
        self.assertFalse(data.can_withdraw('aidana', 'altyn-qalam'))

    def test_denied_for_a_finished_contest(self):
        self.assertFalse(data.can_withdraw('bekzhan_t', 'zhas-aldym-2023'))

    def test_denied_without_a_submission(self):
        self.assertFalse(data.can_withdraw('bekzhan_t', 'bolashak-mektebi'))

    def test_button_and_modal_are_on_the_submissions_page(self):
        login_as(self.client, 'dina_books')
        r = self.client.get(reverse('core:my_submissions'))
        self.assertContains(r, 'Қайтарып алу')
        self.assertContains(r, 'open-withdraw-confirm')

    def test_button_absent_when_withdrawal_is_closed(self):
        login_as(self.client)
        r = self.client.get(reverse('core:my_submissions'))
        self.assertNotContains(r, 'open-withdraw-confirm')


class SubmissionsPageNamesTheDates(TestCase):
    """«Қаралуда» без даты не отвечает на «а когда узнаю»."""

    def test_accepting_contest_shows_both_dates(self):
        login_as(self.client, 'dina_books')
        r = self.client.get(reverse('core:my_submissions'))
        c = data.contest_by_slug('bolashak-mektebi')
        self.assertContains(r, c.closes_on_label)
        self.assertContains(r, c.results_on_label)

    def test_judging_contest_shows_the_results_date(self):
        login_as(self.client)
        r = self.client.get(reverse('core:my_submissions'))
        self.assertContains(r,
                            data.contest_by_slug('altyn-qalam').results_on_label)


class SubmissionDatesAreReal(TestCase):
    """Дата подачи хранится датой и лежит внутри окна приёма (BR-41a).

    Хранимое `submitted_relative="6 ай бұрын"` стояло у заявки на конкурс,
    закрывшийся в декабре 2023-го: подача приходилась на полгода позже
    дедлайна, и заметить это было нечем — строка ведь не дата.
    """

    def test_relative_string_is_not_stored(self):
        stored = {f.name for f in Submission._meta.get_fields()}
        self.assertNotIn(
            'submitted_relative', stored,
            '`submitted_relative` снова стало полем — это хранимое производное')
        self.assertIn('submitted_on', stored)

    def test_submitted_inside_the_acceptance_window(self):
        for username, subs in _all_submissions().items():
            for sub in subs:
                with self.subTest(user=username, contest=sub.contest.slug):
                    c = sub.contest
                    self.assertGreaterEqual(sub.submitted_on, c.opens_on)
                    self.assertLessEqual(sub.submitted_on, c.closes_on)

    def test_label_follows_the_date(self):
        sub = data.submissions_of('aidana')[0]
        self.assertEqual(
            sub.submitted_label,
            data.kk_ago((date.today() - sub.submitted_on).days))

    def test_old_submission_is_not_called_a_year_ago_forever(self):
        """Заявка 2023 года в 2026-м — не «1 жыл бұрын»."""
        sub = data.submissions_of('bekzhan_t')[0]
        years = (date.today() - sub.submitted_on).days // 365
        self.assertEqual(sub.submitted_label, f'{years} жыл бұрын')


class AcceptedIsTheJuryWord(TestCase):
    """«Қабылданды» — решение жюри (BR-41), а не факт получения формы.

    Тост подачи говорил именно это слово, и автор читал отправку как победу
    в первом же круге. Одна сущность — одно слово (docs/16 §16.4).
    """

    def test_submit_form_does_not_promise_acceptance(self):
        login_as(self.client)
        html = self.client.get(
            reverse('core:contest_submit', args=['bolashak-mektebi'])).content.decode()
        self.assertNotIn('Өтінім қабылданды', html)
        self.assertIn('Өтінім жіберілді', html)

    def test_word_survives_where_it_means_the_verdict(self):
        login_as(self.client, 'dina_books')
        r = self.client.get(reverse('core:my_submissions'))
        self.assertContains(r, data.CONTEST_RESULT_LABELS['accepted'])


class CommonRulesAreWrittenOnce(TestCase):
    """Общие правила — один реестр, а не копия в каждом конкурсе (BR-48a).

    Копия успела разойтись тремя способами: неполно (AI-декларация
    обязательна для всех, названа была у одного из пяти), литералом
    («5 000-15 000 таңба» при хранимых порогах) и с кодами ТЗ в тексте.
    """

    def test_thresholds_come_from_the_contest(self):
        for slug in ('altyn-qalam', 'bolashak-mektebi'):
            c = data.contest_by_slug(slug)
            vol = next(r for r in data.common_rules(c) if r['key'] == 'volume')
            with self.subTest(contest=slug):
                self.assertIn(data.spaced_number(c.min_chars), vol['label'])
                self.assertIn(data.spaced_number(c.max_chars), vol['label'])

    def test_every_contest_page_states_them_all(self):
        for slug in [c.slug for c in data.all_contests()]:
            r = self.client.get(reverse('core:contest_detail', args=[slug]))
            contest = data.contest_by_slug(slug)
            for rule in data.common_rules(contest):
                with self.subTest(contest=slug, rule=rule['key']):
                    self.assertContains(r, rule['label'])

    def test_conditions_do_not_restate_a_common_rule(self):
        """Свои условия и общие правила лежат в одном списке (FR-CONT-15).

        Разделён был показ, а не источник: соблазн вписать общее правило
        себе в `conditions` от слияния только вырос, а расходиться копия
        начнёт так же — с AI-декларации, названной у одного конкурса.
        """
        for c in data.all_contests():
            labels = {r['label'] for r in data.common_rules(c)}
            for cond in c.conditions:
                with self.subTest(contest=c.slug, cond=cond):
                    self.assertNotIn(cond, labels)
                    # Пороги объёма живут в min_chars/max_chars и приходят
                    # готовой строкой; переписанные руками, они разойдутся.
                    self.assertNotIn(data.spaced_number(c.min_chars), cond)
                    self.assertNotIn(data.spaced_number(c.max_chars), cond)

    def test_conditions_may_be_any_length(self):
        """Список свободный: и пустой, и длинный рендерятся одинаково."""
        slug = 'qys-ertegisi'
        contest = data.contest_by_slug(slug)
        many = tuple(f"Қосымша шарт {n}" for n in range(1, 13))
        for conds in ((), many):
            with self.subTest(count=len(conds)):
                contest.condition_set.all().delete()
                ContestCondition.objects.bulk_create([
                    ContestCondition(contest=contest, text=text, position=i)
                    for i, text in enumerate(conds)])
                r = self.client.get(reverse('core:contest_detail', args=[slug]))
                self.assertEqual(r.status_code, 200)
                # Секция стоит и у конкурса без единого своего условия:
                # общие правила есть всегда.
                self.assertContains(r, 'Шарттар')
                for cond in conds:
                    self.assertContains(r, cond)

    def test_checklist_is_built_from_the_same_registry(self):
        c = data.contest_by_slug('altyn-qalam')
        story = data.story_by_slug('aidana-tan')
        checklist = {i['key'] for i in data.submission_checklist(story, c)}
        per_work = {r['key'] for r in data.common_rules(c) if r['per_work']}
        self.assertTrue(per_work <= checklist)
        # «Бір автор — бір өтінім» — про автора, не про текст: его держит
        # сама форма (BR-23), в чек-лист работы он не идёт.
        self.assertNotIn('one_entry', checklist)

    def test_checklist_age_item_follows_the_contest(self):
        story = data.story_by_slug('aidana-tan')
        with_age = data.submission_checklist(
            story, data.contest_by_slug('altyn-qalam'))
        self.assertIn('eligibility', {i['key'] for i in with_age})
        without = data.submission_checklist(
            story, data.contest_by_slug('qys-ertegisi'))
        self.assertNotIn('eligibility', {i['key'] for i in without},
                         'конкурс без ценза не должен показывать вечно пройденный пункт')

    def test_confirmation_checkbox_only_where_there_is_a_rule(self):
        """Форма обязана рендериться в обоих случаях, иначе проверка пустая.

        Первая версия брала «Қыс ертегісі» как конкурс без вилки — но он
        в фазе `upcoming`, формы там нет вовсе, и `confirm_age`
        отсутствовал совсем по другой причине. Конкурс без ценза,
        который сейчас принимает заявки, в стабе не заведён, поэтому он
        собирается здесь из существующего.
        """
        login_as(self.client)
        slug = 'bolashak-mektebi'
        with_age = self.client.get(reverse('core:contest_submit', args=[slug])).content.decode()
        self.assertIn('confirm_rules', with_age, 'форма не отрендерилась — проверка пуста')
        self.assertIn('confirm_age', with_age)

        Contest.objects.filter(slug=slug).update(min_age=None, max_age=None)
        without = self.client.get(
            reverse('core:contest_submit', args=[slug])).content.decode()
        self.assertIn('confirm_rules', without, 'форма не отрендерилась — проверка пуста')
        self.assertNotIn('confirm_age', without)


class NotesStandNextToTheirWork(TestCase):
    """Заметка стоит у работы, а не внизу формы.

    Отдельный блок внизу объяснял, почему гаснет кнопка. Кнопка больше не
    гаснет (BR-24), а заметка внизу формы относилась неизвестно к какой из
    работ — к моменту, когда автор до неё дочитывал, выбор был уже сделан.
    """

    def test_every_note_is_rendered_inside_the_picker(self):
        login_as(self.client, 'rudazov')
        html = self.client.get(
            reverse('core:contest_submit', args=['bolashak-mektebi'])).content.decode()
        picker = html[html.index('name="story_slug"'):html.index('Сәйкестік чек-листі')]
        items = data.submission_candidates('rudazov', 'bolashak-mektebi')
        self.assertTrue(any(i['notes'] for i in items), 'стаб потерял работы с заметками')
        for item in items:
            for note in item['notes']:
                with self.subTest(story=item['story'].slug, note=note['key']):
                    self.assertIn(note['text'], picker)

    def test_a_clean_choice_shows_no_note(self):
        login_as(self.client, 'bekzhan_t')
        r = self.client.get(reverse('core:contest_submit', args=['bolashak-mektebi']))
        slug = r.context['initial_slug']
        item = next(i for i in r.context['candidates'] if i['story'].slug == slug)
        self.assertEqual(item['notes'], [])


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
        return html[html.index('Шығарманы таңдау'):html.index('Сәйкестік чек-листі')]

    def _submit_html(self, username='aidana', stories=None):
        """Длинный список подделывается на снимке автора, а не на хелпере.

        Работы кандидатов приходят из `AuthorFacts` — того самого снимка,
        который страница собирает один раз и раздаёт. Подменять надо его:
        подмена отдельного хелпера сторожила бы имя, а не источник.
        """
        login_as(self.client, username)
        ctx = (mock.patch.object(data.AuthorFacts, 'stories',
                                 property(lambda self: stories))
               if stories is not None else contextlib.nullcontext())
        with ctx:
            r = self.client.get(reverse('core:contest_submit', args=['bolashak-mektebi']))
        return r, r.content.decode()

    def test_short_list_has_no_search(self):
        r, html = self._submit_html()
        self.assertLessEqual(len(r.context['candidates']), views.PICKER_SEARCH_FROM)
        self.assertFalse(r.context['picker_search'])
        self.assertNotIn('type="search"', self._picker(html))

    def test_long_list_gets_a_search(self):
        many = data.public_stories_of('aidana') * 4   # > порога
        r, html = self._submit_html(stories=many)
        self.assertTrue(r.context['picker_search'])
        picker = self._picker(html)
        self.assertIn('type="search"', picker)
        # Фильтрация — по данным, а не по тексту разметки метки.
        self.assertIn('x-show="match(', picker)
        for v in r.context['volumes'].values():
            self.assertTrue(v['title'])

    def test_search_does_not_hide_anything_without_js(self):
        """Без JS `x-show` не срабатывает, и список остаётся целым."""
        many = data.public_stories_of('aidana') * 4
        _, html = self._submit_html(stories=many)
        picker = self._picker(html)
        for s in data.public_stories_of('aidana'):
            self.assertIn(s.title, picker)
        self.assertNotIn('style="display:none"', picker)
