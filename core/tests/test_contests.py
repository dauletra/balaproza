"""CONT · конкурс как объект и его страница.

Правило раздела, которое легко потерять: **фаза выводится из трёх дат**
(DEC-45). Хранимых `status`, `days_left` и числа заявок нет — «87 өтінім»
стояло при одной настоящей заявке, а `days_left=12` протухал назавтра.
"""

import re
from datetime import date
from pathlib import Path
from unittest import mock

from core.tests.base import TestCase, login_as
from django.urls import reverse

from core import data
from core.models import AwardGrant, Contest, Story, Submission

TEMPLATES = Path(__file__).resolve().parents[2] / 'templates'


def _all_submissions() -> dict:
    """Заявки по авторам. Нужны здесь ровно затем, чтобы проверить, что
    число заявок у конкурса считается, а не хранится (BR-40a)."""
    out = {}
    for sub in Submission.objects.select_related('author', 'contest', 'story'):
        out.setdefault(sub.author.username, []).append(sub)
    return out


class ContestModel(TestCase):

    def test_contests_have_required_fields(self):
        for c in data.all_contests():
            with self.subTest(slug=c.slug):
                self.assertTrue(c.name)
                self.assertIn(c.phase, data.CONTEST_PHASES)
                self.assertGreaterEqual(c.submissions, 0)
                # Отсчёт есть ровно там, где ему есть что считать.
                self.assertEqual(c.days_left is not None, c.is_accepting)
                self.assertEqual(c.days_until_open is not None,
                                 c.phase == 'upcoming')

    def test_contests_by_slug_lookup(self):
        self.assertEqual(
            data.contest_by_slug('altyn-qalam').name,
            'Алтын қалам',
        )

    def test_every_phase_is_represented_in_the_stub_set(self):
        """Демо-набор покрывает все четыре фазы — иначе `judging` и
        `upcoming` не на чем увидеть, а ради них DEC-45 и заводился."""
        self.assertEqual({c.phase for c in data.all_contests()},
                         set(data.CONTEST_PHASES))

    def test_contest_groups_do_not_overlap(self):
        accepting = {c.slug for c in data.accepting_contests()}
        open_ = {c.slug for c in data.open_contests()}
        finished = {c.slug for c in data.finished_contests()}
        self.assertTrue(accepting <= open_)
        self.assertEqual(open_ & finished, set())
        self.assertEqual(open_ | finished, {c.slug for c in data.all_contests()})

    def test_hero_contest_is_the_one_accepting_work(self):
        self.assertTrue(data.hero_contest().is_accepting)

    def test_jury_and_timeline_present_for_active(self):
        c = data.contest_by_slug('bolashak-mektebi')
        self.assertGreater(len(c.jury), 0)
        self.assertGreater(len(c.timeline), 0)
        # ровно одна активная фаза
        self.assertEqual(sum(1 for t in c.timeline if t.state == 'active'), 1)


