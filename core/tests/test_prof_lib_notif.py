"""PROF / LIB / NOTIF — три родственных авторизованных раздела."""

from pathlib import Path

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


def _login_as(client, username, name='X'):
    s = client.session
    s['signed_in'] = True
    s['user_name'] = name
    s['user_username'] = username
    s.save()


# ════════════════════════════ stub_data helpers ════════════════════════════

class LibraryHelpers(TestCase):

    def test_library_of_returns_all_when_no_kind(self):
        self.assertEqual(len(stub_data.library_of('aidana')), 6)

    def test_library_of_filters_by_kind(self):
        self.assertEqual(len(stub_data.library_of('aidana', 'reading')), 2)
        self.assertEqual(len(stub_data.library_of('aidana', 'saved')), 3)
        self.assertEqual(len(stub_data.library_of('aidana', 'done')), 1)

    def test_library_of_unknown_user_is_empty(self):
        self.assertEqual(stub_data.library_of('no-such-user'), [])

    def test_library_entry_resolves_story(self):
        for e in stub_data.library_of('aidana'):
            with self.subTest(entry=e.story_slug):
                self.assertEqual(e.story.slug, e.story_slug)

    def test_reading_entries_have_valid_progress(self):
        for e in stub_data.library_of('aidana', 'reading'):
            with self.subTest(entry=e.story_slug):
                self.assertGreaterEqual(e.progress_chapter, 1)
                self.assertLessEqual(e.progress_chapter, e.story.chapters)


class PublicStatsHelper(TestCase):
    """Числа, которые видит посторонний, — только по публичным работам."""

    def test_works_matches_author_works(self):
        # Одно правило публичности, посчитанное один раз: если эти два числа
        # разойдутся, профиль и карточка автора на STORY снова будут врать
        # друг про друга (у aidana было 5 против 3).
        for a in stub_data.AUTHORS:
            with self.subTest(author=a.username):
                self.assertEqual(stub_data.public_stats(a.username)['works'], a.works)

    def test_sums_run_over_public_stories_only(self):
        # У черновиков в стабе 0 просмотров и 0 лайков, поэтому сравнение
        # «публичная сумма меньше полной» ничего бы не доказало: сверяем с
        # суммой по public_stories_of напрямую.
        for a in stub_data.AUTHORS:
            pub = stub_data.public_stories_of(a.username)
            stats = stub_data.public_stats(a.username)
            with self.subTest(author=a.username):
                self.assertEqual(stats['reads'], sum(s.views for s in pub))
                self.assertEqual(stats['likes'], sum(s.likes for s in pub))

    def test_hidden_work_does_not_reach_works_count(self):
        hidden = [s for s in stub_data.my_stories_of('aidana') if not s.is_public]
        self.assertTrue(hidden, 'фикстура сломана: у aidana нет непубличных работ')
        self.assertEqual(
            stub_data.public_stats('aidana')['works'],
            len(stub_data.my_stories_of('aidana')) - len(hidden),
        )

    def test_public_stats_unknown_user(self):
        stats = stub_data.public_stats('no-such-user')
        self.assertEqual(
            [stats['works'], stats['reads'], stats['likes'], stats['followers']],
            [0, 0, 0, 0],
        )


class PublicStoriesHelper(TestCase):

    def test_excludes_non_public_statuses(self):
        pub = stub_data.public_stories_of('aidana')
        self.assertTrue(all(s.is_public for s in pub))
        slugs = {s.slug for s in pub}
        self.assertNotIn('aidana-kus', slugs)     # NotPublished
        self.assertNotIn('aidana-erteg', slugs)   # OnModeration

    def test_keeps_serials(self):
        # DEC-37: публичный сериал носит OnProcess/Completed. Фильтр по
        # литералу 'Published' молча выкинул бы их все.
        pub = stub_data.public_stories_of('rudazov')
        self.assertEqual(len(pub), 3)
        self.assertIn('arhimag', {s.slug for s in pub})   # OnProcess

    def test_unknown_user_is_empty(self):
        self.assertEqual(stub_data.public_stories_of('no-such-user'), [])


