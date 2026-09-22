"""CONT — байқау как объект: даты, фазы, условия, награды.

Главное правило раздела: **фаза выводится из трёх дат** (DEC-45).
Хранимых `status`, `days_left`, `year` и числа заявок нет — «87 өтінім»
стояло при одной настоящей заявке, а `days_left=12` протухал назавтра.

Страницы раздела — в `test_contest_pages.py`, подача работы — в
`test_contest_submit.py`.
"""


import re
from datetime import date

from django.urls import reverse

from core import data
from core.domain.contests import eligibility_line, timing_line
from core.templatetags.qazaqnovel import period, short_date
from core.models import AwardGrant, Contest, ContestCondition, Submission
from core.tests.base import TestCase, login_as


def _timing(contest) -> str:
    return timing_line(contest.phase, contest.opens_on, contest.closes_on,
                       contest.results_on)


def _all_submissions() -> dict:
    """Заявки по авторам. Нужны затем, чтобы проверить, что число заявок
    у конкурса считается, а не хранится (BR-40a)."""
    out = {}
    for sub in Submission.objects.select_related('author', 'contest', 'story'):
        out.setdefault(sub.author.username, []).append(sub)
    return out


def _eligibility(contest) -> str:
    return eligibility_line(contest.min_age, contest.max_age)


# ───────────────────────────────────────────────────────────────────────
# Конкурс как объект: даты — единственный источник
# ───────────────────────────────────────────────────────────────────────

class ContestDatesAreTheSource(TestCase):
    """DEC-45: фаза, отсчёт, год и число заявок выводятся, а не хранятся."""

    def test_every_contest_has_the_fields_its_phase_implies(self):
        for contest in data.all_contests():
            with self.subTest(slug=contest.slug):
                self.assertTrue(contest.name)
                self.assertIn(contest.phase, data.CONTEST_PHASES)
                self.assertLessEqual(contest.opens_on, contest.closes_on)
                self.assertLess(contest.closes_on, contest.results_on)
                # Отсчёт есть ровно там, где ему есть что считать.
                self.assertEqual(contest.days_left is not None,
                                 contest.is_accepting)
                self.assertEqual(contest.days_until_open is not None,
                                 contest.phase == 'upcoming')

    def test_the_demo_set_covers_all_four_phases(self):
        """Иначе `judging` и `upcoming` не на чем увидеть, а ради них
        DEC-45 и заводился."""
        self.assertEqual({c.phase for c in data.all_contests()},
                         set(data.CONTEST_PHASES))
        self.assertEqual(data.contest_by_slug('altyn-qalam').name, 'Алтын қалам')

    def test_the_count_of_entries_matches_the_real_rows(self):
        """Хранимое «87 өтінім» стояло при одной настоящей заявке."""
        submissions = _all_submissions()
        for contest in data.all_contests():
            real = sum(1 for subs in submissions.values()
                       for s in subs if s.contest.slug == contest.slug)
            with self.subTest(slug=contest.slug):
                self.assertGreaterEqual(contest.submissions, 0)
                self.assertEqual(contest.submissions, real)

    def test_the_year_comes_from_the_results_date(self):
        for contest in data.all_contests():
            with self.subTest(slug=contest.slug):
                self.assertEqual(contest.year, contest.results_on.year)
                self.assertGreater(contest.year, 2000)
                # «altyn-qalam-2024» с годом 2023 — расхождение, которое
                # видит читатель.
                tail = re.search(r'-(\d{4})$', contest.slug)
                if tail:
                    self.assertEqual(contest.year, int(tail.group(1)))

    def test_the_timeline_lies_inside_the_window_and_runs_forward(self):
        for contest in data.all_contests():
            starts = [t.starts for t in contest.timeline]
            with self.subTest(slug=contest.slug):
                self.assertEqual(starts, sorted(starts))
            for stage in contest.timeline:
                with self.subTest(slug=contest.slug, stage=stage.label):
                    self.assertLessEqual(stage.starts, stage.ends)
                    self.assertGreaterEqual(stage.ends, contest.opens_on)
                    self.assertLessEqual(stage.starts, contest.results_on)

    def test_the_current_stage_follows_the_calendar(self):
        active = data.contest_by_slug('bolashak-mektebi')
        self.assertGreater(len(active.jury), 0)
        self.assertGreater(len(active.timeline), 0)
        self.assertEqual(sum(1 for t in active.timeline if t.state == 'active'), 1)
        self.assertEqual(active.current_stage.label, 'Өтінім қабылдау')
        self.assertEqual(active.next_stage.label, 'Қазылар қарауы')

        finished = data.contest_by_slug('zhas-aldym-2023')
        self.assertTrue(all(t.state == 'done' for t in finished.timeline))
        self.assertIsNone(finished.current_stage)
        self.assertIsNone(finished.next_stage)

    def test_kazakh_dates_read_as_a_day_or_as_a_range(self):
        contest = data.contest_by_slug('zhas-aldym-2023')
        final = next(t for t in contest.timeline if t.label == 'Финал')
        intake = next(t for t in contest.timeline if t.label == 'Өтінім қабылдау')
        self.assertEqual(period(final), '15 жел')
        self.assertEqual(period(intake), '1 қыр — 1 жел')