class ContestDatesAreTheSource(TestCase):
    """DEC-45: фаза, отсчёт, год и число заявок выводятся, а не хранятся."""

    def test_dates_are_ordered(self):
        for c in data.all_contests():
            with self.subTest(slug=c.slug):
                self.assertLessEqual(c.opens_on, c.closes_on)
                self.assertLess(c.closes_on, c.results_on)

    def test_timeline_lies_inside_the_contest_window(self):
        for c in data.all_contests():
            for t in c.timeline:
                with self.subTest(slug=c.slug, stage=t.label):
                    self.assertLessEqual(t.starts, t.ends)
                    self.assertGreaterEqual(t.ends, c.opens_on)
                    self.assertLessEqual(t.starts, c.results_on)

    def test_timeline_stages_are_chronological(self):
        for c in data.all_contests():
            starts = [t.starts for t in c.timeline]
            with self.subTest(slug=c.slug):
                self.assertEqual(starts, sorted(starts))

    def test_submission_count_matches_real_submissions(self):
        """Хранимое «87 өтінім» стояло при одной настоящей заявке."""
        for c in data.all_contests():
            real = sum(1 for subs in _all_submissions().values()
                       for s in subs if s.contest.slug == c.slug)
            with self.subTest(slug=c.slug):
                self.assertEqual(c.submissions, real)

    def test_year_comes_from_the_results_date(self):
        for c in data.all_contests():
            with self.subTest(slug=c.slug):
                self.assertEqual(c.year, c.results_on.year)

    def test_only_finished_contests_have_winners(self):
        for c in data.all_contests():
            if c.winners:
                with self.subTest(slug=c.slug):
                    self.assertTrue(c.is_finished)

    def test_stage_state_follows_the_calendar(self):
        c = data.contest_by_slug('zhas-aldym-2023')
        self.assertTrue(all(t.state == 'done' for t in c.timeline))


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
        for c in data.open_contests():
            with self.subTest(slug=c.slug):
                self.assertContains(r, c.name)
                self.assertContains(
                    r, reverse('core:contest_detail', kwargs={'slug': c.slug}),
                )

    def test_my_submissions_link_for_authed(self):
        login_as(self.client)
        r = self.client.get(reverse('core:contest_list'))
        self.assertContains(r, reverse('core:my_submissions'))

    def test_no_my_submissions_link_for_guest(self):
        r = self.client.get(reverse('core:contest_list'))
        self.assertNotContains(r, reverse('core:my_submissions'))


class ContestDetailKnown(TestCase):

    SLUG = 'bolashak-mektebi'

    def setUp(self):
        self.response = self.client.get(reverse('core:contest_detail', kwargs={'slug': self.SLUG}))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_shows_name_subtitle_prize(self):
        c = data.contest_by_slug(self.SLUG)
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
        c = data.contest_by_slug(self.SLUG)
        for j in c.jury:
            with self.subTest(name=j.name):
                self.assertContains(self.response, j.name)
                self.assertContains(self.response, j.role)

    def test_cta_to_submit_for_active(self):
        self.assertContains(self.response, reverse('core:contest_submit', kwargs={'slug': self.SLUG}))

    def test_countdown_for_active(self):
        c = data.contest_by_slug(self.SLUG)
        self.assertContains(self.response, f'{c.days_left} күн қалды')


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


class ContestWinners(TestCase):
    """`Contest.winners` — слаги произведений, а не имена авторов."""

    def test_winners_reference_known_stories(self):
        for c in data.all_contests():
            for slug in c.winners:
                with self.subTest(contest=c.slug, story=slug):
                    self.assertIsNotNone(data.story_by_slug(slug))

    def test_active_contests_have_no_winners(self):
        for c in data.open_contests():
            with self.subTest(contest=c.slug):
                self.assertEqual(c.winners, ())

    def test_winner_stories_resolve_to_authors(self):
        c = data.contest_by_slug('zhas-aldym-2023')
        authors = {s.author.username for s in c.winner_stories}
        self.assertEqual(authors, {'bekzhan_t', 'dina_books'})

    def test_every_winner_has_a_submission(self):
        """Победа без поданной заявки — конкурсной истории неоткуда взяться."""
        for c in data.all_contests():
            for story in c.winner_stories:
                with self.subTest(contest=c.slug, story=story.slug):
                    self.assertTrue(data.has_submission(
                        story.author.username, c.slug))


class ContestYear(TestCase):

    def test_every_contest_has_a_year(self):
        for c in data.all_contests():
            with self.subTest(contest=c.slug):
                self.assertGreater(c.year, 2000)

    def test_year_matches_slug_when_slug_carries_one(self):
        """«altyn-qalam-2024» с годом 2023 — расхождение, которое видит читатель."""
        import re
        for c in data.all_contests():
            m = re.search(r'-(\d{4})$', c.slug)
            if m:
                with self.subTest(contest=c.slug):
                    self.assertEqual(c.year, int(m.group(1)))


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
        login_as(self.client)
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
        money = data.spaced_number(500_000)
        self.assertEqual(r.content.decode().count(money), 1)

    def test_submit_page_rail_has_no_cta_to_itself(self):
        login_as(self.client)
        r = self.client.get(reverse('core:contest_submit', args=['bolashak-mektebi']))
        self.assertTrue(r.context['hide_submit_cta'])
        # Ссылка на подачу остаётся ровно одна — action самой формы.
        target = reverse('core:contest_submit', args=['bolashak-mektebi'])
        self.assertEqual(r.content.decode().count(f'"{target}"'), 1)