class ReaderStatsHelper(TestCase):

    def test_reader_stats_for_aidana(self):
        stats = stub_data.reader_stats('aidana')
        # Публичные числа те же, что у постороннего: свой профиль не показывает
        # владельцу другую арифметику, чем читателю.
        self.assertEqual(stats['works'], stub_data.AUTHORS_BY_USERNAME['aidana'].works)
        # Сверх них — приватное
        self.assertEqual(stats['works_total'], len(stub_data.my_stories_of('aidana')))
        self.assertGreater(stats['works_total'], stats['works'])
        self.assertEqual(stats['finished'], 1)
        self.assertEqual(stats['followers'], stub_data.AUTHORS_BY_USERNAME['aidana'].followers)

    def test_reader_stats_unknown_user(self):
        stats = stub_data.reader_stats('no-such-user')
        self.assertEqual(stats['works'], 0)
        self.assertEqual(stats['works_total'], 0)
        self.assertEqual(stats['finished'], 0)
        self.assertEqual(stats['followers'], 0)


class FollowGraph(TestCase):

    def test_is_following_true(self):
        self.assertTrue(stub_data.is_following('aidana', 'rudazov'))

    def test_is_following_false(self):
        self.assertFalse(stub_data.is_following('aidana', 'bekzhan_t'))

    def test_following_returns_authors(self):
        f = stub_data.following_of('aidana')
        self.assertEqual(len(f), 3)
        usernames = {a.username for a in f}
        self.assertEqual(usernames, {'rudazov', 'sayyn', 'dina_books'})

    def test_followers_returns_authors(self):
        # На aidana подписан только aygerim_k.
        f = stub_data.followers_of('aidana')
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].username, 'aygerim_k')

    def test_unknown_user_no_follow(self):
        self.assertEqual(stub_data.following_of('no-such-user'), [])
        self.assertEqual(stub_data.followers_of('no-such-user'), [])


class NotificationsHelpers(TestCase):

    def test_groups_into_buckets(self):
        g = stub_data.notifications_for_user('aidana')
        self.assertIn('today', g)
        self.assertIn('yesterday', g)
        self.assertIn('past_week', g)
        # БҮГІН — 3 уведомления (comment + like + moderation).
        self.assertEqual(len(g['today']), 3)
        self.assertEqual(len(g['yesterday']), 2)
        self.assertEqual(len(g['past_week']), 3)

    def test_unknown_user_empty_buckets(self):
        g = stub_data.notifications_for_user('no-such-user')
        for b in stub_data.NOTIF_BUCKETS:
            self.assertEqual(g[b], [])

    def test_unread_count(self):
        # БҮГІН непрочитанные (3 шт), КЕШЕ/АПТА — все read=True.
        self.assertEqual(stub_data.unread_count_for_user('aidana'), 3)

    def test_unread_zero_for_unknown(self):
        self.assertEqual(stub_data.unread_count_for_user('ghost'), 0)

    def test_notification_kinds_within_set(self):
        for n in stub_data.NOTIFICATIONS_BY_USER['aidana']:
            with self.subTest(kind=n.kind):
                self.assertIn(n.kind, stub_data.NOTIF_KINDS)


# ════════════════════════════ PROF · profile_me ════════════════════════════