class ContestGroupsAndPhaseLabels(TestCase):

    def test_the_groups_partition_the_set(self):
        accepting = {c.slug for c in data.accepting_contests()}
        open_ = {c.slug for c in data.open_contests()}
        finished = {c.slug for c in data.finished_contests()}
        self.assertTrue(accepting <= open_)
        self.assertEqual(open_ & finished, set())
        self.assertEqual(open_ | finished, {c.slug for c in data.all_contests()})
        # Баннер главной — ближайший приём, а не порядок в списке.
        self.assertTrue(data.hero_contest().is_accepting)

    def test_the_phase_label_comes_from_one_registry(self):
        html = self.client.get(reverse('core:contest_list')).content.decode()
        for phase in data.CONTEST_PHASES:
            with self.subTest(phase=phase):
                self.assertIn(phase, data.CONTEST_PHASE_LABELS)
                self.assertIn(phase, data.CONTEST_PHASE_BADGE)
        for contest in data.all_contests():
            with self.subTest(slug=contest.slug):
                self.assertIn(data.CONTEST_PHASE_LABELS[contest.phase], html)


class ContestTimingLineIsOneImplementation(TestCase):
    """«Что дальше и когда» собирает конкурс, а не шаблон.

    Формулировка стояла inline в `my_submissions.html`; вторая копия для
    конкурсного уведомления разошлась бы с ней ровно так же, как разошлись
    две рукописные копии правил подачи.
    """

    def test_the_line_matches_the_phase_and_carries_no_countdown(self):
        for contest in data.all_contests():
            line = timing_line(contest.phase, contest.opens_on,
                               contest.closes_on, contest.results_on)
            with self.subTest(contest=contest.slug, phase=contest.phase):
                if contest.phase == 'finished':
                    self.assertEqual(line, '')
                elif contest.phase == 'upcoming':
                    self.assertIn(short_date(contest.opens_on), line)
                elif contest.phase == 'accepting':
                    self.assertIn(short_date(contest.closes_on), line)
                    self.assertIn(short_date(contest.results_on), line)
                else:
                    self.assertIn(short_date(contest.results_on), line)
                # Числа «12 күн» в строке нет: оно протухло бы назавтра.
                self.assertNotIn('күн қалды', line)

    def test_the_submissions_page_renders_that_same_line(self):
        login_as(self.client, 'dina_books')
        self.assertContains(
            self.client.get(reverse('core:my_submissions')),
            _timing(data.contest_by_slug('bolashak-mektebi')))


