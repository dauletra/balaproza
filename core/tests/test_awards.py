"""Знаки автора: за что они и почему не хранятся.

Ни одного числа, по которому авторов можно сравнить между собой:
рейтинга на платформе нет и не будет. Знак отвечает на «что этот человек
сделал», а не «насколько он лучше другого».

Всё здесь **выводится**, а не лежит в базе: ступень оқылым — от
накопленного числа прочтений, «Аяқталған сериал» — от глав. Исключение
одно и оно акт: `AwardGrant` у конкурсной награды несёт дату и того, кто
её присудил.
"""


from django.template.loader import render_to_string
from django.urls import reverse

from core import data
from core.tests.base import TEMPLATES, TestCase, login_as, user


# ───────────────────────────────────────────────────────────────────────
# Знаки, награды и конкурсная биография
# ───────────────────────────────────────────────────────────────────────

class AchievementsRow(TestCase):
    """Ряд знаков и строка фактов (FR-PROF-06)."""

    def test_the_row_renders_for_owner_and_stranger_alike(self):
        """Достижение публично по определению — набор не зависит от зрителя."""
        login_as(self.client)
        mine = self.client.get(reverse('core:profile_me'))
        theirs = self.client.get(
            reverse('core:profile_other', kwargs={'username': 'aidana'}))
        marks = data.achievements_of(user('aidana'))
        self.assertTrue(marks)
        for mark in marks:
            with self.subTest(key=mark['key']):
                self.assertContains(mine, mark['label'])
                self.assertContains(theirs, mark['label'])
        self.assertContains(
            self.client.get(reverse('core:profile_other',
                                    kwargs={'username': 'rudazov'})),
            'Автордың марапаттары')

    def test_an_empty_row_renders_nothing(self):
        """Пустое состояние здесь звучало бы упрёком новичку (docs/ui.md)."""
        html = render_to_string('partials/profile/_achievements.html',
                                {'achievements': []})
        self.assertNotIn('<ul', html)
        self.assertEqual(html.strip(), '')

    def test_the_facts_line_names_how_long_and_the_contests(self):
        response = self.client.get(
            reverse('core:profile_other', kwargs={'username': 'aidana'}))
        self.assertContains(response, user('aidana').joined_since)
        # Участие без статуса: число совпадает с длиной списка заявок и не
        # выдаёт вычитанием, что одна из них отклонена.
        self.assertContains(response,
                            f'{len(data.submissions_of(user("aidana")))} байқау')
        # Дубль числа работ уже вычищали из рейла — не возвращаем в шапку.
        self.assertNotIn('шығарма', (TEMPLATES / 'partials' / 'profile'
                                     / '_header.html').read_text(encoding='utf-8'))

    def test_the_facts_line_omits_contests_when_there_are_none(self):
        response = self.client.get(
            reverse('core:profile_other', kwargs={'username': 'aygerim_k'}))
        self.assertEqual(list(data.submissions_of(user('aygerim_k'))), [])
        self.assertEqual(response.context['contests_n'], 0)
        self.assertContains(response, user('aygerim_k').joined_since)
        # Проверяем сегмент, а не слово: «Байқаулар» есть в шапке и подвале.
        self.assertNotContains(response, '0 байқау')

    def test_the_sprite_is_included_exactly_once(self):
        """Два спрайта на странице — дублирующиеся id символов."""
        marker = '<symbol id="award-first-publication"'
        row = self.client.get(reverse('core:profile_other',
                                      kwargs={'username': 'rudazov'}))
        self.assertEqual(row.content.decode().count(marker), 1)
        login_as(self.client)
        both = self.client.get(reverse('core:profile_me') + '?tab=stats')
        self.assertTrue(both.context['achievements'])
        self.assertEqual(both.content.decode().count(marker), 1)