class ProfileMeGuest(TestCase):

    def test_guest_sees_gate(self):
        r = self.client.get(reverse('core:profile_me'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'кір')
        # Реальные данные не светим
        self.assertNotContains(r, 'Айдана Серікқызы')


class ProfileMeAuthed(TestCase):

    def setUp(self):
        _login_as_aidana(self.client)

    def test_default_tab_is_works(self):
        r = self.client.get(reverse('core:profile_me'))
        self.assertEqual(r.status_code, 200)
        # На вкладке «Шығармалар» видим все 4 рассказа Айданы
        for s in stub_data.my_stories_of('aidana'):
            with self.subTest(story=s.slug):
                self.assertContains(r, s.title)

    def test_header_shows_name_and_username(self):
        r = self.client.get(reverse('core:profile_me'))
        self.assertContains(r, 'aidana')
        self.assertContains(r, '@aidana')

    def test_stats_block_present(self):
        r = self.client.get(reverse('core:profile_me'))
        # 4 числа из reader_stats. «Оқылды» значило то просмотры, то
        # «дочитано»; просмотры теперь везде «Оқылым». «Жазылулар» в этой
        # плитке значило подписчиков, а в заголовке рейла — подписки:
        # одно слово на два противоположных смысла.
        self.assertContains(r, 'Шығарма')
        self.assertContains(r, 'Ұнатулар')
        self.assertContains(r, 'Оқылым')
        self.assertContains(r, 'Жазылушы')

    def test_segmented_control_covers_every_own_tab(self):
        r = self.client.get(reverse('core:profile_me'))
        # Список ведём из самого источника: сегмент, добавленный в
        # _PROF_TABS_ME и забытый в шаблоне, иначе остался бы незамеченным.
        for slug in ('works', 'library', 'stats', 'about'):
            with self.subTest(tab=slug):
                self.assertContains(r, f'?tab={slug}')
        self.assertEqual(len(r.context['prof_items']), 4)

    def test_library_tab_shows_library_rows(self):
        r = self.client.get(reverse('core:profile_me') + '?tab=library')
        # Заголовки секций
        self.assertContains(r, 'Оқу үстіндегі')
        self.assertContains(r, 'Сақталған')
        # Книги из ридинга
        self.assertContains(r, 'Алыс жағалауларда')

    def test_about_tab_shows_bio(self):
        r = self.client.get(reverse('core:profile_me') + '?tab=about')
        self.assertContains(r, 'Жас прозаик')
        # Списка работ здесь нет. «Таң алдында» проверять нельзя: эта работа
        # подана на конкурс и законно стоит в конкурсной истории (FR-PROF-07).
        # Берём работу, которая никуда не подавалась.
        self.assertNotContains(r, 'Көше әндері')
        self.assertNotContains(r, 'my_story_row')

    def test_about_tab_shows_private_block_to_owner(self):
        r = self.client.get(reverse('core:profile_me') + '?tab=about')
        self.assertContains(r, 'Тек саған көрінеді')
        self.assertContains(r, 'Айдана Серікқызы')       # ресми аты-жөні
        self.assertContains(r, '2025 жылдан бері')       # Author.joined_year
        # Полное число работ — с черновиками, и помечено как таковое
        self.assertContains(r, len(stub_data.my_stories_of('aidana')))
        self.assertContains(r, 'жобалармен бірге')

    def test_unknown_tab_falls_back_to_works(self):
        r = self.client.get(reverse('core:profile_me') + '?tab=garbage')
        self.assertEqual(r.status_code, 200)
        # рендерится как works → виден список рассказов
        self.assertContains(r, 'Таң алдында')


# ════════════════════════════ PROF · profile_other ═════════════════════════

class ProfileOtherKnown(TestCase):

    USERNAME = 'rudazov'

    def test_renders_for_guest(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': self.USERNAME}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Rudazov')
        # Гость видит кнопку «Жазылу» — но это <a> на /auth/login/?next=
        self.assertContains(r, 'Жазылу')
        self.assertContains(r, '/auth/login/')

    def test_authed_sees_follow_button(self):
        _login_as(self.client, 'bekzhan_t')   # bekzhan_t подписан на rudazov
        r = self.client.get(reverse('core:profile_other', kwargs={'username': self.USERNAME}))
        # «Уже подписан» — кнопка «Жазылдың» + toast «отписка»
        self.assertContains(r, 'Жазылдың')
        self.assertContains(r, 'Жазылудан бас тарттың')

    def test_authed_not_following_sees_subscribe(self):
        _login_as(self.client, 'sayyn')       # sayyn НЕ подписан на rudazov
        r = self.client.get(reverse('core:profile_other', kwargs={'username': self.USERNAME}))
        # «Не подписан» — кнопка «Жазылу»; toast подписки тут есть («Жазылдың (демо)»),
        # но toast отписки — нет.
        self.assertContains(r, 'Жазылу')
        self.assertNotContains(r, 'Жазылудан бас тарттың')

    def test_works_tab_lists_author_stories(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': self.USERNAME}))
        # У Рысқали в стабе — 2 произведения (kronchessii, arhimag)
        self.assertContains(r, 'Тас уәделер')
        self.assertContains(r, 'Сиқыршы')

    def test_hides_drafts_and_moderation(self):
        """BR-10 / DEC-23: черновик постороннему не показываем.

        Профиль строился на `my_stories_of` — выдаче авторского кабинета, —
        и на `/u/aidana/` черновик с работой на модерации висели обычными
        кликабельными карточками.
        """
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'aidana'}))
        hidden = [s for s in stub_data.my_stories_of('aidana') if not s.is_public]
        self.assertTrue(hidden, 'фикстура сломана: у aidana нет непубличных работ')
        for s in hidden:
            with self.subTest(story=s.slug):
                self.assertNotContains(r, s.title)
                self.assertNotContains(r, f'/story/{s.slug}/')

    def test_segment_count_matches_visible_list(self):
        """Сегмент обещал «Шығармалар 5» и открывал список из трёх."""
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'aidana'}))
        works = r.context['works']
        item = next(i for i in r.context['prof_items'] if i['slug'] == 'works')
        self.assertEqual(item['count'], len(works))

    def test_guest_gets_no_empty_rail(self):
        """Рейл только при данных: пустая колонка 300px сдвигает контент."""
        # sayyn ни на кого не подписан — единственный блок рейла пуст.
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'sayyn'}))
        self.assertEqual(stub_data.following_of('sayyn'), [])
        self.assertFalse(r.context['has_right_rail'])
        self.assertNotContains(r, 'w-[300px]')

    def test_about_tab_visible(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': self.USERNAME}) + '?tab=about')
        self.assertContains(r, 'Фэнтези, шытырман')
        self.assertContains(r, 'жылдан бері')

    def test_about_hides_private_fields(self):
        """Настоящее имя автора — не публичный факт.

        В своей копии вкладки лежал `profile_user.name` без всякой пометки,
        а шапку между двумя шаблонами уже копировали: следующее копирование
        унесло бы имя-фамилию в публичный профиль.
        """
        r = self.client.get(reverse('core:profile_other', kwargs={'username': self.USERNAME}) + '?tab=about')
        self.assertNotContains(r, 'Тек саған көрінеді')
        self.assertNotContains(r, stub_data.AUTHORS_BY_USERNAME[self.USERNAME].name)
        self.assertNotContains(r, 'жобалармен бірге')

    def test_other_profile_has_no_library_tab(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': self.USERNAME}))
        # У чужого профиля segment library — НЕ показываем
        self.assertNotContains(r, '?tab=library')


class ProfileOtherUnknown(TestCase):

    def test_unknown_user_is_404(self):
        """Заглушка с кодом 200 позволяла проиндексировать любой @username."""
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'ghost'}))
        self.assertEqual(r.status_code, 404)