class ContestStages(TestCase):

    def test_current_stage_is_the_active_one(self):
        c = data.contest_by_slug('bolashak-mektebi')
        self.assertEqual(c.current_stage.state, 'active')
        self.assertEqual(c.current_stage.label, 'Өтінім қабылдау')

    def test_next_stage_is_the_first_upcoming(self):
        c = data.contest_by_slug('bolashak-mektebi')
        self.assertEqual(c.next_stage.label, 'Қазылар қарауы')

    def test_finished_contest_has_no_open_stages(self):
        c = data.contest_by_slug('zhas-aldym-2023')
        self.assertIsNone(c.current_stage)
        self.assertIsNone(c.next_stage)


class ContestWinnersOnDetail(TestCase):
    """FR-CONT-08. `winner_stories` существовал и не был отрендерен нигде."""

    def setUp(self):
        self.contest = data.contest_by_slug('zhas-aldym-2023')
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


class ContestParticipants(TestCase):
    """Список участников после описания — все допущенные работы, не
    только победители (BR-74a). Это и есть чтение байқауды как коллекции
    произведений, без отдельной сущности Collection под конкурс.
    """

    def setUp(self):
        self.response = self.client.get(
            reverse('core:contest_detail', args=['zhas-aldym-2023']))

    def test_section_is_present(self):
        self.assertContains(self.response, 'Қатысушылар')

    def test_accepted_stories_are_listed(self):
        for slug in ('temniy-lord', 'igra-kuklovoda'):
            with self.subTest(story=slug):
                self.assertContains(self.response, Story.objects.get(slug=slug).title)

    def test_rejected_submission_is_not_listed(self):
        # aidana подавала «aidana-kysh» на этот же конкурс, и её отклонили —
        # BR-74a запрещает публично показывать отказ.
        self.assertNotContains(self.response, Story.objects.get(slug='aidana-kysh').title)

    def test_winners_carry_their_nomination_label(self):
        contest = data.contest_by_slug('zhas-aldym-2023')
        for grant in contest.grants:
            with self.subTest(award=grant.award.slug):
                self.assertContains(self.response, grant.award.title)

    def test_contest_without_accepted_work_shows_empty_state(self):
        r = self.client.get(reverse('core:contest_detail', args=['altyn-qalam']))
        self.assertEqual(r.context['participants'], [])
        self.assertContains(r, 'Әзірге қатысушы жоқ')


class ContestWinnersOnCard(TestCase):

    def test_finished_card_names_its_winners(self):
        r = self.client.get(reverse('core:contest_list'))
        for story in data.contest_by_slug('zhas-aldym-2023').winner_stories:
            with self.subTest(story=story.slug):
                self.assertContains(r, story.title)

    def test_active_card_says_nothing_about_winners(self):
        html = self.client.get(reverse('core:contest_list')).content.decode()
        self.assertEqual(html.count('Жеңімпаз:'), 1)


class DetailHeroSpeaksByPhase(TestCase):

    def test_accepting_offers_the_button(self):
        r = self.client.get(reverse('core:contest_detail', args=['bolashak-mektebi']))
        self.assertContains(r, reverse('core:contest_submit', args=['bolashak-mektebi']))

    def test_upcoming_names_the_opening_date_instead_of_a_button(self):
        c = data.contest_by_slug('qys-ertegisi')
        r = self.client.get(reverse('core:contest_detail', args=['qys-ertegisi']))
        self.assertNotContains(r, reverse('core:contest_submit', args=['qys-ertegisi']))
        self.assertContains(r, c.opens_on_label)

    def test_judging_names_the_results_date(self):
        c = data.contest_by_slug('altyn-qalam')
        r = self.client.get(reverse('core:contest_detail', args=['altyn-qalam']))
        self.assertNotContains(r, reverse('core:contest_submit', args=['altyn-qalam']))
        self.assertContains(r, c.results_on_label)

    def test_finished_offers_nothing_to_submit(self):
        r = self.client.get(reverse('core:contest_detail', args=['zhas-aldym-2023']))
        self.assertNotContains(r, reverse('core:contest_submit', args=['zhas-aldym-2023']))


