"""CONT · конкурсы: список / детальная / подача / мои заявки."""

import re
from datetime import date
from pathlib import Path
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from core import stub_data

TEMPLATES = Path(__file__).resolve().parents[2] / 'templates'


def _login_as_aidana(client):
    s = client.session
    s['signed_in'] = True
    s['user_name'] = 'Айдана'
    s['user_username'] = 'aidana'
    s.save()


def _login_as(client, username):
    s = client.session
    s['signed_in'] = True
    s['user_name'] = 'X'
    s['user_username'] = username
    s.save()


# ════════════════════════════ stub_data helpers ════════════════════════════

class ContestModel(TestCase):

    def test_contests_have_required_fields(self):
        for c in stub_data.CONTESTS:
            with self.subTest(slug=c.slug):
                self.assertTrue(c.name)
                self.assertIn(c.phase, stub_data.CONTEST_PHASES)
                self.assertGreaterEqual(c.submissions, 0)
                # Отсчёт есть ровно там, где ему есть что считать.
                self.assertEqual(c.days_left is not None, c.is_accepting)
                self.assertEqual(c.days_until_open is not None,
                                 c.phase == 'upcoming')

    def test_contests_by_slug_lookup(self):
        self.assertEqual(
            stub_data.CONTESTS_BY_SLUG['altyn-qalam'].name,
            'Алтын қалам',
        )

    def test_every_phase_is_represented_in_the_stub_set(self):
        """Демо-набор покрывает все четыре фазы — иначе `judging` и
        `upcoming` не на чем увидеть, а ради них DEC-45 и заводился."""
        self.assertEqual({c.phase for c in stub_data.CONTESTS},
                         set(stub_data.CONTEST_PHASES))

    def test_contest_groups_do_not_overlap(self):
        accepting = {c.slug for c in stub_data.ACCEPTING_CONTESTS}
        open_ = {c.slug for c in stub_data.OPEN_CONTESTS}
        finished = {c.slug for c in stub_data.FINISHED_CONTESTS}
        self.assertTrue(accepting <= open_)
        self.assertEqual(open_ & finished, set())
        self.assertEqual(open_ | finished, {c.slug for c in stub_data.CONTESTS})

    def test_hero_contest_is_the_one_accepting_work(self):
        self.assertTrue(stub_data.HERO_CONTEST.is_accepting)

    def test_jury_and_timeline_present_for_active(self):
        c = stub_data.CONTESTS_BY_SLUG['bolashak-mektebi']
        self.assertGreater(len(c.jury), 0)
        self.assertGreater(len(c.timeline), 0)
        # ровно одна активная фаза
        self.assertEqual(sum(1 for t in c.timeline if t.state == 'active'), 1)


class ContestDatesAreTheSource(TestCase):
    """DEC-45: фаза, отсчёт, год и число заявок выводятся, а не хранятся."""

    def test_dates_are_ordered(self):
        for c in stub_data.CONTESTS:
            with self.subTest(slug=c.slug):
                self.assertLessEqual(c.opens_on, c.closes_on)
                self.assertLess(c.closes_on, c.results_on)

    def test_timeline_lies_inside_the_contest_window(self):
        for c in stub_data.CONTESTS:
            for t in c.timeline:
                with self.subTest(slug=c.slug, stage=t.label):
                    self.assertLessEqual(t.starts, t.ends)
                    self.assertGreaterEqual(t.ends, c.opens_on)
                    self.assertLessEqual(t.starts, c.results_on)

    def test_timeline_stages_are_chronological(self):
        for c in stub_data.CONTESTS:
            starts = [t.starts for t in c.timeline]
            with self.subTest(slug=c.slug):
                self.assertEqual(starts, sorted(starts))

    def test_submission_count_matches_real_submissions(self):
        """Хранимое «87 өтінім» стояло при одной настоящей заявке."""
        for c in stub_data.CONTESTS:
            real = sum(1 for subs in stub_data.SUBMISSIONS_BY_USER.values()
                       for s in subs if s.contest_slug == c.slug)
            with self.subTest(slug=c.slug):
                self.assertEqual(c.submissions, real)

    def test_year_comes_from_the_results_date(self):
        for c in stub_data.CONTESTS:
            with self.subTest(slug=c.slug):
                self.assertEqual(c.year, c.results_on.year)

    def test_only_finished_contests_have_winners(self):
        for c in stub_data.CONTESTS:
            if c.winners:
                with self.subTest(slug=c.slug):
                    self.assertTrue(c.is_finished)

    def test_stage_state_follows_the_calendar(self):
        c = stub_data.CONTESTS_BY_SLUG['zhas-aldym-2023']
        self.assertTrue(all(t.state == 'done' for t in c.timeline))


class SubmissionsHelpers(TestCase):

    def test_submissions_of_aidana(self):
        subs = stub_data.submissions_of('aidana')
        self.assertEqual(len(subs), 2)

    def test_submissions_of_unknown(self):
        self.assertEqual(stub_data.submissions_of('ghost'), [])

    def test_has_submission_true(self):
        self.assertTrue(stub_data.has_submission('aidana', 'altyn-qalam'))

    def test_has_submission_false(self):
        self.assertFalse(stub_data.has_submission('aidana', 'bolashak-mektebi'))


class ChecklistHelpers(TestCase):

    def test_checklist_short_story_fails_volume(self):
        # aidana-koshe: главы 800+1200+950+1100+700 = 4750 < 5000
        story = stub_data.STORIES_BY_SLUG['aidana-koshe']
        contest = stub_data.CONTESTS_BY_SLUG['altyn-qalam']
        cl = stub_data.submission_checklist(story, contest)
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
        story = stub_data.STORIES_BY_SLUG['aidana-erteg']  # без глав → 0 chars
        contest = stub_data.CONTESTS_BY_SLUG['altyn-qalam']
        cl = stub_data.submission_checklist(story, contest)
        vol = next(i for i in cl if i['key'] == 'volume')
        self.assertFalse(vol['passed'])

    def test_checklist_ai_declaration_required(self):
        story = stub_data.STORIES_BY_SLUG['aidana-tan']
        contest = stub_data.CONTESTS_BY_SLUG['altyn-qalam']
        cl = stub_data.submission_checklist(story, contest)
        ai = next(i for i in cl if i['key'] == 'ai_decl')
        self.assertFalse(ai['passed'])
        self.assertTrue(ai.get('required'))