class ProfileAchievementsRender(TestCase):
    """Ряд знаков и строка фактов (FR-PROF-06)."""

    def test_badges_render_on_other_profile(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'dina_books'}))
        ach = stub_data.achievements_of('dina_books')
        self.assertTrue(ach)
        for a in ach:
            with self.subTest(key=a['key']):
                self.assertContains(r, a['label'])

    def test_owner_sees_the_same_badges(self):
        """Достижение публично по определению — набор не зависит от зрителя."""
        _login_as_aidana(self.client)
        mine = self.client.get(reverse('core:profile_me'))
        theirs = self.client.get(reverse('core:profile_other', kwargs={'username': 'aidana'}))
        for a in stub_data.achievements_of('aidana'):
            with self.subTest(key=a['key']):
                self.assertContains(mine, a['label'])
                self.assertContains(theirs, a['label'])

    def test_row_is_a_labelled_list(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'rudazov'}))
        self.assertContains(r, 'Автордың марапаттары')

    def test_empty_row_renders_nothing(self):
        """Пустое состояние здесь звучало бы упрёком новичку (docs/13 §13.8.6)."""
        from django.template.loader import render_to_string
        html = render_to_string('partials/profile/_achievements.html', {'achievements': []})
        self.assertNotIn('<ul', html)
        self.assertEqual(html.strip(), '')

    def test_facts_line_shows_year_and_contests(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'aidana'}))
        self.assertContains(r, '2025 жылдан бері')
        # Участие без статуса: число совпадает с длиной списка заявок и не
        # выдаёт вычитанием, что одна из них отклонена.
        self.assertEqual(len(stub_data.submissions_of('aidana')), 2)
        self.assertContains(r, '2 байқау')

    def test_facts_line_omits_contests_when_none(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'aygerim_k'}))
        self.assertEqual(stub_data.submissions_of('aygerim_k'), [])
        self.assertEqual(r.context['contests_n'], 0)
        self.assertContains(r, '2024 жылдан бері')
        # Проверяем сам сегмент, а не слово: «Байқаулар» есть в шапке и подвале.
        self.assertNotContains(r, '0 байқау')

    def test_facts_line_does_not_repeat_the_works_tile(self):
        """Дубль числа работ уже вычищали из рейла — не возвращаем его в шапку."""
        body = (TEMPLATES / 'partials' / 'profile' / '_header.html').read_text(encoding='utf-8')
        self.assertNotIn('шығарма', body)