class AchievementsAreDerivedNotStored(TestCase):
    """Знаки автора выводятся из его работ (BR-ACH-01, DEC-41).

    Колонки «награды автора» нет и быть не может — она разошлась бы с тем,
    что человек сделал. Рейтинга здесь тоже нет: знак говорит «ты
    сделал», рейтинг — «ты хуже вон того», и аудитории 14-18 второе не
    нужно.

    Проверки идут по всему корпусу, потому что вопрос именно такой:
    выполняется ли правило **для каждого** автора.
    """

    def _all(self):
        return [(a.username, ach)
                for a in data.all_authors()
                for ach in data.achievements_of(a)]

    def test_shape_and_uniqueness(self):
        self.assertEqual(data.achievements_of(user('ghost')), [])
        for username, ach in self._all():
            with self.subTest(author=username, key=ach.get('key')):
                self.assertEqual(set(ach), {'key', 'label', 'art', 'tier'})
                self.assertTrue(ach['label'])
                self.assertTrue(ach['art'])
                self.assertIn(ach['tier'], data.AWARD_TIERS)
        for author in data.all_authors():
            marks = data.achievements_of(author)
            with self.subTest(author=author.username):
                keys = [m['key'] for m in marks]
                arts = [m['art'] for m in marks]
                self.assertEqual(len(keys), len(set(keys)))
                self.assertEqual(len(arts), len(set(arts)))
                # «Мың» и «Он мың» рядом говорят одно и то же.
                reads = [m for m in marks if m['key'] == 'reads']
                self.assertLessEqual(len(reads), 1)
                if reads:
                    self.assertEqual(reads[0]['label'],
                                     data.read_tier(author)[1])

    def test_gold_stays_rare_and_every_tier_has_art(self):
        """Металл — сигнал ценности. Позолотить всё значит обесценить золото.

        «Байқау жеңімпазы» из системного реестра убран (DEC-46): победу
        называет награда конкретного конкурса, и металла у неё нет.
        """
        gold = {ach['key'] for _, ach in self._all() if ach['tier'] == 'gold'}
        self.assertTrue(gold <= {'editorial_choice', 'reads'}, gold)
        golden_reads = {ach['label'] for _, ach in self._all()
                        if ach['key'] == 'reads' and ach['tier'] == 'gold'}
        self.assertTrue(golden_reads <= {'Жүз мың оқылым'})
        self.assertEqual(data.READ_TIER_ART[100_000][1], 'gold')
        self.assertEqual(data.READ_TIER_ART[1_000][1], 'bronze')
        self.assertEqual(set(data.READ_TIER_ART), {t[0] for t in data.READ_TIERS})
        for art, metal in data.READ_TIER_ART.values():
            with self.subTest(art=art):
                self.assertIn(metal, data.AWARD_TIERS)

    def test_a_mark_never_outruns_its_reason(self):
        """Каждый знак обязан иметь под собой факт: редакционный — публичную
        работу с этим бейджем, конкурсный — заявку, прошедшую жюри
        (DEC-46), «дописанный сериал» — сериал."""
        editorial = data.BADGE_LABELS['editorial']
        for author in data.all_authors():
            keys = {m['key'] for m in data.achievements_of(author)}
            with self.subTest(author=author.username):
                has_public_pick = any(
                    editorial in s.badges
                    for s in data.public_stories_of(author))
                self.assertEqual('editorial_choice' in keys, has_public_pick)
                if data.contest_awards_of(author):
                    self.assertIn('contest_participant', keys)
                    self.assertIn('contest_accepted', keys)
                if 'finished_serial' in keys:
                    self.assertTrue(any(
                        s.is_serial and s.status == 'Completed'
                        for s in data.public_stories_of(author)))


class AwardRegistry(TestCase):
    """Один реестр на «что получено» и «что можно получить» (FR-PROF-08)."""

    def test_the_row_and_the_catalog_come_from_the_same_source(self):
        keys = [x.key for x in data.AWARDS]
        for author in data.all_authors():
            earned_row = {x['key'] for x in data.achievements_of(author)
                          if x['key'] != 'reads'}
            catalog = data.award_catalog(author)
            with self.subTest(author=author.username):
                self.assertEqual(earned_row,
                                 {x['key'] for x in catalog if x['earned']})
                # Список полный у всех: серая плитка отвечает «что дальше».
                self.assertEqual([x['key'] for x in catalog], keys)
        unknown = data.award_catalog(user('ghost'))
        self.assertEqual(len(unknown), len(data.AWARDS))
        self.assertFalse(any(x['earned'] for x in unknown))

    def test_every_award_explains_how_to_get_it_and_dim_is_the_inverse(self):
        for award in data.AWARDS:
            with self.subTest(award=award.key):
                self.assertTrue(award.hint.strip())
                self.assertNotEqual(award.hint, award.label)
        for author in data.all_authors():
            items = (data.award_catalog(author)
                     + data.read_ladder(author))
            for item in items:
                with self.subTest(author=author.username,
                                  key=item.get('key') or item.get('threshold')):
                    self.assertEqual(item['dim'], not item['earned'])

    def test_the_ladder_marks_exactly_one_next_step(self):
        for author in data.all_authors():
            ladder = data.read_ladder(author)
            with self.subTest(author=author.username):
                self.assertEqual(len(ladder), len(data.READ_TIERS))
                self.assertLessEqual(sum(1 for s in ladder if s['is_next']), 1)
                # Пройденные идут подряд с начала: ступень не перепрыгнуть.
                earned = [s['earned'] for s in ladder]
                self.assertEqual(earned, sorted(earned, reverse=True))
                for step in ladder:
                    if step['earned']:
                        self.assertEqual(step['left'], 0)
                    else:
                        self.assertGreater(step['left'], 0)