class AgeIsTheContestsRule(TestCase):
    """Возрастную вилку ставит конкурс, а не платформа (BR-48).

    Прежнее BR-20 объявляло «14-18 лет» правилом платформы, и потому
    конкурс со своей вилкой выразить было нечем: четыре конкурса из пяти
    повторяли одну и ту же строку руками, чек-лист держал её в коде,
    а форма регистрации сообщала её каждому новому пришедшему.
    """

    BASE = dict(slug='x', name='X', subtitle='',
                opens_on=date(2026, 1, 1), closes_on=date(2026, 2, 1),
                results_on=date(2026, 3, 1), prize_kzt=None)

    def test_the_line_reads_right_in_every_shape(self):
        for extra, expected in (({'min_age': 16, 'max_age': 25}, '16-25 жас'),
                                ({'min_age': 18}, '18 жастан бастап'),
                                ({'max_age': 22}, '22 жасқа дейін'),
                                ({}, '')):
            with self.subTest(**extra):
                self.assertEqual(
                    _eligibility(Contest(**self.BASE, **extra)), expected)

    def test_the_contests_do_not_all_share_one_bracket(self):
        """Если у всех одна вилка, поле ничем не отличается от константы."""
        brackets = {(c.min_age, c.max_age) for c in data.all_contests()}
        self.assertGreater(len(brackets), 1)
        self.assertIn((None, None), brackets,
                      'нужен конкурс без ценза — иначе ветка «нет требования» '
                      'не показана')

    def test_the_conditions_repeat_neither_the_age_nor_a_spec_code(self):
        for contest in data.all_contests():
            for condition in contest.conditions:
                with self.subTest(contest=contest.slug, cond=condition):
                    self.assertNotIn('жас', condition,
                                     'возраст приходит из min_age/max_age')
                    # «(BR-23)» и «(DEC-21)» читал подросток.
                    self.assertNotRegex(condition, r'\b(BR|DEC|FR|NFR)-\d+')

    def test_the_page_states_the_bracket_only_when_there_is_one(self):
        restricted = data.contest_by_slug('altyn-qalam')
        self.assertContains(
            self.client.get(reverse('core:contest_detail',
                                    args=[restricted.slug])),
            _eligibility(restricted))

        free = data.contest_by_slug('qys-ertegisi')
        self.assertEqual(_eligibility(free), '')
        html = self.client.get(
            reverse('core:contest_detail', args=[free.slug])).content.decode()
        self.assertNotIn('Қатысушы:', html)