class ContestHistoryPrivacy(TestCase):
    """FR-PROF-07 / BR-74a: публично — участие, не приговор."""

    JURY_NOTE = 'Көлемі шарттан асып кеткен'

    def test_helper_hides_note_from_strangers(self):
        public = stub_data.contest_history('aidana')
        mine = stub_data.contest_history('aidana', is_self=True)
        self.assertEqual([i['note'] for i in public], ['', ''])
        self.assertTrue(any(self.JURY_NOTE in i['note'] for i in mine))

    def test_helper_hides_rejection_and_review_from_strangers(self):
        # Публично «қаралуда» и «қабылданбады» одинаково выглядят участием,
        # поэтому отказ нельзя ни увидеть, ни отличить от ожидания.
        for item in stub_data.contest_history('aidana'):
            with self.subTest(contest=item['contest'].slug):
                self.assertIn(item['result'], ('', *stub_data.PUBLIC_CONTEST_RESULTS))
        mine = {i['result'] for i in stub_data.contest_history('aidana', is_self=True)}
        self.assertEqual(mine, {'reviewing', 'rejected'})

    def test_winner_is_derived_from_contest_not_status(self):
        # У dina_books заявка помечена accepted, а победа лежит в
        # Contest.winners: без вывода из данных «Жеңімпаз» не появился бы.
        hist = stub_data.contest_history('dina_books')
        winners = [i for i in hist if i['result'] == 'winner']
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0]['contest'].slug, 'zhas-aldym-2023')

    def test_row_count_matches_the_facts_line(self):
        """Строк столько же, сколько подач — иначе отказ считается вычитанием."""
        for username in stub_data.SUBMISSIONS_BY_USER:
            with self.subTest(user=username):
                self.assertEqual(
                    len(stub_data.contest_history(username)),
                    len(stub_data.submissions_of(username)),
                )

    def test_newest_first(self):
        years = [i['year'] for i in stub_data.contest_history('aidana')]
        self.assertEqual(years, sorted(years, reverse=True))

    def test_non_public_work_is_not_named_to_strangers(self):
        # BR-73: подача на конкурс не должна раскрывать снятую с публикации
        # работу. В фикстуре все поданные работы публичны, поэтому проверяем
        # само правило, а не текущее совпадение данных.
        for username in stub_data.SUBMISSIONS_BY_USER:
            for item in stub_data.contest_history(username):
                with self.subTest(user=username, contest=item['contest'].slug):
                    if item['story'] is not None:
                        self.assertTrue(item['story'].is_public)

    def test_page_hides_jury_note_from_strangers(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'aidana'}) + '?tab=about')
        self.assertContains(r, 'Байқаулар')
        self.assertContains(r, 'Алтын қалам')
        self.assertNotContains(r, self.JURY_NOTE)
        self.assertNotContains(r, 'Қабылданбады')
        self.assertNotContains(r, 'Қаралуда')

    def test_page_shows_own_result_and_note(self):
        _login_as_aidana(self.client)
        r = self.client.get(reverse('core:profile_me') + '?tab=about')
        self.assertContains(r, self.JURY_NOTE)
        self.assertContains(r, 'Қабылданбады')
        self.assertContains(r, 'Қаралуда')

    def test_page_shows_winner_badge(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'dina_books'}) + '?tab=about')
        self.assertContains(r, 'Жеңімпаз')
        self.assertContains(r, '2023')

    def test_history_empty_for_author_without_submissions(self):
        self.assertEqual(stub_data.contest_history('aygerim_k'), [])
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'aygerim_k'}) + '?tab=about')
        self.assertEqual(r.context['contest_history'], [])
        # Слово «Байқаулар» само по себе не показатель — оно есть в шапке
        # и в подвале. Проверяем, что нет ни одного названия конкурса.
        for c in stub_data.CONTESTS:
            with self.subTest(contest=c.slug):
                self.assertNotContains(r, c.name)