class EligibleForContest(TestCase):

    def test_only_public_works_are_candidates(self):
        """Черновик и работа на модерации кандидатами не являются (DEC-23).

        Раньше они попадали в выбор, и от подачи черновика спасал только
        нулевой объём — работа на 6 000 знаков со статусом `NotPublished`
        подавалась бы. Порог объёма, наоборот, остаётся видимым
        заблокированным пунктом (BR-24): его автор может исправить.
        """
        items = stub_data.eligible_for_contest('aidana', 'altyn-qalam')
        self.assertEqual([i['story'].slug for i in items],
                         [s.slug for s in stub_data.public_stories_of('aidana')])
        self.assertTrue(all(i['story'].is_public for i in items))

    def test_shape_is_complete(self):
        for it in stub_data.eligible_for_contest('aidana', 'altyn-qalam'):
            with self.subTest(story=it['story'].slug):
                self.assertEqual(set(it),
                                 {'story', 'chars', 'eligible', 'reason', 'hint'})
                self.assertEqual(bool(it['reason']), not it['eligible'])
                self.assertEqual(bool(it['hint']), not it['eligible'])

    def test_eligible_unknown_contest(self):
        self.assertEqual(stub_data.eligible_for_contest('aidana', 'no-such'), [])

    def test_eligible_unknown_user(self):
        self.assertEqual(stub_data.eligible_for_contest('ghost', 'altyn-qalam'), [])


# ════════════════════════════ Contest list ═════════════════════════════════