class CommonRulesAreWrittenOnce(TestCase):
    """Общие правила — один реестр, а не копия в каждом конкурсе (BR-48a).

    Копия успела разойтись тремя способами: неполно (AI-декларация
    обязательна для всех, названа была у одного из пяти), литералом
    («5 000-15 000 таңба» при хранимых порогах) и с кодами ТЗ в тексте.
    """

    def test_the_thresholds_come_from_the_contest(self):
        for slug in ('altyn-qalam', 'bolashak-mektebi'):
            contest = data.contest_by_slug(slug)
            volume = next(r for r in data.common_rules(contest)
                          if r['key'] == 'volume')
            with self.subTest(contest=slug):
                self.assertIn(data.spaced_number(contest.min_chars),
                              volume['label'])
                self.assertIn(data.spaced_number(contest.max_chars),
                              volume['label'])

    def test_every_contest_page_states_them_all(self):
        for contest in data.all_contests():
            response = self.client.get(
                reverse('core:contest_detail', args=[contest.slug]))
            for rule in data.common_rules(contest):
                with self.subTest(contest=contest.slug, rule=rule['key']):
                    self.assertContains(response, rule['label'])

    def test_own_conditions_never_restate_a_common_rule(self):
        """Свои условия и общие правила лежат в одном списке (FR-CONT-15).

        Разделён был показ, а не источник: соблазн вписать общее правило
        себе в `conditions` от слияния только вырос, а расходиться копия
        начнёт так же — с AI-декларации, названной у одного конкурса.
        """
        for contest in data.all_contests():
            labels = {r['label'] for r in data.common_rules(contest)}
            for condition in contest.conditions:
                with self.subTest(contest=contest.slug, cond=condition):
                    self.assertNotIn(condition, labels)
                    # Пороги объёма живут в min_chars/max_chars и приходят
                    # готовой строкой; переписанные руками, они разойдутся.
                    self.assertNotIn(data.spaced_number(contest.min_chars),
                                     condition)
                    self.assertNotIn(data.spaced_number(contest.max_chars),
                                     condition)

    def test_the_list_of_conditions_may_be_any_length(self):
        """И пустой, и длинный рендерятся одинаково."""
        slug = 'qys-ertegisi'
        contest = data.contest_by_slug(slug)
        many = tuple(f'Қосымша шарт {n}' for n in range(1, 13))
        for conditions in ((), many):
            with self.subTest(count=len(conditions)):
                contest.condition_set.all().delete()
                ContestCondition.objects.bulk_create([
                    ContestCondition(contest=contest, text=text, position=i)
                    for i, text in enumerate(conditions)])
                response = self.client.get(
                    reverse('core:contest_detail', args=[slug]))
                self.assertEqual(response.status_code, 200)
                # Секция стоит и у конкурса без единого своего условия:
                # общие правила есть всегда.
                self.assertContains(response, 'Шарттар')
                for condition in conditions:
                    self.assertContains(response, condition)

    def test_the_checklist_is_built_from_the_same_registry(self):
        contest = data.contest_by_slug('altyn-qalam')
        story = data.story_by_slug('aidana-tan')
        checklist = {i['key'] for i in data.submission_checklist(story, contest)}
        per_work = {r['key'] for r in data.common_rules(contest) if r['per_work']}
        self.assertTrue(per_work <= checklist)
        # «Бір автор — бір өтінім» — про автора, не про текст: его держит
        # сама форма (BR-23), в чек-лист работы он не идёт.
        self.assertNotIn('one_entry', checklist)
        # Пункт возраста приходит от конкурса: без ценза вечно пройденный
        # пункт показывать незачем.
        self.assertNotIn('eligibility',
                         {i['key'] for i in data.submission_checklist(
                             story, data.contest_by_slug('qys-ertegisi'))})

    def test_the_age_checkbox_stands_only_where_there_is_a_rule(self):
        """Форма обязана рендериться в обоих случаях, иначе проверка пустая.

        Первая версия брала «Қыс ертегісі» как конкурс без вилки — но он
        в фазе `upcoming`, формы там нет вовсе, и `confirm_age` отсутствовал
        совсем по другой причине. Конкурс без ценза, который сейчас
        принимает заявки, в корпусе не заведён, поэтому он собирается
        здесь из существующего.
        """
        login_as(self.client)
        slug = 'bolashak-mektebi'
        url = reverse('core:contest_submit', args=[slug])
        with_age = self.client.get(url).content.decode()
        self.assertIn('confirm_rules', with_age, 'форма не отрендерилась')
        self.assertIn('confirm_age', with_age)

        Contest.objects.filter(slug=slug).update(min_age=None, max_age=None)
        without = self.client.get(url).content.decode()
        self.assertIn('confirm_rules', without, 'форма не отрендерилась')
        self.assertNotIn('confirm_age', without)


# ───────────────────────────────────────────────────────────────────────
# Награды конкурса: номинации и присуждения (DEC-46)
# ───────────────────────────────────────────────────────────────────────

class ContestAwardsData(TestCase):
    """Набор номинаций у каждого конкурса свой, победа — акт жюри."""

    def test_every_contest_declares_its_own_unique_awards(self):
        """Номинация — ответ на «зачем участвовать». Конкурс без неё
        предлагает только сумму в тенге."""
        for contest in data.all_contests():
            slugs = [a.slug for a in contest.awards]
            with self.subTest(contest=contest.slug):
                self.assertTrue(contest.awards)
                self.assertEqual(len(slugs), len(set(slugs)))

    def test_a_grant_implies_a_finished_contest_and_a_submission(self):
        """Награду нельзя вручить, пока жюри не закончило, и вручить её
        некому, если автор не подавал заявку."""
        seen = []
        for grant in AwardGrant.objects.all():
            with self.subTest(grant=(grant.contest.slug, grant.award.slug)):
                self.assertIsNotNone(grant.story)
                self.assertTrue(grant.contest.is_finished)
                self.assertIn(
                    grant.contest.slug,
                    {s.contest.slug
                     for s in data.submissions_of(grant.story.author)})
            seen.append((grant.contest.slug, grant.award.slug))
        # Одна номинация вручается не более одного раза.
        self.assertEqual(len(seen), len(set(seen)))

    def test_the_winners_are_derived_from_the_grants(self):
        finished = data.contest_by_slug('zhas-aldym-2023')
        self.assertEqual(finished.winners,
                         tuple(g.story.slug for g in finished.grants))
        self.assertEqual({s.author.username for s in finished.winner_stories},
                         {'bekzhan_t', 'dina_books'})
        for contest in data.all_contests():
            with self.subTest(contest=contest.slug):
                if not contest.grants:
                    self.assertEqual(contest.winners, ())
                if contest.winners:
                    self.assertTrue(contest.is_finished)
                for slug in contest.winners:
                    self.assertIsNotNone(data.story_by_slug(slug))
                for story in contest.winner_stories:
                    # Победа без поданной заявки — конкурсной истории
                    # неоткуда взяться.
                    self.assertTrue(
                        data.has_submission(story.author, contest.slug))

    def test_an_open_contest_has_no_winners_yet(self):
        for contest in data.open_contests():
            with self.subTest(contest=contest.slug):
                self.assertEqual(contest.winners, ())

    def test_the_generic_winner_award_is_retired(self):
        """DEC-46 снял общий «Байқау жеңімпазы» — его вытеснила награда
        конкретного конкурса. Знаки участия остались."""
        keys = {a.key for a in data.AWARDS}
        self.assertNotIn('contest_winner', keys)
        self.assertIn('contest_participant', keys)
        self.assertIn('contest_accepted', keys)