class AwardRegistry(TestCase):
    """Один реестр на «что получено» и «что можно получить» (FR-PROF-08)."""

    def test_catalog_and_row_come_from_the_same_source(self):
        for a in stub_data.AUTHORS:
            earned_row = {x['key'] for x in stub_data.achievements_of(a.username)
                          if x['key'] != 'reads'}
            earned_cat = {x['key'] for x in stub_data.award_catalog(a.username)
                          if x['earned']}
            with self.subTest(author=a.username):
                self.assertEqual(earned_row, earned_cat)

    def test_catalog_lists_every_award_for_everyone(self):
        keys = [x.key for x in stub_data.AWARDS]
        for a in stub_data.AUTHORS:
            with self.subTest(author=a.username):
                self.assertEqual([x['key'] for x in stub_data.award_catalog(a.username)], keys)

    def test_every_award_explains_how_to_get_it(self):
        for a in stub_data.AWARDS:
            with self.subTest(award=a.key):
                self.assertTrue(a.hint.strip())
                self.assertNotEqual(a.hint, a.label)

    def test_dim_is_the_inverse_of_earned(self):
        for a in stub_data.AUTHORS:
            for item in stub_data.award_catalog(a.username) + stub_data.read_ladder(a.username):
                with self.subTest(author=a.username, key=item.get('key') or item.get('threshold')):
                    self.assertEqual(item['dim'], not item['earned'])

    def test_ladder_marks_exactly_one_next_step(self):
        for a in stub_data.AUTHORS:
            ladder = stub_data.read_ladder(a.username)
            with self.subTest(author=a.username):
                self.assertEqual(len(ladder), len(stub_data.READ_TIERS))
                self.assertLessEqual(sum(1 for s in ladder if s['is_next']), 1)
                # Пройденные идут подряд с начала: ступень нельзя перепрыгнуть.
                earned = [s['earned'] for s in ladder]
                self.assertEqual(earned, sorted(earned, reverse=True))

    def test_ladder_left_is_zero_once_taken(self):
        for a in stub_data.AUTHORS:
            for s in stub_data.read_ladder(a.username):
                with self.subTest(author=a.username, step=s['threshold']):
                    if s['earned']:
                        self.assertEqual(s['left'], 0)
                    else:
                        self.assertGreater(s['left'], 0)

    def test_unknown_user_gets_full_catalog_with_nothing_earned(self):
        cat = stub_data.award_catalog('ghost')
        self.assertEqual(len(cat), len(stub_data.AWARDS))
        self.assertFalse(any(x['earned'] for x in cat))


class ProfileStatsTab(TestCase):
    """Вкладка «Статистика» — приватная и не повторяет кабинет."""

    def setUp(self):
        _login_as_aidana(self.client)

    def test_segment_exists_for_owner(self):
        r = self.client.get(reverse('core:profile_me'))
        self.assertContains(r, '?tab=stats')
        self.assertContains(r, 'Статистика')

    def test_stranger_has_no_stats_tab(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'aidana'}))
        self.assertNotContains(r, '?tab=stats')

    def test_stats_tab_is_marked_private(self):
        r = self.client.get(reverse('core:profile_me') + '?tab=stats')
        self.assertContains(r, 'Тек саған көрінеді')

    def test_shows_private_breakdown(self):
        r = self.client.get(reverse('core:profile_me') + '?tab=stats')
        self.assertContains(r, 'Модерацияда')
        self.assertContains(r, 'Жазылып жатыр')
        self.assertContains(r, 'Оқып шыққаның')

    def test_shows_whole_ladder_not_just_the_taken_step(self):
        r = self.client.get(reverse('core:profile_me') + '?tab=stats')
        for _, label in stub_data.READ_TIERS:
            with self.subTest(tier=label):
                self.assertContains(r, label)

    def test_shows_unearned_awards_with_hints(self):
        r = self.client.get(reverse('core:profile_me') + '?tab=stats')
        unearned = [a for a in stub_data.award_catalog('aidana') if not a['earned']]
        self.assertTrue(unearned, 'фикстура сломана: у aidana все награды взяты')
        for a in unearned:
            with self.subTest(award=a['key']):
                self.assertContains(r, a['hint'])

    def test_does_not_duplicate_the_cabinet(self):
        """Кабинет отвечает «что делать», статистика — «как идёт» (FR-WRITE-08)."""
        r = self.client.get(reverse('core:profile_me') + '?tab=stats')
        self.assertNotContains(r, 'Назарыңды күтеді')

    def test_guest_never_reaches_the_tab(self):
        self.client.logout()
        r = self.client.get(reverse('core:profile_me') + '?tab=stats')
        self.assertNotContains(r, 'Тек саған көрінеді')
        self.assertNotContains(r, 'Оқылым сатылары')