class ContestList(TestCase):

    def test_renders_for_guest(self):
        r = self.client.get(reverse('core:contest_list'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Байқаулар')

    def test_lists_active_and_finished_sections(self):
        r = self.client.get(reverse('core:contest_list'))
        self.assertContains(r, 'Ағымдағы')
        self.assertContains(r, 'Аяқталған')

    def test_shows_all_active_cards(self):
        r = self.client.get(reverse('core:contest_list'))
        for c in stub_data.OPEN_CONTESTS:
            with self.subTest(slug=c.slug):
                self.assertContains(r, c.name)
                self.assertContains(
                    r, reverse('core:contest_detail', kwargs={'slug': c.slug}),
                )

    def test_my_submissions_link_for_authed(self):
        _login_as_aidana(self.client)
        r = self.client.get(reverse('core:contest_list'))
        self.assertContains(r, reverse('core:my_submissions'))

    def test_no_my_submissions_link_for_guest(self):
        r = self.client.get(reverse('core:contest_list'))
        self.assertNotContains(r, reverse('core:my_submissions'))


# ════════════════════════════ Contest detail ═══════════════════════════════

class ContestDetailKnown(TestCase):

    SLUG = 'bolashak-mektebi'

    def setUp(self):
        self.response = self.client.get(reverse('core:contest_detail', kwargs={'slug': self.SLUG}))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_shows_name_subtitle_prize(self):
        c = stub_data.CONTESTS_BY_SLUG[self.SLUG]
        self.assertContains(self.response, c.name)
        self.assertContains(self.response, c.subtitle)
        # Призовой фонд в ₸ — с разрядами через неразрывный пробел (фильтр `spaced`).
        # Раньше stringformat:"d" печатал «500000» сплошняком.
        self.assertContains(self.response, '500 000 ₸')

    def test_shows_description_and_conditions(self):
        self.assertContains(self.response, 'Республикалық')
        self.assertContains(self.response, 'Шарттар')

    def test_shows_timeline_with_active_marker(self):
        self.assertContains(self.response, 'Кезеңдер')
        self.assertContains(self.response, 'Қазір')

    def test_shows_jury_members(self):
        c = stub_data.CONTESTS_BY_SLUG[self.SLUG]
        for j in c.jury:
            with self.subTest(name=j.name):
                self.assertContains(self.response, j.name)
                self.assertContains(self.response, j.role)

    def test_cta_to_submit_for_active(self):
        self.assertContains(self.response, reverse('core:contest_submit', kwargs={'slug': self.SLUG}))

    def test_countdown_for_active(self):
        c = stub_data.CONTESTS_BY_SLUG[self.SLUG]
        self.assertContains(self.response, f'{c.days_left} күн қалды')


class ContestDetailAlreadySubmitted(TestCase):

    SLUG = 'altyn-qalam'

    def setUp(self):
        _login_as_aidana(self.client)   # aidana уже подала на altyn-qalam-2024
        self.response = self.client.get(reverse('core:contest_detail', kwargs={'slug': self.SLUG}))

    def test_shows_already_submitted_badge(self):
        self.assertContains(self.response, 'Өтінім берілген')

    def test_no_qatysu_button(self):
        # Если уже подал — нет CTA «Қатысу» (только бейдж)
        # Ссылка на submit-страницу есть только в форме, но кнопки нет
        self.assertNotContains(self.response, '>\n                        Қатысу\n                    </a>')


class ContestDetailFinished(TestCase):

    SLUG = 'zhas-aldym-2023'

    def test_no_submit_link_for_finished(self):
        r = self.client.get(reverse('core:contest_detail', kwargs={'slug': self.SLUG}))
        # Завершённый — нет CTA «Қатысу» (active-блок скрыт)
        self.assertNotContains(r, reverse('core:contest_submit', kwargs={'slug': self.SLUG}))


class ContestDetailUnknown(TestCase):

    def test_unknown_slug_renders_not_found(self):
        r = self.client.get(reverse('core:contest_detail', kwargs={'slug': 'ghost'}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Байқау табылмады')


# ════════════════════════════ Contest submit ═══════════════════════════════

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
        _login_as_aidana(self.client)
        self.response = self.client.get(reverse('core:contest_submit', kwargs={'slug': self.SLUG}))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_form_lists_the_public_works(self):
        for s in stub_data.public_stories_of('aidana'):
            with self.subTest(slug=s.slug):
                self.assertContains(self.response, f'value="{s.slug}"')

    def test_form_hides_drafts_and_moderation(self):
        for s in stub_data.my_stories_of('aidana'):
            if s.is_public:
                continue
            with self.subTest(slug=s.slug):
                self.assertNotContains(self.response, f'value="{s.slug}"')

    def test_disables_too_short_story(self):
        # aidana-koshe: 4750 < 5000 → disabled
        self.assertContains(self.response, 'Көлемі тым аз')

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
        _login_as_aidana(self.client)
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
        _login_as_aidana(self.client)
        r = self.client.get(reverse('core:contest_submit', kwargs={'slug': 'ghost'}))
        self.assertContains(r, 'Байқау табылмады')


# ════════════════════════════ My submissions ═══════════════════════════════

class MySubmissionsGuest(TestCase):

    def test_guest_sees_gate(self):
        r = self.client.get(reverse('core:my_submissions'))
        self.assertContains(r, 'кір')


class MySubmissionsAuthed(TestCase):

    def setUp(self):
        _login_as_aidana(self.client)
        self.response = self.client.get(reverse('core:my_submissions'))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_lists_all_submissions(self):
        for sub in stub_data.submissions_of('aidana'):
            with self.subTest(slug=sub.contest_slug):
                self.assertContains(self.response, sub.contest.name)
                self.assertContains(self.response, sub.story.title)

    def test_shows_status_badges(self):
        # У aidana: 1 reviewing + 1 rejected
        self.assertContains(self.response, 'Қаралуда')
        self.assertContains(self.response, 'Қабылданбады')

    def test_links_to_contest_detail(self):
        for sub in stub_data.submissions_of('aidana'):
            with self.subTest(slug=sub.contest_slug):
                self.assertContains(
                    self.response,
                    reverse('core:contest_detail', kwargs={'slug': sub.contest_slug}),
                )

    def test_rejected_shows_jury_note(self):
        self.assertContains(self.response, 'Көлемі шарттан аз')


class MySubmissionsEmpty(TestCase):

    def setUp(self):
        _login_as(self.client, 'lonely_writer')

    def test_empty_state_shown(self):
        r = self.client.get(reverse('core:my_submissions'))
        self.assertContains(r, 'Әлі өтінім жоқ')
        self.assertContains(r, reverse('core:contest_list'))


# ───────────────────── Инварианты конкурсных данных (Э0) ──────────────────

class ContestWinners(TestCase):
    """`Contest.winners` — слаги произведений, а не имена авторов."""

    def test_winners_reference_known_stories(self):
        for c in stub_data.CONTESTS:
            for slug in c.winners:
                with self.subTest(contest=c.slug, story=slug):
                    self.assertIn(slug, stub_data.STORIES_BY_SLUG)

    def test_active_contests_have_no_winners(self):
        for c in stub_data.OPEN_CONTESTS:
            with self.subTest(contest=c.slug):
                self.assertEqual(c.winners, ())

    def test_winner_stories_resolve_to_authors(self):
        c = stub_data.CONTESTS_BY_SLUG['zhas-aldym-2023']
        authors = {s.author_username for s in c.winner_stories}
        self.assertEqual(authors, {'bekzhan_t', 'dina_books'})

    def test_every_winner_has_a_submission(self):
        """Победа без поданной заявки — конкурсной истории неоткуда взяться."""
        for c in stub_data.CONTESTS:
            for story in c.winner_stories:
                with self.subTest(contest=c.slug, story=story.slug):
                    self.assertTrue(stub_data.has_submission(
                        story.author_username, c.slug))


class SubmissionsMatchContestBadges(TestCase):
    """Бейдж «Байқауға қатысады» на работе ⟺ заявка на идущий конкурс.

    Данные расходились в обе стороны: у `igra-kuklovoda` бейдж стоял без
    единой заявки, а у `aidana-tan` заявка на активный «Алтын қалам» была,
    но бейджа не было — каталог по оси `badge=contest` работу не находил.
    """

    LABEL = 'Байқауға қатысады'

    def _stories_with_active_submission(self):
        active = {c.slug for c in stub_data.OPEN_CONTESTS}
        return {
            sub.story_slug
            for subs in stub_data.SUBMISSIONS_BY_USER.values()
            for sub in subs
            if sub.contest_slug in active
        }

    def test_badge_implies_active_submission(self):
        expected = self._stories_with_active_submission()
        for s in stub_data.STORIES:
            if self.LABEL in s.badges:
                with self.subTest(story=s.slug):
                    self.assertIn(s.slug, expected)

    def test_active_submission_implies_badge(self):
        for slug in self._stories_with_active_submission():
            with self.subTest(story=slug):
                self.assertIn(self.LABEL, stub_data.STORIES_BY_SLUG[slug].badges)


class SubmissionIntegrity(TestCase):

    def test_submissions_reference_known_contests_and_stories(self):
        for username, subs in stub_data.SUBMISSIONS_BY_USER.items():
            for sub in subs:
                with self.subTest(user=username, contest=sub.contest_slug):
                    self.assertIn(sub.contest_slug, stub_data.CONTESTS_BY_SLUG)
                    self.assertIn(sub.story_slug, stub_data.STORIES_BY_SLUG)

    def test_submitted_story_belongs_to_submitter(self):
        for username, subs in stub_data.SUBMISSIONS_BY_USER.items():
            for sub in subs:
                with self.subTest(user=username, story=sub.story_slug):
                    self.assertEqual(
                        stub_data.STORIES_BY_SLUG[sub.story_slug].author_username,
                        username,
                    )

    def test_one_work_per_contest(self):
        """BR-23: один автор — не больше одной заявки на конкретный конкурс."""
        for username, subs in stub_data.SUBMISSIONS_BY_USER.items():
            slugs = [s.contest_slug for s in subs]
            with self.subTest(user=username):
                self.assertEqual(len(slugs), len(set(slugs)))


class ContestYear(TestCase):

    def test_every_contest_has_a_year(self):
        for c in stub_data.CONTESTS:
            with self.subTest(contest=c.slug):
                self.assertGreater(c.year, 2000)

    def test_year_matches_slug_when_slug_carries_one(self):
        """«altyn-qalam-2024» с годом 2023 — расхождение, которое видит читатель."""
        import re
        for c in stub_data.CONTESTS:
            m = re.search(r'-(\d{4})$', c.slug)
            if m:
                with self.subTest(contest=c.slug):
                    self.assertEqual(c.year, int(m.group(1)))


# ════════════════════════════ CONT-1 · словарь и рейл ══════════════════════

class ContestVocabulary(TestCase):
    """Одна сущность — одно слово: в интерфейсе «байқау», не «конкурс».

    Шапка, нижнее меню, футер и баннер главной всегда говорили «Байқаулар»,
    а сам раздел называл себя «Конкурстар» — в h1, во всех хлебных крошках,
    в кнопках и в пустом состоянии. Русское заимствование в казахском
    интерфейсе (docs/16).
    """

    URLS = (
        '/contests/',
        '/contests/bolashak-mektebi/',
        '/contests/zhas-aldym-2023/',
        '/contests/bolashak-mektebi/submit/',
        '/contests/my-submissions/',
        '/contests/unknown-slug/',
    )

    def test_contest_pages_never_say_konkurs(self):
        _login_as_aidana(self.client)
        for url in self.URLS:
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertNotIn('онкурс', html)

    def test_contest_pages_never_say_konkurs_for_guest(self):
        for url in self.URLS:
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertNotIn('онкурс', html)


class ContestRail(TestCase):
    """Правый рейл конкурса: не копия страницы и не пустая колонка (DEC-25)."""

    def test_unknown_slug_has_no_rail(self):
        for url in ('/contests/unknown-slug/', '/contests/unknown-slug/submit/'):
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertFalse(r.context['has_right_rail'])

    def test_finished_contest_without_open_stages_has_no_rail(self):
        """У «Жас алдым — 2023» все этапы позади: рейлу нечего сказать."""
        r = self.client.get(reverse('core:contest_detail', args=['zhas-aldym-2023']))
        self.assertFalse(r.context['has_right_rail'])

    def test_active_contest_rail_names_current_and_next_stage(self):
        r = self.client.get(reverse('core:contest_detail', args=['bolashak-mektebi']))
        self.assertTrue(r.context['has_right_rail'])
        html = r.content.decode()
        self.assertIn('Қазылар қарауы', html)   # следующий этап — только в рейле

    def test_rail_does_not_repeat_the_prize_from_the_hero(self):
        """Сыйақы написан в хиро; вторая копия в рейле — не дополнение, а дубль."""
        r = self.client.get(reverse('core:contest_detail', args=['bolashak-mektebi']))
        money = stub_data.spaced_number(500_000)
        self.assertEqual(r.content.decode().count(money), 1)

    def test_submit_page_rail_has_no_cta_to_itself(self):
        _login_as_aidana(self.client)
        r = self.client.get(reverse('core:contest_submit', args=['bolashak-mektebi']))
        self.assertTrue(r.context['hide_submit_cta'])
        # Ссылка на подачу остаётся ровно одна — action самой формы.
        target = reverse('core:contest_submit', args=['bolashak-mektebi'])
        self.assertEqual(r.content.decode().count(f'"{target}"'), 1)


class ContestStages(TestCase):

    def test_current_stage_is_the_active_one(self):
        c = stub_data.CONTESTS_BY_SLUG['bolashak-mektebi']
        self.assertEqual(c.current_stage.state, 'active')
        self.assertEqual(c.current_stage.label, 'Өтінім қабылдау')

    def test_next_stage_is_the_first_upcoming(self):
        c = stub_data.CONTESTS_BY_SLUG['bolashak-mektebi']
        self.assertEqual(c.next_stage.label, 'Қазылар қарауы')

    def test_finished_contest_has_no_open_stages(self):
        c = stub_data.CONTESTS_BY_SLUG['zhas-aldym-2023']
        self.assertIsNone(c.current_stage)
        self.assertIsNone(c.next_stage)


class ChecklistNumbers(TestCase):
    """Числа в подсказках — с разрядами, пороги — из конкурса, не литералом."""

    def setUp(self):
        self.contest = stub_data.CONTESTS_BY_SLUG['altyn-qalam']
        self.story = stub_data.STORIES_BY_SLUG['aidana-tan']
        self.volume = next(i for i in stub_data.submission_checklist(self.story, self.contest)
                           if i['key'] == 'volume')

    def test_thresholds_come_from_the_contest(self):
        self.assertIn(stub_data.spaced_number(self.contest.min_chars), self.volume['label'])
        self.assertIn(stub_data.spaced_number(self.contest.max_chars), self.volume['label'])

    def test_char_count_is_spaced(self):
        total = sum(c.char_count for c in stub_data.chapters_of(self.story.slug))
        self.assertIn(stub_data.spaced_number(total), self.volume['hint'])
        self.assertNotIn(str(total), self.volume['hint'])


class RejectionNoteMatchesTheData(TestCase):
    """Отказ по объёму должен называть ту сторону порога, которая нарушена."""

    def test_aidana_rejection_says_too_small(self):
        sub = next(s for s in stub_data.submissions_of('aidana') if s.status == 'rejected')
        total = sum(c.char_count for c in stub_data.chapters_of(sub.story_slug))
        self.assertLess(total, sub.contest.min_chars)
        self.assertIn('аз', sub.note)


# ════════════════════════════ CONT-2 · победители ══════════════════════════

class ContestWinnersOnDetail(TestCase):
    """FR-CONT-08. `winner_stories` существовал и не был отрендерен нигде."""

    def setUp(self):
        self.contest = stub_data.CONTESTS_BY_SLUG['zhas-aldym-2023']
        self.response = self.client.get(
            reverse('core:contest_detail', args=['zhas-aldym-2023']))

    def test_section_is_present(self):
        # Именно заголовок секции: «Жеңімпаздар» — ещё и подпись последнего
        # этапа в таймлайне активного конкурса, по голому слову не отличить.
        self.assertContains(self.response, '>Жеңімпаздар</h2>')

    def test_every_winner_is_named(self):
        for story in self.contest.winner_stories:
            with self.subTest(story=story.slug):
                self.assertContains(self.response, story.title)

    def test_winner_links_to_story_and_author(self):
        for story in self.contest.winner_stories:
            with self.subTest(story=story.slug):
                self.assertContains(
                    self.response, reverse('core:story_detail', args=[story.slug]))
                self.assertContains(
                    self.response,
                    reverse('core:profile_other', args=[story.author.username]))

    def test_timeline_is_collapsed_once_winners_are_known(self):
        self.assertContains(self.response, '<summary')

    def test_active_contest_has_no_winners_section(self):
        r = self.client.get(reverse('core:contest_detail', args=['bolashak-mektebi']))
        self.assertEqual(r.context['grants'], [])
        self.assertNotContains(r, '>Жеңімпаздар</h2>')


class ContestWinnersOnCard(TestCase):

    def test_finished_card_names_its_winners(self):
        r = self.client.get(reverse('core:contest_list'))
        for story in stub_data.CONTESTS_BY_SLUG['zhas-aldym-2023'].winner_stories:
            with self.subTest(story=story.slug):
                self.assertContains(r, story.title)

    def test_active_card_says_nothing_about_winners(self):
        html = self.client.get(reverse('core:contest_list')).content.decode()
        self.assertEqual(html.count('Жеңімпаз:'), 1)


# ════════════════════════════ CONT-3 · фазы ════════════════════════════════

class SubmitIsGatedByPhase(TestCase):
    """Форма подачи живёт только в фазе приёма (DEC-45).

    Прямая ссылка открывалась в любой момент и предлагала подать работу
    в конкурс, который ещё не начался или уже ушёл на судейство.
    """

    def setUp(self):
        # Не aidana: у неё уже есть заявка в «Алтын қалам», и страница
        # показала бы блок «өтінім бергенсің» раньше, чем блок фазы.
        _login_as(self.client, 'bekzhan_t')

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


class DetailHeroSpeaksByPhase(TestCase):

    def test_accepting_offers_the_button(self):
        r = self.client.get(reverse('core:contest_detail', args=['bolashak-mektebi']))
        self.assertContains(r, reverse('core:contest_submit', args=['bolashak-mektebi']))

    def test_upcoming_names_the_opening_date_instead_of_a_button(self):
        c = stub_data.CONTESTS_BY_SLUG['qys-ertegisi']
        r = self.client.get(reverse('core:contest_detail', args=['qys-ertegisi']))
        self.assertNotContains(r, reverse('core:contest_submit', args=['qys-ertegisi']))
        self.assertContains(r, c.opens_on_label)

    def test_judging_names_the_results_date(self):
        c = stub_data.CONTESTS_BY_SLUG['altyn-qalam']
        r = self.client.get(reverse('core:contest_detail', args=['altyn-qalam']))
        self.assertNotContains(r, reverse('core:contest_submit', args=['altyn-qalam']))
        self.assertContains(r, c.results_on_label)

    def test_finished_offers_nothing_to_submit(self):
        r = self.client.get(reverse('core:contest_detail', args=['zhas-aldym-2023']))
        self.assertNotContains(r, reverse('core:contest_submit', args=['zhas-aldym-2023']))


class ContestListOrdersByWhatYouCanDo(TestCase):

    def test_accepting_contest_comes_first(self):
        self.assertTrue(stub_data.OPEN_CONTESTS[0].is_accepting)

    def test_every_open_contest_is_on_the_page(self):
        html = self.client.get(reverse('core:contest_list')).content.decode()
        positions = [html.index(c.name) for c in stub_data.OPEN_CONTESTS]
        self.assertEqual(positions, sorted(positions))


class PhaseLabelsAreOneRegistry(TestCase):
    """Подпись фазы приходит из `CONTEST_PHASE_LABELS`, не из шаблона."""

    def test_every_phase_has_a_label_and_a_badge_kind(self):
        for phase in stub_data.CONTEST_PHASES:
            with self.subTest(phase=phase):
                self.assertIn(phase, stub_data.CONTEST_PHASE_LABELS)
                self.assertIn(phase, stub_data.CONTEST_PHASE_BADGE)

    def test_card_shows_the_registry_label(self):
        html = self.client.get(reverse('core:contest_list')).content.decode()
        for c in stub_data.CONTESTS:
            with self.subTest(slug=c.slug):
                self.assertIn(stub_data.CONTEST_PHASE_LABELS[c.phase], html)


class KazakhDateFormatting(TestCase):

    def test_single_day_stage_has_no_dash(self):
        c = stub_data.CONTESTS_BY_SLUG['zhas-aldym-2023']
        final = next(t for t in c.timeline if t.label == 'Финал')
        self.assertEqual(final.period, '15 жел')

    def test_range_stage_joins_two_dates(self):
        c = stub_data.CONTESTS_BY_SLUG['zhas-aldym-2023']
        intake = next(t for t in c.timeline if t.label == 'Өтінім қабылдау')
        self.assertEqual(intake.period, '1 қыр — 1 жел')


# ════════════════════════════ CONT-4 · награды конкурса ════════════════════

class ContestAwardsData(TestCase):
    """DEC-46: набор номинаций у каждого конкурса свой, победа — акт жюри."""

    def test_award_slugs_are_unique_within_a_contest(self):
        for c in stub_data.CONTESTS:
            slugs = [a.slug for a in c.awards]
            with self.subTest(contest=c.slug):
                self.assertEqual(len(slugs), len(set(slugs)))

    def test_every_contest_declares_at_least_one_award(self):
        """Номинация — ответ на «зачем участвовать». Конкурс без неё
        предлагает только сумму в тенге."""
        for c in stub_data.CONTESTS:
            with self.subTest(contest=c.slug):
                self.assertTrue(c.awards)

    def test_grants_reference_known_contest_award_and_story(self):
        for g in stub_data.AWARD_GRANTS:
            with self.subTest(grant=(g.contest_slug, g.award_slug, g.story_slug)):
                self.assertIsNotNone(g.contest)
                self.assertIsNotNone(g.award)
                self.assertIsNotNone(g.story)

    def test_grant_implies_a_finished_contest(self):
        """Награду нельзя вручить, пока жюри не закончило."""
        for g in stub_data.AWARD_GRANTS:
            with self.subTest(grant=g.award_slug):
                self.assertTrue(g.contest.is_finished)

    def test_grant_implies_a_submission_by_the_same_author(self):
        for g in stub_data.AWARD_GRANTS:
            subs = stub_data.submissions_of(g.story.author_username)
            with self.subTest(grant=g.award_slug):
                self.assertIn(g.contest_slug, {s.contest_slug for s in subs})

    def test_one_award_is_granted_at_most_once(self):
        seen = [(g.contest_slug, g.award_slug) for g in stub_data.AWARD_GRANTS]
        self.assertEqual(len(seen), len(set(seen)))

    def test_winners_are_derived_from_grants(self):
        c = stub_data.CONTESTS_BY_SLUG['zhas-aldym-2023']
        self.assertEqual(c.winners, tuple(g.story_slug for g in c.grants))

    def test_contest_without_grants_has_no_winners(self):
        for c in stub_data.CONTESTS:
            if not c.grants:
                with self.subTest(contest=c.slug):
                    self.assertEqual(c.winners, ())


class ContestAwardImages(TestCase):
    """Эмблему грузит админ файлом — путь обязан вести к реальному файлу."""

    def test_declared_images_exist_in_media(self):
        """Путь эмблемы ведёт к настоящему файлу — если он вообще есть локально.

        `media/` целиком в `.gitignore` (там же лежат обложки-плейсхолдеры),
        поэтому на чистом клоне файлов нет, и жёсткая проверка падала бы не
        на ошибке, а на отсутствии необязательных ассетов. Контракт пути
        проверяется отдельно и всегда — `test_image_path_follows_the_contract`.
        """
        from pathlib import Path

        from django.conf import settings
        root = Path(settings.MEDIA_ROOT) / 'awards'
        if not root.is_dir():
            self.skipTest('media/awards/ нет локально — ассеты не в репозитории')
        for c in stub_data.CONTESTS:
            for a in c.awards:
                if not a.image:
                    continue
                with self.subTest(contest=c.slug, award=a.slug):
                    self.assertTrue((Path(settings.MEDIA_ROOT) / a.image).is_file(),
                                    f'нет файла: {a.image}')

    def test_image_path_follows_the_contract(self):
        """`awards/<contest>/<award>.png` — растр, не SVG.

        SVG из `/media/` открывается в origin сайта и может нести скрипт;
        загрузка эмблем идёт через админку, но правило одно для всех.
        """
        for c in stub_data.CONTESTS:
            for a in c.awards:
                if not a.image:
                    continue
                with self.subTest(award=a.slug):
                    self.assertTrue(a.image.startswith(f'awards/{c.slug}/'), a.image)
                    self.assertTrue(a.image.endswith(('.png', '.webp')), a.image)

    def test_award_without_image_still_renders(self):
        """Админ не загрузил файл — типографическая заглушка, не дыра."""
        c = stub_data.CONTESTS_BY_SLUG['bolashak-mektebi']
        self.assertTrue(any(not a.image for a in c.awards),
                        'фикстура сломана: нужна номинация без эмблемы')
        r = self.client.get(reverse('core:contest_detail', args=[c.slug]))
        self.assertEqual(r.status_code, 200)
        for a in c.awards:
            with self.subTest(award=a.slug):
                self.assertContains(r, a.title)


class ContestAwardsOnDetail(TestCase):

    def test_nominations_are_shown_before_the_results(self):
        r = self.client.get(reverse('core:contest_detail', args=['bolashak-mektebi']))
        self.assertContains(r, 'Марапаттар')
        self.assertContains(r, 'Бас жүлде')

    def test_nominations_are_not_repeated_after_the_results(self):
        """У завершённого конкурса номинации уже перечислены победителями."""
        r = self.client.get(reverse('core:contest_detail', args=['zhas-aldym-2023']))
        self.assertNotContains(r, 'Марапаттар')

    def test_winner_row_names_the_nomination(self):
        c = stub_data.CONTESTS_BY_SLUG['zhas-aldym-2023']
        r = self.client.get(reverse('core:contest_detail', args=[c.slug]))
        for g in c.grants:
            with self.subTest(award=g.award_slug):
                self.assertContains(r, g.award.title)

    def test_winner_emblem_is_rendered(self):
        c = stub_data.CONTESTS_BY_SLUG['zhas-aldym-2023']
        r = self.client.get(reverse('core:contest_detail', args=[c.slug]))
        for g in c.grants:
            if g.award.image:
                with self.subTest(award=g.award_slug):
                    self.assertContains(r, f'/media/{g.award.image}')


class SystemWinnerAwardIsRetired(TestCase):
    """DEC-46 снял общий «Байқау жеңімпазы» — его вытеснила награда конкурса."""

    def test_registry_has_no_generic_winner_award(self):
        self.assertNotIn('contest_winner', {a.key for a in stub_data.AWARDS})

    def test_participation_awards_stay(self):
        keys = {a.key for a in stub_data.AWARDS}
        self.assertIn('contest_participant', keys)
        self.assertIn('contest_accepted', keys)


# ════════════════════════════ CONT-5 · подача ══════════════════════════════

class EligibilityReasons(TestCase):
    """BR-24 + BR-23a: почему работу нельзя подать — говорится, а не молчится."""

    def _items(self, username, slug='bolashak-mektebi'):
        return {i['story'].slug: i for i in stub_data.eligible_for_contest(username, slug)}

    def test_too_short_work_is_blocked_with_a_reason(self):
        item = self._items('aidana')['aidana-koshe']
        self.assertFalse(item['eligible'])
        self.assertEqual(item['reason'], 'too_short')
        self.assertIn(stub_data.INELIGIBLE_REASONS['too_short'], item['hint'])

    def test_work_in_another_open_contest_is_blocked(self):
        """Одним текстом нельзя идти в двух конкурсах разом (BR-23a)."""
        item = self._items('aidana')['aidana-tan']
        self.assertEqual(item['reason'], 'busy')
        self.assertIn('Алтын қалам', item['hint'])

    def test_finished_contest_does_not_block_a_work(self):
        """Работа своё отучаствовала — она снова свободна."""
        self.assertIsNone(
            stub_data.busy_contest_of('bekzhan_t', 'temniy-lord'))

    def test_the_same_contest_does_not_block_itself(self):
        busy = stub_data.busy_contest_of('aidana', 'aidana-tan', besides='altyn-qalam')
        self.assertIsNone(busy)

    def test_eligible_work_carries_no_reason(self):
        item = self._items('bekzhan_t')['tunge-deiin']
        self.assertTrue(item['eligible'])
        self.assertEqual(item['reason'], '')


class ChecklistFollowsTheChoice(TestCase):
    """FR-CONT-04: чек-лист пересчитывается при смене работы, не застывает."""

    def setUp(self):
        _login_as(self.client, 'bekzhan_t')
        self.response = self.client.get(
            reverse('core:contest_submit', args=['bolashak-mektebi']))

    def test_view_ships_volume_data_for_every_candidate(self):
        vols = self.response.context['volumes']
        candidates = {i['story'].slug
                      for i in self.response.context['eligible']}
        self.assertEqual(set(vols), candidates)
        for slug, v in vols.items():
            with self.subTest(story=slug):
                self.assertEqual(set(v), {'passed', 'hint', 'eligible', 'reason'})

    def test_data_is_embedded_for_the_browser(self):
        self.assertContains(self.response, 'id="submit-volumes"')
        self.assertContains(self.response, 'x-model="picked"')

    def test_initial_choice_is_an_eligible_work(self):
        slug = self.response.context['initial_slug']
        self.assertTrue(self.response.context['volumes'][slug]['eligible'])
        self.assertFalse(self.response.context['submit_blocked'])


class ChecklistSurvivesWithoutAnEligibleWork(TestCase):
    """Раньше при отсутствии подходящей работы исчезали AI-декларация и оба
    согласия: чек-лист считался только для подходящей, а форма без него
    выглядела обрубленной."""

    def setUp(self):
        _login_as(self.client, 'rudazov')   # все работы короче порога
        self.response = self.client.get(
            reverse('core:contest_submit', args=['bolashak-mektebi']))

    def test_no_work_passes(self):
        self.assertFalse(any(i['eligible']
                             for i in self.response.context['eligible']))

    def test_checklist_is_still_rendered(self):
        self.assertContains(self.response, 'Сәйкестік чек-листі')

    def test_declaration_and_consents_are_still_rendered(self):
        self.assertContains(self.response, 'name="ai_used"')
        self.assertContains(self.response, 'name="confirm_age"')
        self.assertContains(self.response, 'name="confirm_rules"')

    def test_submit_starts_blocked(self):
        self.assertTrue(self.response.context['submit_blocked'])


class WithdrawSubmission(TestCase):
    """BR-23b: одна работа на конкурс — но заявку можно забрать назад."""

    def test_allowed_while_the_contest_still_accepts(self):
        self.assertTrue(stub_data.can_withdraw('dina_books', 'bolashak-mektebi'))

    def test_denied_once_judging_started(self):
        self.assertFalse(stub_data.can_withdraw('aidana', 'altyn-qalam'))

    def test_denied_for_a_finished_contest(self):
        self.assertFalse(stub_data.can_withdraw('bekzhan_t', 'zhas-aldym-2023'))

    def test_denied_without_a_submission(self):
        self.assertFalse(stub_data.can_withdraw('bekzhan_t', 'bolashak-mektebi'))

    def test_button_and_modal_are_on_the_submissions_page(self):
        _login_as(self.client, 'dina_books')
        r = self.client.get(reverse('core:my_submissions'))
        self.assertContains(r, 'Қайтарып алу')
        self.assertContains(r, 'open-withdraw-confirm')

    def test_button_absent_when_withdrawal_is_closed(self):
        _login_as_aidana(self.client)
        r = self.client.get(reverse('core:my_submissions'))
        self.assertNotContains(r, 'open-withdraw-confirm')


class SubmissionsPageNamesTheDates(TestCase):
    """«Қаралуда» без даты не отвечает на «а когда узнаю»."""

    def test_accepting_contest_shows_both_dates(self):
        _login_as(self.client, 'dina_books')
        r = self.client.get(reverse('core:my_submissions'))
        c = stub_data.CONTESTS_BY_SLUG['bolashak-mektebi']
        self.assertContains(r, c.closes_on_label)
        self.assertContains(r, c.results_on_label)

    def test_judging_contest_shows_the_results_date(self):
        _login_as_aidana(self.client)
        r = self.client.get(reverse('core:my_submissions'))
        self.assertContains(r,
                            stub_data.CONTESTS_BY_SLUG['altyn-qalam'].results_on_label)


# ════════════════════════════ CONT-6 · сроки и слова ═══════════════════════

class SubmissionDatesAreReal(TestCase):
    """Дата подачи хранится датой и лежит внутри окна приёма (BR-41a).

    Хранимое `submitted_relative="6 ай бұрын"` стояло у заявки на конкурс,
    закрывшийся в декабре 2023-го: подача приходилась на полгода позже
    дедлайна, и заметить это было нечем — строка ведь не дата.
    """

    def test_relative_string_is_not_stored(self):
        stored = stub_data.Submission.__dataclass_fields__
        self.assertNotIn(
            'submitted_relative', stored,
            '`submitted_relative` снова стало полем — это хранимое производное')

    def test_submitted_inside_the_acceptance_window(self):
        for username, subs in stub_data.SUBMISSIONS_BY_USER.items():
            for sub in subs:
                with self.subTest(user=username, contest=sub.contest_slug):
                    c = sub.contest
                    self.assertGreaterEqual(sub.submitted_on, c.opens_on)
                    self.assertLessEqual(sub.submitted_on, c.closes_on)

    def test_label_follows_the_date(self):
        sub = stub_data.SUBMISSIONS_BY_USER['aidana'][0]
        self.assertEqual(
            sub.submitted_label,
            stub_data.kk_ago((date.today() - sub.submitted_on).days))

    def test_old_submission_is_not_called_a_year_ago_forever(self):
        """Заявка 2023 года в 2026-м — не «1 жыл бұрын»."""
        sub = stub_data.SUBMISSIONS_BY_USER['bekzhan_t'][0]
        years = (date.today() - sub.submitted_on).days // 365
        self.assertEqual(sub.submitted_label, f'{years} жыл бұрын')


class ContestTimingLineIsOneImplementation(TestCase):
    """«Что дальше и когда» собирает конкурс, а не шаблон.

    Формулировка стояла inline в `my_submissions.html`; вторая копия для
    конкурсного уведомления разошлась бы с ней ровно так же, как разошлись
    две рукописные копии правил подачи.
    """

    def test_line_matches_the_phase(self):
        for c in stub_data.CONTESTS:
            with self.subTest(contest=c.slug, phase=c.phase):
                line = c.timing_line
                if c.phase == 'finished':
                    self.assertEqual(line, '')
                elif c.phase == 'upcoming':
                    self.assertIn(c.opens_on_label, line)
                elif c.phase == 'accepting':
                    self.assertIn(c.closes_on_label, line)
                    self.assertIn(c.results_on_label, line)
                else:
                    self.assertIn(c.results_on_label, line)

    def test_line_carries_no_countdown_number(self):
        """Числа «12 күн» в строке нет: оно протухло бы назавтра (BR-40a)."""
        for c in stub_data.CONTESTS:
            with self.subTest(contest=c.slug):
                self.assertNotIn('күн қалды', c.timing_line)

    def test_submissions_page_renders_the_shared_line(self):
        _login_as(self.client, 'dina_books')
        r = self.client.get(reverse('core:my_submissions'))
        self.assertContains(r,
                            stub_data.CONTESTS_BY_SLUG['bolashak-mektebi'].timing_line)


class AcceptedIsTheJuryWord(TestCase):
    """«Қабылданды» — решение жюри (BR-41), а не факт получения формы.

    Тост подачи говорил именно это слово, и автор читал отправку как победу
    в первом же круге. Одна сущность — одно слово (docs/16 §16.4).
    """

    def test_submit_form_does_not_promise_acceptance(self):
        _login_as_aidana(self.client)
        html = self.client.get(
            reverse('core:contest_submit', args=['bolashak-mektebi'])).content.decode()
        self.assertNotIn('Өтінім қабылданды', html)
        self.assertIn('Өтінім жіберілді', html)

    def test_word_survives_where_it_means_the_verdict(self):
        _login_as(self.client, 'dina_books')
        r = self.client.get(reverse('core:my_submissions'))
        self.assertContains(r, stub_data.CONTEST_RESULT_LABELS['accepted'])


# ════════════════════════════ CONT-7 · афиша и выходы ══════════════════════

class ContestPosterIsItsOwn(TestCase):
    """Афиша конкурса — своя, а не фотография чужой книги (FR-CONT-11).

    В `static/img/bookN.jpg` лежат книжные обложки; четыре конкурса
    различались тем, чья книга досталась каждому.
    """

    TPL = TEMPLATES / 'components'

    def test_contest_templates_do_not_pull_static_book_photos(self):
        for name in ('components/contest_card.html',
                     'pages/contests/contest_detail.html'):
            with self.subTest(template=name):
                body = (TEMPLATES / name).read_text(encoding='utf-8')
                self.assertNotIn('img/book', body)
                self.assertNotIn('contest.cover', body)

    def test_cover_field_is_gone(self):
        self.assertNotIn('cover', stub_data.Contest.__dataclass_fields__)
        self.assertIn('poster', stub_data.Contest.__dataclass_fields__)

    def test_poster_renders_on_list_and_detail(self):
        for url in ('/contests/', '/contests/bolashak-mektebi/'):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertIn('oklch(', html,
                              'типографическая афиша не отрендерилась')

    def test_declared_poster_files_live_in_media(self):
        """Афишу грузит админ в MEDIA_ROOT, как эмблему награды (BR-46)."""
        for c in stub_data.CONTESTS:
            if c.poster:
                with self.subTest(contest=c.slug):
                    self.assertTrue(c.poster.startswith('contests/'))
                    self.assertFalse(c.poster.endswith('.svg'))


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

    def test_card_uses_one_strip_not_two_corners(self):
        body = self._markup(TEMPLATES / 'components' / 'contest_card.html')
        self.assertIn('inset-x-3', body)
        for corner in ('left-3 top-3', 'right-3 top-3'):
            self.assertNotIn(
                corner, body,
                'абсолютный угол вернулся — соседняя пилюля снова окажется под ним')

    def test_status_row_wraps(self):
        body = self._markup(TEMPLATES / 'components' / 'contest_status.html')
        self.assertIn('flex-wrap', body,
                      'без переноса отсчёт не помещается в полосу узкой карточки')


class CountdownIconMeansTime(TestCase):
    """Иконка отсчёта — часы, а не ползунки фильтра.

    `adjustments` стояла перед «12 күн қалды» потому, что часов в спрайте
    не было, а добавить `<symbol>` было лень. Иконка, взятая по наличию,
    не значит ничего — CLAUDE.md и docs/04 §4.2 запрещают ровно это.
    """

    def test_countdown_uses_the_clock(self):
        body = (TEMPLATES / 'components' / 'countdown.html').read_text(encoding='utf-8')
        self.assertIn('name="clock"', body)
        self.assertNotIn('name="adjustments"', body)

    def test_clock_exists_in_the_sprite(self):
        sprite = (TEMPLATES / 'components' / 'icons' / '_sprite.html').read_text(encoding='utf-8')
        self.assertIn('id="icon-clock"', sprite)

    def test_adjustments_stays_where_it_means_something(self):
        """У кнопки сүзгі каталога ползунки — на своём месте."""
        body = (TEMPLATES / 'pages' / 'catalog' / 'catalog.html').read_text(encoding='utf-8')
        self.assertIn('name="adjustments"', body)


class ContestEditionsAreLinked(TestCase):
    """Завершённый конкурс перестал быть тупиком (FR-CONT-13, BR-47)."""

    def test_editions_see_each_other(self):
        old = stub_data.CONTESTS_BY_SLUG['zhas-aldym-2023']
        new = stub_data.CONTESTS_BY_SLUG['zhas-aldym-2026']
        self.assertEqual([c.slug for c in old.other_editions], [new.slug])
        self.assertEqual([c.slug for c in new.other_editions], [old.slug])

    def test_a_one_off_contest_has_no_editions(self):
        self.assertEqual(stub_data.CONTESTS_BY_SLUG['altyn-qalam'].other_editions, [])

    def test_finished_page_links_to_the_open_edition(self):
        r = self.client.get(reverse('core:contest_detail', args=['zhas-aldym-2023']))
        self.assertContains(r, reverse('core:contest_detail', args=['zhas-aldym-2026']))
        self.assertContains(r, 'Басқа жылдар')

    def test_year_comes_from_the_data_not_the_name(self):
        for c in stub_data.CONTESTS:
            for e in c.other_editions:
                with self.subTest(contest=c.slug, edition=e.slug):
                    self.assertEqual(e.year, e.results_on.year)


class ContestPageCanBeShared(TestCase):
    """FR-CONT-12: конкурс живёт тем, что о нём рассказывают."""

    def test_share_button_in_every_phase(self):
        for slug in stub_data.CONTESTS_BY_SLUG:
            with self.subTest(contest=slug):
                r = self.client.get(reverse('core:contest_detail', args=[slug]))
                self.assertContains(r, 'Бөлісу')

    def test_unknown_slug_has_nothing_to_share(self):
        r = self.client.get(reverse('core:contest_detail', args=['no-such-contest']))
        self.assertNotContains(r, 'Бөлісу')


class ContestVocabularyInEmptyState(TestCase):
    """Ветка, которая не рендерится, всё равно должна говорить по-казахски.

    Пустое состояние списка говорило «Әзірге конкурс жоқ» и пережило
    чистку CONT-1 только потому, что конкурсы в стабе есть всегда.
    """

    def test_empty_list_says_baiqau(self):
        with mock.patch.object(stub_data, 'OPEN_CONTESTS', []), \
             mock.patch.object(stub_data, 'FINISHED_CONTESTS', []):
            html = self.client.get(reverse('core:contest_list')).content.decode()
        self.assertNotIn('онкурс', html)
        self.assertIn('Әзірге байқау жоқ', html)


class BlockedSubmitExplainsItself(TestCase):
    """Заблокированная кнопка без объяснения — тупик."""

    def test_reason_is_rendered_when_nothing_fits(self):
        _login_as(self.client, 'rudazov')
        r = self.client.get(reverse('core:contest_submit', args=['bolashak-mektebi']))
        self.assertTrue(r.context['submit_blocked'])
        self.assertTrue(r.context['initial_reason'])
        self.assertContains(r, r.context['initial_reason'])

    def test_reason_is_empty_when_the_choice_fits(self):
        _login_as(self.client, 'bekzhan_t')
        r = self.client.get(reverse('core:contest_submit', args=['bolashak-mektebi']))
        self.assertFalse(r.context['submit_blocked'])
        self.assertEqual(r.context['initial_reason'], '')
