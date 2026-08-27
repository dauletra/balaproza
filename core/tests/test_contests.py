"""CONT — байқау: объект, страница, подача и свои заявки.

Два правила держат весь раздел.

**Фаза выводится из трёх дат** (DEC-45). Хранимых `status`, `days_left`,
`year` и числа заявок нет: «87 өтінім» стояло при одной настоящей заявке,
а `days_left=12` протухал назавтра.

**Форма ничего не отклоняет** (BR-24). У кандидатов бывают заметки — про
объём, про занятость другим конкурсом, — но решение принимает человек.
Прежняя версия гасила радио и кнопку, то есть отказывала от имени
конкурса до всякого жюри.
"""

import contextlib
import re
from datetime import date
from pathlib import Path
from unittest import mock

from django.test import Client
from django.urls import reverse

from core import data, views
from core.models import (
    AwardGrant,
    Contest,
    ContestCondition,
    Story,
    Submission,
    User,
)
from core.tests.base import TestCase, login_as, login_as_newcomer

TEMPLATES = Path(__file__).resolve().parents[2] / 'templates'


def _all_submissions() -> dict:
    """Заявки по авторам. Нужны затем, чтобы проверить, что число заявок
    у конкурса считается, а не хранится (BR-40a)."""
    out = {}
    for sub in Submission.objects.select_related('author', 'contest', 'story'):
        out.setdefault(sub.author.username, []).append(sub)
    return out


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
        self.assertEqual(final.period, '15 жел')
        self.assertEqual(intake.period, '1 қыр — 1 жел')


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
            line = contest.timing_line
            with self.subTest(contest=contest.slug, phase=contest.phase):
                if contest.phase == 'finished':
                    self.assertEqual(line, '')
                elif contest.phase == 'upcoming':
                    self.assertIn(contest.opens_on_label, line)
                elif contest.phase == 'accepting':
                    self.assertIn(contest.closes_on_label, line)
                    self.assertIn(contest.results_on_label, line)
                else:
                    self.assertIn(contest.results_on_label, line)
                # Числа «12 күн» в строке нет: оно протухло бы назавтра.
                self.assertNotIn('күн қалды', line)

    def test_the_submissions_page_renders_that_same_line(self):
        login_as(self.client, 'dina_books')
        self.assertContains(
            self.client.get(reverse('core:my_submissions')),
            data.contest_by_slug('bolashak-mektebi').timing_line)


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
                    Contest(**self.BASE, **extra).eligibility_line, expected)

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
            restricted.eligibility_line)

        free = data.contest_by_slug('qys-ertegisi')
        self.assertEqual(free.eligibility_line, '')
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
                     for s in data.submissions_of(grant.story.author.username)})
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
                        data.has_submission(story.author.username, contest.slug))

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

    def test_the_declared_files_exist_in_media(self):
        """`media/` целиком в `.gitignore`, поэтому на чистом клоне файлов
        нет, и жёсткая проверка падала бы не на ошибке, а на отсутствии
        необязательных ассетов. Контракт пути проверяется отдельно."""
        from django.conf import settings
        root = Path(settings.MEDIA_ROOT) / 'awards'
        if not root.is_dir():
            self.skipTest('media/awards/ нет локально — ассеты не в репозитории')
        for contest in data.all_contests():
            for award in contest.awards:
                if not award.image:
                    continue
                with self.subTest(contest=contest.slug, award=award.slug):
                    self.assertTrue(
                        (Path(settings.MEDIA_ROOT) / award.image.name).is_file(),
                        f'нет файла: {award.image.name}')

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
            'qys-ertegisi': 'opens_on_label',            # upcoming
            'altyn-qalam': 'results_on_label',           # judging
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
                    self.assertContains(response, getattr(contest, field))

    def test_an_unknown_slug_says_so_and_offers_nothing(self):
        response = self.client.get(
            reverse('core:contest_detail', kwargs={'slug': 'ghost'}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Байқау табылмады')
        self.assertNotContains(response, 'Бөлісу')

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
        for url in ('/contests/unknown-slug/', '/contests/unknown-slug/submit/'):
            with self.subTest(url=url):
                self.assertFalse(
                    self.client.get(url).context['has_right_rail'])
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


# ───────────────────────────────────────────────────────────────────────
# Подача работы: кандидаты, заметки, чек-лист
# ───────────────────────────────────────────────────────────────────────

class SubmissionHelpers(TestCase):

    def test_candidates_are_the_public_works_and_nothing_else(self):
        """Черновик и работа на модерации на конкурс не выставляются
        (DEC-23): их нельзя ни дать прочитать жюри, ни показать читателю
        рядом с победителями. Это единственное, что список сужает — всё
        остальное заметки, не запреты (BR-24)."""
        items = data.submission_candidates('aidana', 'altyn-qalam')
        self.assertEqual([i['story'].slug for i in items],
                         [s.slug for s in data.public_stories_of('aidana')])
        for item in items:
            with self.subTest(story=item['story'].slug):
                self.assertTrue(item['story'].is_public)
                self.assertEqual(set(item), {'story', 'chars', 'notes'})
                for note in item['notes']:
                    self.assertEqual(set(note), {'key', 'text'})
                    self.assertIn(note['key'], data.SUBMISSION_NOTES)
        self.assertEqual(data.submission_candidates('aidana', 'no-such'), [])
        self.assertEqual(data.submission_candidates('ghost', 'altyn-qalam'), [])

    def test_the_submission_lookup_answers_both_ways(self):
        self.assertEqual(len(data.submissions_of('aidana')), 2)
        self.assertEqual(data.submissions_of('ghost'), [])
        self.assertTrue(data.has_submission('aidana', 'altyn-qalam'))
        self.assertFalse(data.has_submission('aidana', 'bolashak-mektebi'))

    def test_the_checklist_marks_volume_and_demands_the_declaration(self):
        contest = data.contest_by_slug('altyn-qalam')
        for slug in ('aidana-koshe',     # 4 750 знаков — меньше порога
                     'aidana-erteg'):    # ни одной главы — ноль знаков
            checklist = data.submission_checklist(data.story_by_slug(slug),
                                                  contest)
            volume = next(i for i in checklist if i['key'] == 'volume')
            with self.subTest(story=slug):
                self.assertFalse(volume['passed'])
        self.assertIn('Көлемі тым аз',
                      next(i for i in data.submission_checklist(
                          data.story_by_slug('aidana-koshe'), contest)
                          if i['key'] == 'volume')['hint'])
        declaration = next(i for i in data.submission_checklist(
            data.story_by_slug('aidana-tan'), contest) if i['key'] == 'ai_decl')
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
        for story in data.public_stories_of('aidana'):
            with self.subTest(slug=story.slug):
                self.assertContains(response, f'value="{story.slug}"')
        for story in data.my_stories_of('aidana'):
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

    def test_an_unknown_slug_says_so(self):
        login_as(self.client)
        self.assertContains(
            self.client.get(reverse('core:contest_submit',
                                    kwargs={'slug': 'ghost'})),
            'Байқау табылмады')


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
                for i in data.submission_candidates(username, slug)}

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
        self.assertIsNone(data.busy_contest_of('bekzhan_t', 'temniy-lord'))
        self.assertIsNone(data.busy_contest_of('aidana', 'aidana-tan',
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
        items = data.submission_candidates('rudazov', 'bolashak-mektebi')
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

        Работы кандидатов приходят из `AuthorFacts` — того самого снимка,
        который страница собирает один раз и раздаёт. Подменять надо его:
        подмена отдельного хелпера сторожила бы имя, а не источник.
        """
        login_as(self.client, username)
        ctx = (mock.patch.object(data.AuthorFacts, 'stories',
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
        many = data.public_stories_of('aidana') * 4   # > порога
        response, html = self._submit_html(stories=many)
        self.assertTrue(response.context['picker_search'])
        picker = self._picker(html)
        self.assertIn('type="search"', picker)
        # Фильтрация — по данным, а не по тексту разметки метки.
        self.assertIn('x-show="match(', picker)
        for volume in response.context['volumes'].values():
            self.assertTrue(volume['title'])
        # Без JS `x-show` не срабатывает, и список остаётся целым.
        for story in data.public_stories_of('aidana'):
            with self.subTest(story=story.slug):
                self.assertIn(story.title, picker)
        self.assertNotIn('style="display:none"', picker)


# ───────────────────────────────────────────────────────────────────────
# Ф15, Этап 5: настоящий POST — `Submission` создаётся и отзывается
# ───────────────────────────────────────────────────────────────────────

class ContestSubmitCreatesSubmission(TestCase):

    SLUG = 'bolashak-mektebi'   # accepting, eligibility_line непустой
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
        self.assertTrue(Contest.objects.get(slug=self.SLUG).eligibility_line)
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
        self.assertTrue(data.can_withdraw('dina_books', self.OPEN))
        self.assertFalse(data.can_withdraw('aidana', 'altyn-qalam'))
        self.assertFalse(data.can_withdraw('bekzhan_t', 'zhas-aldym-2023'))
        self.assertFalse(data.can_withdraw('bekzhan_t', self.OPEN))

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
        # GET безопасен
        login_as(self.client, 'dina_books')
        self.client.get(reverse('core:contest_withdraw', args=[self.OPEN]))
        self.assertTrue(Submission.objects.filter(
            contest__slug=self.OPEN, author__username='dina_books').exists())
        # Гость
        Client().post(reverse('core:contest_withdraw', args=[self.OPEN]))
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
        for sub in data.submissions_of('aidana'):
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
        self.assertContains(response, accepting.closes_on_label)
        self.assertContains(response, accepting.results_on_label)
        login_as(self.client)
        self.assertContains(
            self.client.get(reverse('core:my_submissions')),
            data.contest_by_slug('altyn-qalam').results_on_label)

    def test_accepted_stays_the_jury_word(self):
        """«Қабылданды» — решение жюри (BR-41), а не факт получения формы.

        Тост подачи говорил именно это слово, и автор читал отправку как
        победу в первом же круге. Одна сущность — одно слово (docs/ui.md).
        """
        login_as(self.client)
        story = data.public_stories_of('aidana')[0]
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
        fresh = data.submissions_of('aidana')[0]
        self.assertEqual(fresh.submitted_label,
                         data.kk_ago((date.today() - fresh.submitted_on).days))
        # Заявка 2023 года в 2026-м — не «1 жыл бұрын».
        old = data.submissions_of('bekzhan_t')[0]
        years = (date.today() - old.submitted_on).days // 365
        self.assertEqual(old.submitted_label, f'{years} жыл бұрын')

    def test_the_rejection_note_names_the_side_of_the_threshold(self):
        sub = next(s for s in data.submissions_of('aidana')
                   if s.status == 'rejected')
        total = sum(c.char_count for c in data.chapters_of(sub.story.slug))
        self.assertLess(total, sub.contest.min_chars)
        self.assertIn('аз', sub.note)