class AwardSpriteIsIncludedOnce(TestCase):
    """Два спрайта на странице — дублирующиеся id символов."""

    MARKER = '<symbol id="award-contest-winner"'

    def test_row_only(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'rudazov'}))
        self.assertEqual(r.content.decode().count(self.MARKER), 1)

    def test_row_and_stats_tab_together(self):
        _login_as_aidana(self.client)
        r = self.client.get(reverse('core:profile_me') + '?tab=stats')
        self.assertTrue(r.context['achievements'])
        self.assertEqual(r.content.decode().count(self.MARKER), 1)

    def test_stats_tab_without_any_award(self):
        # Автор без единой награды всё равно должен увидеть серые плитки:
        # спрятанная награда не отвечает на вопрос «что дальше».
        _login_as(self.client, 'lonely_writer')
        r = self.client.get(reverse('core:profile_me') + '?tab=stats')
        self.assertEqual(r.status_code, 200)


class ProfileTemplatesShareParts(TestCase):
    """Свой и чужой профиль обязаны рендерить одни и те же партиалы.

    Шапка, четыре числа и «Туралы» были скопированы в оба шаблона — около
    шестидесяти строк, — и копии уже разъехались: в одной вкладке «Туралы»
    четыре поля, в другой только био. Тест ловит именно повторное
    заинлайнивание: поведенческие проверки такого не видят, пока копии
    случайно совпадают.
    """

    PAGES = ('pages/profile/profile_me.html', 'pages/profile/profile_other.html')
    PARTS = ('_header.html', '_achievements.html', '_stats.html', '_about.html')

    def test_both_pages_include_shared_partials(self):
        for page in self.PAGES:
            body = (TEMPLATES / page).read_text(encoding='utf-8')
            for part in self.PARTS:
                with self.subTest(page=page, part=part):
                    self.assertIn(f'partials/profile/{part}', body)

    def test_pages_do_not_reinline_markup(self):
        # Разметка чисел и шапки живёт только в партиалах.
        for page in self.PAGES:
            body = (TEMPLATES / page).read_text(encoding='utf-8')
            with self.subTest(page=page):
                self.assertNotIn('Оқылым', body)
                self.assertNotIn('<header', body)


class ProfileMeGuestRail(TestCase):

    def test_guest_gets_no_empty_rail(self):
        """`has_right_rail` стоял безусловным True.

        Рейл профиля состоит из одного блока «Жазылулар»; у гостя
        `profile_user` пуст, блок не рендерится, и от рейла оставалась
        пустая колонка в 300px, сдвигавшая гейт от центра.
        """
        r = self.client.get(reverse('core:profile_me'))
        self.assertFalse(r.context['has_right_rail'])
        self.assertNotContains(r, 'w-[300px]')


# ════════════════════════════ LIB ══════════════════════════════════════════