class ContestListOrdersByWhatYouCanDo(TestCase):

    def test_accepting_contest_comes_first(self):
        self.assertTrue(data.open_contests()[0].is_accepting)

    def test_every_open_contest_is_on_the_page(self):
        html = self.client.get(reverse('core:contest_list')).content.decode()
        positions = [html.index(c.name) for c in data.open_contests()]
        self.assertEqual(positions, sorted(positions))


class PhaseLabelsAreOneRegistry(TestCase):
    """Подпись фазы приходит из `CONTEST_PHASE_LABELS`, не из шаблона."""

    def test_every_phase_has_a_label_and_a_badge_kind(self):
        for phase in data.CONTEST_PHASES:
            with self.subTest(phase=phase):
                self.assertIn(phase, data.CONTEST_PHASE_LABELS)
                self.assertIn(phase, data.CONTEST_PHASE_BADGE)

    def test_card_shows_the_registry_label(self):
        html = self.client.get(reverse('core:contest_list')).content.decode()
        for c in data.all_contests():
            with self.subTest(slug=c.slug):
                self.assertIn(data.CONTEST_PHASE_LABELS[c.phase], html)


class KazakhDateFormatting(TestCase):

    def test_single_day_stage_has_no_dash(self):
        c = data.contest_by_slug('zhas-aldym-2023')
        final = next(t for t in c.timeline if t.label == 'Финал')
        self.assertEqual(final.period, '15 жел')

    def test_range_stage_joins_two_dates(self):
        c = data.contest_by_slug('zhas-aldym-2023')
        intake = next(t for t in c.timeline if t.label == 'Өтінім қабылдау')
        self.assertEqual(intake.period, '1 қыр — 1 жел')


class ContestAwardsData(TestCase):
    """DEC-46: набор номинаций у каждого конкурса свой, победа — акт жюри."""

    def test_award_slugs_are_unique_within_a_contest(self):
        for c in data.all_contests():
            slugs = [a.slug for a in c.awards]
            with self.subTest(contest=c.slug):
                self.assertEqual(len(slugs), len(set(slugs)))

    def test_every_contest_declares_at_least_one_award(self):
        """Номинация — ответ на «зачем участвовать». Конкурс без неё
        предлагает только сумму в тенге."""
        for c in data.all_contests():
            with self.subTest(contest=c.slug):
                self.assertTrue(c.awards)

    def test_grants_reference_known_contest_award_and_story(self):
        for g in AwardGrant.objects.all():
            with self.subTest(grant=(g.contest.slug, g.award.slug, g.story.slug)):
                self.assertIsNotNone(g.contest)
                self.assertIsNotNone(g.award)
                self.assertIsNotNone(g.story)

    def test_grant_implies_a_finished_contest(self):
        """Награду нельзя вручить, пока жюри не закончило."""
        for g in AwardGrant.objects.all():
            with self.subTest(grant=g.award.slug):
                self.assertTrue(g.contest.is_finished)

    def test_grant_implies_a_submission_by_the_same_author(self):
        for g in AwardGrant.objects.all():
            subs = data.submissions_of(g.story.author.username)
            with self.subTest(grant=g.award.slug):
                self.assertIn(g.contest.slug, {s.contest.slug for s in subs})

    def test_one_award_is_granted_at_most_once(self):
        seen = [(g.contest.slug, g.award.slug) for g in AwardGrant.objects.all()]
        self.assertEqual(len(seen), len(set(seen)))

    def test_winners_are_derived_from_grants(self):
        c = data.contest_by_slug('zhas-aldym-2023')
        self.assertEqual(c.winners, tuple(g.story.slug for g in c.grants))

    def test_contest_without_grants_has_no_winners(self):
        for c in data.all_contests():
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
        for c in data.all_contests():
            for a in c.awards:
                if not a.image:
                    continue
                with self.subTest(contest=c.slug, award=a.slug):
                    self.assertTrue((Path(settings.MEDIA_ROOT) / a.image.name).is_file(),
                                    f'нет файла: {a.image.name}')

    def test_image_path_follows_the_contract(self):
        """`awards/<contest>/<award>.png` — растр, не SVG.

        SVG из `/media/` открывается в origin сайта и может нести скрипт;
        загрузка эмблем идёт через админку, но правило одно для всех.
        """
        for c in data.all_contests():
            for a in c.awards:
                if not a.image:
                    continue
                with self.subTest(award=a.slug):
                    self.assertTrue(a.image.name.startswith(f'awards/{c.slug}/'),
                                    a.image.name)
                    self.assertTrue(a.image.name.endswith(('.png', '.webp')),
                                    a.image.name)

    def test_award_without_image_still_renders(self):
        """Админ не загрузил файл — типографическая заглушка, не дыра."""
        c = data.contest_by_slug('bolashak-mektebi')
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
        c = data.contest_by_slug('zhas-aldym-2023')
        r = self.client.get(reverse('core:contest_detail', args=[c.slug]))
        for g in c.grants:
            with self.subTest(award=g.award.slug):
                self.assertContains(r, g.award.title)

    def test_winner_emblem_is_rendered(self):
        c = data.contest_by_slug('zhas-aldym-2023')
        r = self.client.get(reverse('core:contest_detail', args=[c.slug]))
        for g in c.grants:
            if g.award.image:
                with self.subTest(award=g.award.slug):
                    self.assertContains(r, f'/media/{g.award.image.name}')


