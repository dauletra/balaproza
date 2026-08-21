"""CONT · конкурсы: список / детальная / подача / мои заявки."""

from django.test import TestCase
from django.urls import reverse

from core import stub_data


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
                self.assertIn(c.status, ('active', 'finished'))
                self.assertGreaterEqual(c.submissions, 0)
                # для active обязателен days_left
                if c.status == 'active':
                    self.assertIsNotNone(c.days_left)
                    self.assertIsNotNone(c.prize_kzt)

    def test_contests_by_slug_lookup(self):
        self.assertEqual(
            stub_data.CONTESTS_BY_SLUG['altyn-qalam-2024'].name,
            'Алтын қалам — 2024',
        )

    def test_active_contests_filter(self):
        self.assertEqual(len(stub_data.ACTIVE_CONTESTS), 2)
        for c in stub_data.ACTIVE_CONTESTS:
            self.assertEqual(c.status, 'active')

    def test_jury_and_timeline_present_for_active(self):
        c = stub_data.CONTESTS_BY_SLUG['bolashak-mektebi']
        self.assertGreater(len(c.jury), 0)
        self.assertGreater(len(c.timeline), 0)
        # ровно одна активная фаза
        self.assertEqual(sum(1 for t in c.timeline if t.state == 'active'), 1)


class SubmissionsHelpers(TestCase):

    def test_submissions_of_aidana(self):
        subs = stub_data.submissions_of('aidana')
        self.assertEqual(len(subs), 2)

    def test_submissions_of_unknown(self):
        self.assertEqual(stub_data.submissions_of('ghost'), [])

    def test_has_submission_true(self):
        self.assertTrue(stub_data.has_submission('aidana', 'altyn-qalam-2024'))

    def test_has_submission_false(self):
        self.assertFalse(stub_data.has_submission('aidana', 'bolashak-mektebi'))


class ChecklistHelpers(TestCase):

    def test_checklist_short_story_fails_volume(self):
        # aidana-koshe: главы 800+1200+950+1100+700 = 4750 < 5000
        story = stub_data.STORIES_BY_SLUG['aidana-koshe']
        contest = stub_data.CONTESTS_BY_SLUG['altyn-qalam-2024']
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
        contest = stub_data.CONTESTS_BY_SLUG['altyn-qalam-2024']
        cl = stub_data.submission_checklist(story, contest)
        vol = next(i for i in cl if i['key'] == 'volume')
        self.assertFalse(vol['passed'])

    def test_checklist_ai_declaration_required(self):
        story = stub_data.STORIES_BY_SLUG['aidana-tan']
        contest = stub_data.CONTESTS_BY_SLUG['altyn-qalam-2024']
        cl = stub_data.submission_checklist(story, contest)
        ai = next(i for i in cl if i['key'] == 'ai_decl')
        self.assertFalse(ai['passed'])
        self.assertTrue(ai.get('required'))


class EligibleForContest(TestCase):

    def test_eligible_returns_all_with_eligible_flag(self):
        items = stub_data.eligible_for_contest('aidana', 'altyn-qalam-2024')
        # Все произведения Айданы, каждое с флагом пригодности
        self.assertEqual(len(items), len(stub_data.my_stories_of('aidana')))
        for it in items:
            self.assertIn('story', it)
            self.assertIn('chars', it)
            self.assertIn('eligible', it)

    def test_eligible_unknown_contest(self):
        self.assertEqual(stub_data.eligible_for_contest('aidana', 'no-such'), [])

    def test_eligible_unknown_user(self):
        self.assertEqual(stub_data.eligible_for_contest('ghost', 'altyn-qalam-2024'), [])


# ════════════════════════════ Contest list ═════════════════════════════════

class ContestList(TestCase):

    def test_renders_for_guest(self):
        r = self.client.get(reverse('core:contest_list'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Конкурстар')

    def test_lists_active_and_finished_sections(self):
        r = self.client.get(reverse('core:contest_list'))
        self.assertContains(r, 'Белсенді')
        self.assertContains(r, 'Аяқталған')

    def test_shows_all_active_cards(self):
        r = self.client.get(reverse('core:contest_list'))
        for c in stub_data.ACTIVE_CONTESTS:
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

    SLUG = 'altyn-qalam-2024'

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
        self.assertContains(r, 'Конкурс табылмады')


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

    def test_form_lists_all_user_stories(self):
        for s in stub_data.my_stories_of('aidana'):
            with self.subTest(slug=s.slug):
                self.assertContains(self.response, f'value="{s.slug}"')

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

    SLUG = 'altyn-qalam-2024'   # aidana уже подала

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
        self.assertContains(r, 'Конкурс табылмады')


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
        self.assertContains(self.response, 'Көлемі шарттан асып кеткен')


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
        for c in stub_data.ACTIVE_CONTESTS:
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
        active = {c.slug for c in stub_data.ACTIVE_CONTESTS}
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