class LibraryGuest(TestCase):

    def test_guest_sees_gate(self):
        r = self.client.get(reverse('core:library'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'кір')
        self.assertNotContains(r, 'Алыс жағалауларда')


class LibraryAuthed(TestCase):

    def setUp(self):
        _login_as_aidana(self.client)

    def test_default_tab_is_saved(self):
        r = self.client.get(reverse('core:library'))
        self.assertEqual(r.status_code, 200)
        # «Сақталған»: 3 книги
        for e in stub_data.library_of('aidana', 'saved'):
            with self.subTest(slug=e.story.slug):
                self.assertContains(r, e.story.title)

    def test_reading_tab_shows_progress_and_continue(self):
        r = self.client.get(reverse('core:library') + '?tab=reading')
        self.assertContains(r, 'Жалғастыру')
        self.assertContains(r, 'Алыс жағалауларда')
        # Прогресс «N / M бөлім»
        self.assertContains(r, '4 / 12 бөлім')

    def test_done_tab(self):
        r = self.client.get(reverse('core:library') + '?tab=done')
        self.assertContains(r, 'Империя құдіреті')
        self.assertContains(r, 'Қайта оқу')

    def test_segmented_control_links(self):
        r = self.client.get(reverse('core:library'))
        self.assertContains(r, '?tab=saved')
        self.assertContains(r, '?tab=reading')
        self.assertContains(r, '?tab=done')

    def test_unknown_tab_falls_back_to_saved(self):
        r = self.client.get(reverse('core:library') + '?tab=garbage')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Күңгірт мырза')  # из saved

    def test_other_tab_books_not_shown(self):
        # На reading-табе НЕ должно быть «Күңгірт мырза» (saved)
        r = self.client.get(reverse('core:library') + '?tab=reading')
        self.assertNotContains(r, 'Күңгірт мырза')


class LibraryEmpty(TestCase):

    def setUp(self):
        _login_as(self.client, 'lonely_reader')

    def test_saved_empty_shows_empty_state_with_cta(self):
        r = self.client.get(reverse('core:library'))
        self.assertContains(r, 'Сақталғандар жоқ')
        self.assertContains(r, reverse('core:catalog'))

    def test_reading_empty(self):
        r = self.client.get(reverse('core:library') + '?tab=reading')
        self.assertContains(r, 'Оқу үстіндегі шығарма жоқ')

    def test_done_empty(self):
        r = self.client.get(reverse('core:library') + '?tab=done')
        self.assertContains(r, 'Әлі ешнәрсе оқылмаған')


# ════════════════════════════ NOTIF ════════════════════════════════════════

class NotificationsGuest(TestCase):

    def test_guest_sees_gate(self):
        r = self.client.get(reverse('core:notifications'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'кір')


class NotificationsAuthed(TestCase):

    def setUp(self):
        _login_as_aidana(self.client)
        self.response = self.client.get(reverse('core:notifications'))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_shows_three_buckets(self):
        self.assertContains(self.response, 'Бүгін')
        self.assertContains(self.response, 'Кеше')
        self.assertContains(self.response, 'Өткен аптада')

    def test_renders_all_notifications(self):
        # 3 + 2 + 3 = 8 уведомлений у aidana
        # Уникальные тексты по типам
        self.assertContains(self.response, 'пікір қалдырды')   # comment
        self.assertContains(self.response, 'ұнатты')           # like
        self.assertContains(self.response, 'саған жазылды')    # follower
        self.assertContains(self.response, 'жаңа бөлім')       # new_chapter
        self.assertContains(self.response, 'Модерация')        # moderation
        self.assertContains(self.response, 'Байқау')           # contest

    def test_unread_summary_shows_count(self):
        self.assertContains(self.response, '3 оқылмаған')

    def test_mark_all_button_present_when_has_items(self):
        self.assertContains(self.response, 'Барлығын оқылды деп белгілеу')

    def test_notification_links_to_actor_profile(self):
        # actor=aygerim_k для первого comment
        self.assertContains(self.response, reverse('core:profile_other', kwargs={'username': 'aygerim_k'}))


class NotificationsEmpty(TestCase):

    def setUp(self):
        _login_as(self.client, 'lonely_user')

    def test_empty_state_shown(self):
        r = self.client.get(reverse('core:notifications'))
        self.assertContains(r, 'Әзірге хабарлама жоқ')
        # Кнопки «Mark all» не должно быть в пустом стейте
        self.assertNotContains(r, 'Барлығын оқылды')


# ════════════════════════════ Header / nav badges ═════════════════════════

class HeaderUnreadBadge(TestCase):

    def test_authed_aidana_sees_unread_badge(self):
        _login_as_aidana(self.client)
        r = self.client.get(reverse('core:home'))
        # Бейдж непрочитанных = 3 (из stub_data.unread_count_for_user)
        self.assertContains(r, 'оқылмаған')

    def test_authed_no_notifs_no_badge_number(self):
        _login_as(self.client, 'no_notifs_user')
        r = self.client.get(reverse('core:home'))
        # У этого юзера 0 — текст «оқылмаған» в aria-label не должен появиться
        self.assertNotContains(r, 'оқылмаған')

    def test_guest_no_bell_at_all(self):
        r = self.client.get(reverse('core:home'))
        self.assertNotContains(r, 'Хабарламалар (')