class SystemWinnerAwardIsRetired(TestCase):
    """DEC-46 снял общий «Байқау жеңімпазы» — его вытеснила награда конкурса."""

    def test_registry_has_no_generic_winner_award(self):
        self.assertNotIn('contest_winner', {a.key for a in data.AWARDS})

    def test_participation_awards_stay(self):
        keys = {a.key for a in data.AWARDS}
        self.assertIn('contest_participant', keys)
        self.assertIn('contest_accepted', keys)


class ContestTimingLineIsOneImplementation(TestCase):
    """«Что дальше и когда» собирает конкурс, а не шаблон.

    Формулировка стояла inline в `my_submissions.html`; вторая копия для
    конкурсного уведомления разошлась бы с ней ровно так же, как разошлись
    две рукописные копии правил подачи.
    """

    def test_line_matches_the_phase(self):
        for c in data.all_contests():
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
        for c in data.all_contests():
            with self.subTest(contest=c.slug):
                self.assertNotIn('күн қалды', c.timing_line)

    def test_submissions_page_renders_the_shared_line(self):
        login_as(self.client, 'dina_books')
        r = self.client.get(reverse('core:my_submissions'))
        self.assertContains(r,
                            data.contest_by_slug('bolashak-mektebi').timing_line)


class AgeIsTheContestsRule(TestCase):
    """Возрастную вилку ставит конкурс, а не платформа (BR-48).

    Прежнее BR-20 объявляло «14-18 лет» правилом платформы, и потому
    конкурс со своей вилкой выразить было нечем: четыре конкурса из пяти
    повторяли одну и ту же строку руками, чек-лист держал её в коде,
    а форма регистрации сообщала её каждому новому пришедшему.
    """

    def test_line_reads_right_in_every_shape(self):
        C = Contest
        base = dict(slug='x', name='X', subtitle='',
                    opens_on=date(2026, 1, 1), closes_on=date(2026, 2, 1),
                    results_on=date(2026, 3, 1), prize_kzt=None)
        cases = [
            ({'min_age': 16, 'max_age': 25}, '16-25 жас'),
            ({'min_age': 18},                '18 жастан бастап'),
            ({'max_age': 22},                '22 жасқа дейін'),
            ({},                             ''),
        ]
        for extra, expected in cases:
            with self.subTest(**extra):
                self.assertEqual(C(**base, **extra).eligibility_line, expected)

    def test_contests_do_not_all_share_one_bracket(self):
        """Если у всех одна вилка, поле ничем не отличается от константы."""
        brackets = {(c.min_age, c.max_age) for c in data.all_contests()}
        self.assertGreater(len(brackets), 1)
        self.assertIn((None, None), brackets,
                      'нужен конкурс без ценза — иначе ветка «нет требования» не показана')

    def test_conditions_no_longer_repeat_the_age(self):
        for c in data.all_contests():
            for cond in c.conditions:
                with self.subTest(contest=c.slug, cond=cond):
                    self.assertNotIn('жас', cond,
                                     'возраст приходит из min_age/max_age, не из conditions')

    def test_conditions_carry_no_spec_codes(self):
        """«(BR-23)» и «(DEC-21)» читал подросток."""
        for c in data.all_contests():
            for cond in c.conditions:
                with self.subTest(contest=c.slug, cond=cond):
                    self.assertNotRegex(cond, r'\b(BR|DEC|FR|NFR)-\d+')

    def test_detail_shows_the_bracket_from_data(self):
        c = data.contest_by_slug('altyn-qalam')
        r = self.client.get(reverse('core:contest_detail', args=[c.slug]))
        self.assertContains(r, c.eligibility_line)

    def test_detail_of_an_unrestricted_contest_claims_no_age(self):
        c = data.contest_by_slug('qys-ertegisi')
        self.assertEqual(c.eligibility_line, '')
        html = self.client.get(reverse('core:contest_detail', args=[c.slug])).content.decode()
        self.assertNotIn('Қатысушы:', html)


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
        fields = {f.name for f in Contest._meta.get_fields()}
        self.assertNotIn('cover', fields)
        self.assertIn('poster', fields)

    def test_poster_renders_on_list_and_detail(self):
        for url in ('/contests/', '/contests/bolashak-mektebi/'):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertIn('oklch(', html,
                              'типографическая афиша не отрендерилась')

    def test_declared_poster_files_live_in_media(self):
        """Афишу грузит админ в MEDIA_ROOT, как эмблему награды (BR-46)."""
        for c in data.all_contests():
            if c.poster:
                with self.subTest(contest=c.slug):
                    self.assertTrue(c.poster.name.startswith('contests/'))
                    self.assertFalse(c.poster.name.endswith('.svg'))


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
        old = data.contest_by_slug('zhas-aldym-2023')
        new = data.contest_by_slug('zhas-aldym-2026')
        self.assertEqual([c.slug for c in old.other_editions], [new.slug])
        self.assertEqual([c.slug for c in new.other_editions], [old.slug])

    def test_a_one_off_contest_has_no_editions(self):
        self.assertEqual(data.contest_by_slug('altyn-qalam').other_editions, [])

    def test_finished_page_links_to_the_open_edition(self):
        r = self.client.get(reverse('core:contest_detail', args=['zhas-aldym-2023']))
        self.assertContains(r, reverse('core:contest_detail', args=['zhas-aldym-2026']))
        self.assertContains(r, 'Басқа жылдар')

    def test_year_comes_from_the_data_not_the_name(self):
        for c in data.all_contests():
            for e in c.other_editions:
                with self.subTest(contest=c.slug, edition=e.slug):
                    self.assertEqual(e.year, e.results_on.year)


class ContestPageCanBeShared(TestCase):
    """FR-CONT-12: конкурс живёт тем, что о нём рассказывают."""

    def test_share_button_in_every_phase(self):
        for slug in [c.slug for c in data.all_contests()]:
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
        # Патчится фасад: view читает `core.data`, и подмена в модуле
        # запросов до него уже не доходит.
        with mock.patch.object(data, 'open_contests', lambda: []), \
             mock.patch.object(data, 'finished_contests', lambda: []):
            html = self.client.get(reverse('core:contest_list')).content.decode()
        self.assertNotIn('онкурс', html)
        self.assertIn('Әзірге байқау жоқ', html)