class ContestAwardsInProfile(TestCase):
    """DEC-46: награды конкурсов стоят тем же рядом, что и системные знаки."""

    def test_a_winner_gets_a_medallion_with_a_complete_shape(self):
        awards = data.contest_awards_of(user('bekzhan_t'))
        self.assertEqual([a['title'] for a in awards], ['Бас жүлде'])
        self.assertEqual(awards[0]['year'], 2023)
        for author in data.all_authors():
            for item in data.contest_awards_of(author):
                with self.subTest(author=author.username, key=item['key']):
                    self.assertEqual(
                        set(item),
                        {'key', 'title', 'image', 'contest', 'story', 'year', 'note'})
                    self.assertTrue(item['title'])
                    # Работа скрыта — награда остаётся: она принадлежит
                    # автору, а не видимости текста (BR-73).
                    if item['story'] is not None:
                        self.assertTrue(item['story'].is_public)

    def test_the_row_shows_the_emblem_and_names_both_nomination_and_contest(self):
        """Медальон без подписи; смысл несёт тултип (BR-ACH-06), и одной
        номинации мало — «Бас жүлде» бывает у каждого конкурса."""
        response = self.client.get(reverse('core:profile_other',
                                           kwargs={'username': 'bekzhan_t'}))
        award = data.contest_awards_of(user('bekzhan_t'))[0]
        self.assertContains(response, f"/media/{award['image']}")
        self.assertContains(response, 'Бас жүлде · Жас алдым — 2023')

    def test_an_author_without_contest_awards_shows_no_medallion(self):
        """Системные знаки у неё есть, конкурсных нет — и медальона тоже."""
        self.assertEqual(data.contest_awards_of(user('aidana')), [])
        self.assertEqual(data.contest_awards_of(user('ghost')), [])
        self.assertNotContains(
            self.client.get(reverse('core:profile_other',
                                    kwargs={'username': 'aidana'})),
            '/media/awards/')


class ContestHistoryPrivacy(TestCase):
    """FR-PROF-07 / BR-74a: публично — участие, не приговор."""

    JURY_NOTE = 'Көлемі шарттан аз'

    def test_the_helper_hides_the_verdict_from_strangers(self):
        # Публично «қаралуда» и «қабылданбады» одинаково выглядят участием,
        # поэтому отказ нельзя ни увидеть, ни отличить от ожидания.
        public = data.contest_history(user('aidana'))
        self.assertEqual([i['note'] for i in public], ['', ''])
        for item in public:
            with self.subTest(contest=item['contest'].slug):
                self.assertIn(item['result'], ('', *data.PUBLIC_CONTEST_RESULTS))
        mine = data.contest_history(user('aidana'), is_self=True)
        self.assertTrue(any(self.JURY_NOTE in i['note'] for i in mine))
        self.assertEqual({i['result'] for i in mine}, {'reviewing', 'rejected'})

    def test_the_rows_match_the_submissions_and_run_newest_first(self):
        """Строк столько же, сколько подач — иначе отказ считается вычитанием."""
        for username in ('aidana', 'dina_books', 'bekzhan_t'):
            author = user(username)
            history = data.contest_history(author)
            with self.subTest(user=username):
                self.assertEqual(len(history), len(data.submissions_of(author)))
                years = [i['year'] for i in history]
                self.assertEqual(years, sorted(years, reverse=True))
                # BR-73: подача не раскрывает снятую с публикации работу.
                for item in history:
                    if item['story'] is not None:
                        self.assertTrue(item['story'].is_public)

    def test_a_win_is_derived_from_the_contest_not_from_the_status(self):
        # У dina_books заявка помечена accepted, а победа лежит в
        # Contest.winners: без вывода из данных «Жеңімпаз» не появился бы.
        winners = [i for i in data.contest_history(user('dina_books'))
                   if i['result'] == 'winner']
        self.assertEqual([i['contest'].slug for i in winners], ['zhas-aldym-2023'])
        # Строка называет номинацию, а не общее «Жеңімпаз» (DEC-46):
        # «Оқырман таңдауы» и «Бас жүлде» — разные вещи.
        response = self.client.get(
            reverse('core:profile_other', kwargs={'username': 'dina_books'})
            + '?tab=about')
        self.assertContains(response, 'Оқырман таңдауы')
        self.assertContains(response, '2023')

    def test_the_page_shows_the_verdict_only_to_its_owner(self):
        theirs = self.client.get(
            reverse('core:profile_other', kwargs={'username': 'aidana'})
            + '?tab=about')
        self.assertContains(theirs, 'Байқаулар')
        self.assertContains(theirs, 'Алтын қалам')
        for hidden in (self.JURY_NOTE, 'Қабылданбады', 'Қаралуда'):
            with self.subTest(hidden=hidden):
                self.assertNotContains(theirs, hidden)

        login_as(self.client)
        mine = self.client.get(reverse('core:profile_me') + '?tab=about')
        for shown in (self.JURY_NOTE, 'Қабылданбады', 'Қаралуда'):
            with self.subTest(shown=shown):
                self.assertContains(mine, shown)

    def test_an_author_without_submissions_gets_no_section(self):
        self.assertEqual(data.contest_history(user('aygerim_k')), [])
        response = self.client.get(
            reverse('core:profile_other', kwargs={'username': 'aygerim_k'})
            + '?tab=about')
        self.assertEqual(response.context['contest_history'], [])
        # Слово «Байқаулар» само по себе не показатель — оно есть в шапке
        # и в подвале. Проверяем, что нет ни одного названия конкурса.
        for contest in data.all_contests():
            with self.subTest(contest=contest.slug):
                self.assertNotContains(response, contest.name)