class ContestAwardImages(TestCase):
    """Эмблему грузит админ файлом — путь обязан вести к реальному файлу."""

    def test_the_path_follows_the_contract(self):
        """`awards/<contest>/<award>.png` — растр, не SVG.

        SVG из `/media/` открывается в origin сайта и может нести скрипт;
        загрузка эмблем идёт через админку, но правило одно для всех.
        """
        for contest in data.all_contests():
            for award in contest.awards:
                if not award.image:
                    continue
                with self.subTest(award=award.slug):
                    self.assertTrue(
                        award.image.name.startswith(f'awards/{contest.slug}/'),
                        award.image.name)
                    self.assertTrue(award.image.name.endswith(('.png', '.webp')),
                                    award.image.name)

    # Теста «файл лежит в media/» здесь больше нет. Он проверял не код, а
    # содержимое гитигнорной папки на машине разработчика: на чистом клоне
    # молча пропускался, на рабочей — падал или нет в зависимости от
    # порядка тестов, потому что сид в ту же папку и писал (см.
    # `tests/runner.py`). Теперь `MEDIA_ROOT` под тестами временный, и
    # проверять там нечего. Правило, которое действительно код, —
    # контракт пути выше.

    def test_an_award_without_an_image_still_renders(self):
        """Админ не загрузил файл — типографическая заглушка, не дыра."""
        contest = data.contest_by_slug('bolashak-mektebi')
        self.assertTrue(any(not a.image for a in contest.awards),
                        'фикстура сломана: нужна номинация без эмблемы')
        response = self.client.get(
            reverse('core:contest_detail', args=[contest.slug]))
        self.assertEqual(response.status_code, 200)
        for award in contest.awards:
            with self.subTest(award=award.slug):
                self.assertContains(response, award.title)


class ContestEditionsAreLinked(TestCase):
    """Завершённый конкурс перестал быть тупиком (FR-CONT-13, BR-47)."""

    def test_the_editions_see_each_other(self):
        old = data.contest_by_slug('zhas-aldym-2023')
        new = data.contest_by_slug('zhas-aldym-2026')
        self.assertEqual([c.slug for c in old.other_editions], [new.slug])
        self.assertEqual([c.slug for c in new.other_editions], [old.slug])
        self.assertEqual(data.contest_by_slug('altyn-qalam').other_editions, [])
        for contest in data.all_contests():
            for edition in contest.other_editions:
                with self.subTest(contest=contest.slug, edition=edition.slug):
                    self.assertEqual(edition.year, edition.results_on.year)

    def test_the_finished_page_links_to_the_open_edition(self):
        response = self.client.get(
            reverse('core:contest_detail', args=['zhas-aldym-2023']))
        self.assertContains(response, reverse('core:contest_detail',
                                              args=['zhas-aldym-2026']))
        self.assertContains(response, 'Басқа жылдар')
