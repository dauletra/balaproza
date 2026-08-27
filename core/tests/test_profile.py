"""PROF — свой и чужой профиль, знаки, конкурсная биография.

Разделение, которое здесь проверяется чаще прочего, — **кто зритель**
(BR-73): посторонний видит только публичное, и однажды эти две выдачи уже
склеили — на `/u/<username>/` висели черновик и работа на модерации.
"""

from pathlib import Path

from core.tests.base import TestCase, login_as, login_as_newcomer
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from core import data
from core.models import Follow, User

TEMPLATES = Path(__file__).resolve().parents[2] / 'templates'


class PublicStatsHelper(TestCase):
    """Числа, которые видит посторонний, — только по публичным работам."""

    def test_works_matches_author_works(self):
        # Одно правило публичности, посчитанное один раз: если эти два числа
        # разойдутся, профиль и карточка автора на STORY снова будут врать
        # друг про друга (у aidana было 5 против 3).
        for a in data.all_authors():
            with self.subTest(author=a.username):
                self.assertEqual(data.public_stats(a.username)['works'], a.works)

    def test_sums_run_over_public_stories_only(self):
        # У черновиков в стабе 0 просмотров и 0 лайков, поэтому сравнение
        # «публичная сумма меньше полной» ничего бы не доказало: сверяем с
        # суммой по public_stories_of напрямую.
        for a in data.all_authors():
            pub = data.public_stories_of(a.username)
            stats = data.public_stats(a.username)
            with self.subTest(author=a.username):
                self.assertEqual(stats['reads'], sum(s.views for s in pub))
                self.assertEqual(stats['likes'], sum(s.likes for s in pub))

    def test_hidden_work_does_not_reach_works_count(self):
        hidden = [s for s in data.my_stories_of('aidana') if not s.is_public]
        self.assertTrue(hidden, 'фикстура сломана: у aidana нет непубличных работ')
        self.assertEqual(
            data.public_stats('aidana')['works'],
            len(data.my_stories_of('aidana')) - len(hidden),
        )

    def test_public_stats_unknown_user(self):
        stats = data.public_stats('no-such-user')
        self.assertEqual(
            [stats['works'], stats['reads'], stats['likes'], stats['followers']],
            [0, 0, 0, 0],
        )


class PublicStoriesHelper(TestCase):

    def test_excludes_non_public_statuses(self):
        pub = data.public_stories_of('aidana')
        self.assertTrue(all(s.is_public for s in pub))
        slugs = {s.slug for s in pub}
        self.assertNotIn('aidana-kus', slugs)     # NotPublished
        self.assertNotIn('aidana-erteg', slugs)   # OnModeration

    def test_keeps_serials(self):
        # DEC-37: публичный сериал носит OnProcess/Completed. Фильтр по
        # литералу 'Published' молча выкинул бы их все.
        pub = data.public_stories_of('rudazov')
        self.assertEqual(len(pub), 3)
        self.assertIn('arhimag', {s.slug for s in pub})   # OnProcess

    def test_unknown_user_is_empty(self):
        self.assertEqual(data.public_stories_of('no-such-user'), [])


class ReaderStatsHelper(TestCase):

    def test_reader_stats_for_aidana(self):
        stats = data.reader_stats('aidana')
        # Публичные числа те же, что у постороннего: свой профиль не показывает
        # владельцу другую арифметику, чем читателю.
        self.assertEqual(stats['works'], data.public_stats('aidana')['works'])
        # Сверх них — приватное
        self.assertEqual(stats['works_total'], len(data.my_stories_of('aidana')))
        self.assertGreater(stats['works_total'], stats['works'])
        self.assertEqual(stats['finished'], 1)
        self.assertEqual(stats['followers'], User.objects.get(username='aidana').followers)

    def test_reader_stats_unknown_user(self):
        stats = data.reader_stats('no-such-user')
        self.assertEqual(stats['works'], 0)
        self.assertEqual(stats['works_total'], 0)
        self.assertEqual(stats['finished'], 0)
        self.assertEqual(stats['followers'], 0)


class FollowGraph(TestCase):

    def test_is_following_true(self):
        self.assertTrue(data.is_following('aidana', 'rudazov'))

    def test_is_following_false(self):
        self.assertFalse(data.is_following('aidana', 'bekzhan_t'))

    def test_following_returns_authors(self):
        f = data.following_of('aidana')
        self.assertEqual(len(f), 3)
        usernames = {a.username for a in f}
        self.assertEqual(usernames, {'rudazov', 'sayyn', 'dina_books'})

    def test_followers_returns_authors(self):
        # На aidana подписан только aygerim_k.
        f = data.followers_of('aidana')
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].username, 'aygerim_k')

    def test_unknown_user_no_follow(self):
        self.assertEqual(data.following_of('no-such-user'), [])
        self.assertEqual(data.followers_of('no-such-user'), [])


class ProfileMeGuest(TestCase):

    def test_guest_sees_gate(self):
        r = self.client.get(reverse('core:profile_me'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'кір')
        # Реальные данные не светим
        self.assertNotContains(r, 'Айдана Серікқызы')


class ProfileMeAuthed(TestCase):

    def setUp(self):
        login_as(self.client)

    def test_default_tab_is_works(self):
        r = self.client.get(reverse('core:profile_me'))
        self.assertEqual(r.status_code, 200)
        # DEC-44: вкладка показывает публичные работы — то же, что видит
        # читатель. Черновик и работа на модерации сюда не попадают.
        for s in data.public_stories_of('aidana'):
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
        self.assertContains(r, 'Реакциялар')
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

    def test_active_segment_is_marked_for_screen_readers(self):
        # `role="tab"` убран (обещал панель, которой нет) — состояние
        # активного сегмента несёт aria-current, и оно обязано быть ровно одно.
        r = self.client.get(reverse('core:profile_me') + '?tab=about')
        html = r.content.decode()
        self.assertEqual(html.count('aria-current="page"'), 1)
        self.assertNotIn('aria-selected', html)

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
        self.assertContains(r, len(data.my_stories_of('aidana')))
        self.assertContains(r, 'жобалармен бірге')

    def test_unknown_tab_falls_back_to_works(self):
        r = self.client.get(reverse('core:profile_me') + '?tab=garbage')
        self.assertEqual(r.status_code, 200)
        # рендерится как works → виден список рассказов
        self.assertContains(r, 'Таң алдында')


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
        login_as(self.client, 'bekzhan_t')   # bekzhan_t подписан на rudazov
        r = self.client.get(reverse('core:profile_other', kwargs={'username': self.USERNAME}))
        # «Уже подписан» — кнопка «Жазылдың», ведущая в настоящий POST
        self.assertContains(r, 'Жазылдың')
        self.assertContains(r, reverse('core:follow_toggle',
                                       kwargs={'username': self.USERNAME}))

    def test_authed_not_following_sees_subscribe(self):
        login_as(self.client, 'sayyn')       # sayyn НЕ подписан на rudazov
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
        hidden = [s for s in data.my_stories_of('aidana') if not s.is_public]
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
        # У sayyn три публичные работы, и все три уже стоят в теле вкладки —
        # топ-3 рядом был бы копией соседней колонки, поэтому блока нет.
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'sayyn'}))
        self.assertEqual(len(data.public_stories_of('sayyn')), 3)
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
        self.assertNotContains(r, User.objects.get(username=self.USERNAME).name)
        self.assertNotContains(r, 'жобалармен бірге')

    def test_other_profile_has_no_library_tab(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': self.USERNAME}))
        # У чужого профиля segment library — НЕ показываем
        self.assertNotContains(r, '?tab=library')


class ProfileIsNotASecondCabinet(TestCase):
    """DEC-44: профиль — публичный вид на автора, кабинет — рабочее место.

    `/me/?tab=works` рендерил `my_stories_of` строками `my_story_row`, то
    есть ровно список из `/my-stories/` минус полоса внимания. Две страницы
    с одним содержимым, и ни одна не отвечала, зачем она.
    """

    def setUp(self):
        login_as(self.client)

    def test_owner_sees_what_a_reader_sees(self):
        r = self.client.get(reverse('core:profile_me'))
        self.assertEqual(
            [s.slug for s in r.context['works']],
            [s.slug for s in data.public_stories_of('aidana')],
        )

    def test_drafts_and_moderation_stay_in_the_cabinet(self):
        r = self.client.get(reverse('core:profile_me'))
        for slug in ('aidana-kus', 'aidana-erteg'):
            with self.subTest(story=slug):
                self.assertNotContains(r, data.story_by_slug(slug).title)

    def test_the_hidden_ones_are_counted_and_linked(self):
        # Молча спрятать работы нельзя: автор должен видеть, что их не
        # потеряли, и знать, где они лежат.
        r = self.client.get(reverse('core:profile_me'))
        self.assertEqual(r.context['hidden_n'], 2)
        self.assertContains(r, reverse('core:my_stories'))

    def test_the_status_rows_are_gone(self):
        # `my_story_row` — строка кабинета: статус, «когда трогали», меню.
        r = self.client.get(reverse('core:profile_me'))
        self.assertNotContains(r, 'Сайтта қарау')

    def test_segment_count_matches_the_visible_list(self):
        r = self.client.get(reverse('core:profile_me'))
        item = next(i for i in r.context['prof_items'] if i['slug'] == 'works')
        self.assertEqual(item['count'], len(r.context['works']))

    def test_owner_and_stranger_count_works_the_same_way(self):
        mine = self.client.get(reverse('core:profile_me')).context['prof_items']
        theirs = self.client.get(
            reverse('core:profile_other', kwargs={'username': 'aidana'})).context['prof_items']
        self.assertEqual(
            next(i['count'] for i in mine if i['slug'] == 'works'),
            next(i['count'] for i in theirs if i['slug'] == 'works'),
        )

    def test_the_private_breakdown_is_still_reachable(self):
        # Информация о черновиках не потеряна — она во вкладке «Статистика»,
        # помеченной «Тек саған көрінеді» (FR-PROF-08).
        r = self.client.get(reverse('core:profile_me') + '?tab=stats')
        self.assertContains(r, 'Тек саған көрінеді')
        self.assertEqual(r.context['writer']['total'],
                         len(data.my_stories_of('aidana')))


class TopStoriesHelper(TestCase):
    """`top_stories_of` — данные для рейла чужого профиля (FR-PROF-09)."""

    def test_sorted_by_views_desc(self):
        top = data.top_stories_of('aygerim_k')
        self.assertEqual([s.views for s in top], sorted((s.views for s in top), reverse=True))

    def test_only_public_work_reaches_the_rail(self):
        # У aidana есть черновик и работа на модерации: рейл — публичная
        # поверхность, и BR-73 действует здесь ровно так же, как в теле.
        slugs = {s.slug for s in data.top_stories_of('aidana', limit=99)}
        self.assertNotIn('aidana-kus', slugs)
        self.assertNotIn('aidana-erteg', slugs)
        self.assertTrue(all(s.is_public for s in data.top_stories_of('aidana', limit=99)))

    def test_limit_is_respected(self):
        self.assertLessEqual(len(data.top_stories_of('aygerim_k')), 3)
        self.assertEqual(len(data.top_stories_of('aygerim_k', limit=1)), 1)

    def test_unknown_user_is_empty(self):
        self.assertEqual(data.top_stories_of('no-such-user'), [])


class ProfileRailByViewer(TestCase):
    """Рейл профиля разный по зрителю (FR-PROF-09).

    Чужой профиль показывал «Жазылулар» — на кого подписан **он**. Читателю
    это не сообщало ничего и занимало единственный блок колонки.
    """

    def test_stranger_does_not_see_whom_the_author_follows(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'aygerim_k'}))
        self.assertTrue(data.following_of('aygerim_k'))   # подписки есть
        self.assertNotContains(r, 'Жазылулар')                 # и они не здесь

    def test_stranger_sees_the_most_read_work(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'aygerim_k'}))
        self.assertContains(r, 'Ең көп оқылғаны')
        self.assertTrue(r.context['has_right_rail'])
        self.assertContains(r, data.top_stories_of('aygerim_k')[0].title)

    def test_rail_stays_away_when_the_body_already_shows_everything(self):
        # Три работы: вкладка «Шығармалар» показывает их целиком, топ-3
        # рядом был бы дублем — тем же, за который убирали числа из рейла.
        url = reverse('core:profile_other', kwargs={'username': 'rudazov'})
        self.assertEqual(len(data.public_stories_of('rudazov')), 3)
        self.assertFalse(self.client.get(url).context['has_right_rail'])
        # На «Туралы» работ в теле нет вовсе — там блок полезен с первой.
        self.assertTrue(self.client.get(url + '?tab=about').context['has_right_rail'])

    def test_owner_still_gets_the_list_of_who_he_reads(self):
        login_as(self.client)
        r = self.client.get(reverse('core:profile_me'))
        self.assertContains(r, 'Жазылулар')
        self.assertNotContains(r, 'Ең көп оқылғаны')


class ProfilePeoplePages(TestCase):
    """Подписчики и подписки открываются страницей (FR-PROF-10, BR-75)."""

    def _url(self, username, kind):
        return reverse('core:profile_people', kwargs={'username': username, 'kind': kind})

    def test_followers_list_names_everyone(self):
        r = self.client.get(self._url('rudazov', 'followers'))
        self.assertEqual(r.status_code, 200)
        for a in data.followers_of('rudazov'):
            self.assertContains(r, a.public_name)

    def test_following_list_names_everyone(self):
        r = self.client.get(self._url('aidana', 'following'))
        for a in data.following_of('aidana'):
            self.assertContains(r, a.public_name)

    def test_both_lists_are_public(self):
        # BR-75: число подписчиков и так объявлено плиткой профиля, а
        # подписки показывал рейл. Гость получает обе страницы.
        for kind in ('followers', 'following'):
            with self.subTest(kind=kind):
                self.assertEqual(self.client.get(self._url('aidana', kind)).status_code, 200)

    def test_segments_carry_real_paths_not_query(self):
        r = self.client.get(self._url('aidana', 'followers'))
        self.assertContains(r, self._url('aidana', 'following'))
        self.assertNotContains(r, '?tab=following')

    def test_segment_counts_match_the_lists(self):
        r = self.client.get(self._url('aidana', 'followers'))
        counts = {it['slug']: it['count'] for it in r.context['people_items']}
        self.assertEqual(counts['followers'], len(data.followers_of('aidana')))
        self.assertEqual(counts['following'], len(data.following_of('aidana')))

    def test_empty_list_explains_itself(self):
        # rudazov ни на кого не подписан.
        self.assertEqual(data.following_of('rudazov'), [])
        r = self.client.get(self._url('rudazov', 'following'))
        self.assertContains(r, 'Әлі ешкімге жазылмаған')

    def test_unknown_kind_is_404(self):
        # Молчаливый фолбэк отдал бы подписчиков под чужим заголовком.
        self.assertEqual(self.client.get('/u/aidana/garbage/').status_code, 404)

    def test_unknown_author_is_404(self):
        self.assertEqual(self.client.get(self._url('no-such-user', 'followers')).status_code, 404)

    def test_follow_button_stays_on_the_profile(self):
        # Кнопка рядом с одним именем просит решение раньше, чем показано,
        # на основании чего его принимать. Строка ведёт в профиль, где она
        # стоит рядом с био, работами и знаками.
        r = self.client.get(self._url('rudazov', 'followers'))
        self.assertNotContains(r, 'Жазылдың')
        self.assertContains(r, reverse('core:profile_other', kwargs={'username': 'aidana'}))


class ProfileStatTilesLinkToLists(TestCase):
    """Числа профиля кликабельны там, где за ними стоит список (FR-PROF-10)."""

    def test_followers_tile_opens_the_list(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'rudazov'}))
        self.assertContains(r, reverse('core:profile_people',
                                       kwargs={'username': 'rudazov', 'kind': 'followers'}))

    def test_works_tile_opens_the_segment(self):
        login_as(self.client)
        r = self.client.get(reverse('core:profile_me'))
        self.assertContains(r, '/me/?tab=works')

    def test_sums_get_no_link(self):
        # «Оқылым» и «Реакциялар» — суммы, открывать в них нечего. Две ссылки
        # на четыре плитки, и ни одной лишней.
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'rudazov'}))
        self.assertEqual(r.content.decode().count('class="absolute inset-0 rounded-lg"'), 2)


class ProfileOtherUnknown(TestCase):

    def test_unknown_user_is_404(self):
        """Заглушка с кодом 200 позволяла проиндексировать любой @username."""
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'ghost'}))
        self.assertEqual(r.status_code, 404)


class ProfileAchievementsRender(TestCase):
    """Ряд знаков и строка фактов (FR-PROF-06)."""

    def test_badges_render_on_other_profile(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'dina_books'}))
        ach = data.achievements_of('dina_books')
        self.assertTrue(ach)
        for a in ach:
            with self.subTest(key=a['key']):
                self.assertContains(r, a['label'])

    def test_owner_sees_the_same_badges(self):
        """Достижение публично по определению — набор не зависит от зрителя."""
        login_as(self.client)
        mine = self.client.get(reverse('core:profile_me'))
        theirs = self.client.get(reverse('core:profile_other', kwargs={'username': 'aidana'}))
        for a in data.achievements_of('aidana'):
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
        self.assertEqual(len(data.submissions_of('aidana')), 2)
        self.assertContains(r, '2 байқау')

    def test_facts_line_omits_contests_when_none(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'aygerim_k'}))
        self.assertEqual(data.submissions_of('aygerim_k'), [])
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

    JURY_NOTE = 'Көлемі шарттан аз'

    def test_helper_hides_note_from_strangers(self):
        public = data.contest_history('aidana')
        mine = data.contest_history('aidana', is_self=True)
        self.assertEqual([i['note'] for i in public], ['', ''])
        self.assertTrue(any(self.JURY_NOTE in i['note'] for i in mine))

    def test_helper_hides_rejection_and_review_from_strangers(self):
        # Публично «қаралуда» и «қабылданбады» одинаково выглядят участием,
        # поэтому отказ нельзя ни увидеть, ни отличить от ожидания.
        for item in data.contest_history('aidana'):
            with self.subTest(contest=item['contest'].slug):
                self.assertIn(item['result'], ('', *data.PUBLIC_CONTEST_RESULTS))
        mine = {i['result'] for i in data.contest_history('aidana', is_self=True)}
        self.assertEqual(mine, {'reviewing', 'rejected'})

    def test_winner_is_derived_from_contest_not_status(self):
        # У dina_books заявка помечена accepted, а победа лежит в
        # Contest.winners: без вывода из данных «Жеңімпаз» не появился бы.
        hist = data.contest_history('dina_books')
        winners = [i for i in hist if i['result'] == 'winner']
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0]['contest'].slug, 'zhas-aldym-2023')

    def test_row_count_matches_the_facts_line(self):
        """Строк столько же, сколько подач — иначе отказ считается вычитанием."""
        for username in ('aidana', 'dina_books', 'bekzhan_t'):
            with self.subTest(user=username):
                self.assertEqual(
                    len(data.contest_history(username)),
                    len(data.submissions_of(username)),
                )

    def test_newest_first(self):
        years = [i['year'] for i in data.contest_history('aidana')]
        self.assertEqual(years, sorted(years, reverse=True))

    def test_non_public_work_is_not_named_to_strangers(self):
        # BR-73: подача на конкурс не должна раскрывать снятую с публикации
        # работу. В фикстуре все поданные работы публичны, поэтому проверяем
        # само правило, а не текущее совпадение данных.
        for username in ('aidana', 'dina_books', 'bekzhan_t'):
            for item in data.contest_history(username):
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
        login_as(self.client)
        r = self.client.get(reverse('core:profile_me') + '?tab=about')
        self.assertContains(r, self.JURY_NOTE)
        self.assertContains(r, 'Қабылданбады')
        self.assertContains(r, 'Қаралуда')

    def test_page_shows_winner_badge(self):
        """Строка называет номинацию, а не общее «Жеңімпаз» (DEC-46):
        «Оқырман таңдауы» и «Бас жүлде» — разные вещи, и одинаковая
        подпись у обеих скрывала бы, что именно взял автор."""
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'dina_books'}) + '?tab=about')
        self.assertContains(r, 'Оқырман таңдауы')
        self.assertContains(r, '2023')

    def test_history_empty_for_author_without_submissions(self):
        self.assertEqual(data.contest_history('aygerim_k'), [])
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'aygerim_k'}) + '?tab=about')
        self.assertEqual(r.context['contest_history'], [])
        # Слово «Байқаулар» само по себе не показатель — оно есть в шапке
        # и в подвале. Проверяем, что нет ни одного названия конкурса.
        for c in data.all_contests():
            with self.subTest(contest=c.slug):
                self.assertNotContains(r, c.name)


class AwardRegistry(TestCase):
    """Один реестр на «что получено» и «что можно получить» (FR-PROF-08)."""

    def test_catalog_and_row_come_from_the_same_source(self):
        for a in data.all_authors():
            earned_row = {x['key'] for x in data.achievements_of(a.username)
                          if x['key'] != 'reads'}
            earned_cat = {x['key'] for x in data.award_catalog(a.username)
                          if x['earned']}
            with self.subTest(author=a.username):
                self.assertEqual(earned_row, earned_cat)

    def test_catalog_lists_every_award_for_everyone(self):
        keys = [x.key for x in data.AWARDS]
        for a in data.all_authors():
            with self.subTest(author=a.username):
                self.assertEqual([x['key'] for x in data.award_catalog(a.username)], keys)

    def test_every_award_explains_how_to_get_it(self):
        for a in data.AWARDS:
            with self.subTest(award=a.key):
                self.assertTrue(a.hint.strip())
                self.assertNotEqual(a.hint, a.label)

    def test_dim_is_the_inverse_of_earned(self):
        for a in data.all_authors():
            for item in data.award_catalog(a.username) + data.read_ladder(a.username):
                with self.subTest(author=a.username, key=item.get('key') or item.get('threshold')):
                    self.assertEqual(item['dim'], not item['earned'])

    def test_ladder_marks_exactly_one_next_step(self):
        for a in data.all_authors():
            ladder = data.read_ladder(a.username)
            with self.subTest(author=a.username):
                self.assertEqual(len(ladder), len(data.READ_TIERS))
                self.assertLessEqual(sum(1 for s in ladder if s['is_next']), 1)
                # Пройденные идут подряд с начала: ступень нельзя перепрыгнуть.
                earned = [s['earned'] for s in ladder]
                self.assertEqual(earned, sorted(earned, reverse=True))

    def test_ladder_left_is_zero_once_taken(self):
        for a in data.all_authors():
            for s in data.read_ladder(a.username):
                with self.subTest(author=a.username, step=s['threshold']):
                    if s['earned']:
                        self.assertEqual(s['left'], 0)
                    else:
                        self.assertGreater(s['left'], 0)

    def test_unknown_user_gets_full_catalog_with_nothing_earned(self):
        cat = data.award_catalog('ghost')
        self.assertEqual(len(cat), len(data.AWARDS))
        self.assertFalse(any(x['earned'] for x in cat))


class ProfileStatsTab(TestCase):
    """Вкладка «Статистика» — приватная и не повторяет кабинет."""

    def setUp(self):
        login_as(self.client)

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
        for _, label in data.READ_TIERS:
            with self.subTest(tier=label):
                self.assertContains(r, label)

    def test_shows_unearned_awards_with_hints(self):
        r = self.client.get(reverse('core:profile_me') + '?tab=stats')
        unearned = [a for a in data.award_catalog('aidana') if not a['earned']]
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

    MARKER = '<symbol id="award-first-publication"'

    def test_row_only(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'rudazov'}))
        self.assertEqual(r.content.decode().count(self.MARKER), 1)

    def test_row_and_stats_tab_together(self):
        login_as(self.client)
        r = self.client.get(reverse('core:profile_me') + '?tab=stats')
        self.assertTrue(r.context['achievements'])
        self.assertEqual(r.content.decode().count(self.MARKER), 1)

    def test_stats_tab_without_any_award(self):
        # Автор без единой награды всё равно должен увидеть серые плитки:
        # спрятанная награда не отвечает на вопрос «что дальше».
        login_as_newcomer(self.client, 'lonely_writer')
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


class ContestAwardsInProfile(TestCase):
    """DEC-46: награды конкурсов стоят тем же рядом, что и системные знаки."""

    def test_helper_returns_awards_for_a_winner(self):
        awards = data.contest_awards_of('bekzhan_t')
        self.assertEqual([a['title'] for a in awards], ['Бас жүлде'])
        self.assertEqual(awards[0]['year'], 2023)

    def test_helper_is_empty_for_an_author_without_awards(self):
        self.assertEqual(data.contest_awards_of('aidana'), [])
        self.assertEqual(data.contest_awards_of('ghost'), [])

    def test_shape_is_complete(self):
        for a in data.all_authors():
            for item in data.contest_awards_of(a.username):
                with self.subTest(author=a.username, key=item['key']):
                    self.assertEqual(
                        set(item),
                        {'key', 'title', 'image', 'contest', 'story', 'year', 'note'})
                    self.assertTrue(item['title'])

    def test_row_renders_the_emblem(self):
        r = self.client.get(reverse('core:profile_other',
                                    kwargs={'username': 'bekzhan_t'}))
        award = data.contest_awards_of('bekzhan_t')[0]
        self.assertContains(r, f"/media/{award['image']}")

    def test_tooltip_names_both_nomination_and_contest(self):
        """Медальон без подписи; смысл несёт тултип (BR-ACH-06), и одной
        номинации мало — «Бас жүлде» бывает у каждого конкурса."""
        r = self.client.get(reverse('core:profile_other',
                                    kwargs={'username': 'bekzhan_t'}))
        self.assertContains(r, 'Бас жүлде · Жас алдым — 2023')

    def test_award_survives_the_work_being_unpublished(self):
        """Работа скрыта — награда остаётся: она принадлежит автору, а не
        видимости текста (BR-73)."""
        for a in data.all_authors():
            for item in data.contest_awards_of(a.username):
                with self.subTest(author=a.username, key=item['key']):
                    self.assertTrue(item['title'])
                    if item['story'] is not None:
                        self.assertTrue(item['story'].is_public)

    def test_author_without_contest_awards_shows_no_medallion(self):
        """Системные знаки у неё есть, конкурсных нет — и медальона тоже."""
        self.assertFalse(data.contest_awards_of('aidana'))
        r = self.client.get(reverse('core:profile_other',
                                    kwargs={'username': 'aidana'}))
        self.assertNotContains(r, '/media/awards/')


# ───────────────────────────────────────────────────────────────────────
# Ф15, Этап 6: редактирование профиля — настоящий POST.
# ───────────────────────────────────────────────────────────────────────

class ProfileEditSavesFields(TestCase):

    def setUp(self):
        login_as(self.client)

    def _post(self, **overrides):
        payload = {
            'pen_name': 'Жаңа лақап', 'name': 'Жаңа есім',
            'bio': 'Жаңа био.', 'gender': 'girl', 'age': '16',
        }
        payload.update(overrides)
        return self.client.post(reverse('core:profile_me_edit'), payload)

    def test_saves_all_fields(self):
        self._post()
        user = User.objects.get(username='aidana')
        self.assertEqual(user.pen_name, 'Жаңа лақап')
        self.assertEqual(user.name, 'Жаңа есім')
        self.assertEqual(user.bio, 'Жаңа био.')
        self.assertEqual(user.gender, 'girl')
        self.assertEqual(user.age, 16)

    def test_redirects_to_the_profile(self):
        r = self._post()
        self.assertRedirects(r, reverse('core:profile_me'))

    def test_blank_age_and_gender_are_allowed(self):
        self._post(age='', gender='')
        user = User.objects.get(username='aidana')
        self.assertIsNone(user.age)
        self.assertEqual(user.gender, '')

    def test_bio_may_be_cleared(self):
        self._post(bio='')
        self.assertEqual(User.objects.get(username='aidana').bio, '')


class ProfileEditValidation(TestCase):

    def setUp(self):
        login_as(self.client)

    def _post(self, **overrides):
        payload = {
            'pen_name': 'Аты', 'name': 'Есім', 'bio': '', 'gender': '', 'age': '',
        }
        payload.update(overrides)
        return self.client.post(reverse('core:profile_me_edit'), payload)

    def _pen_name(self):
        return User.objects.get(username='aidana').pen_name

    def test_missing_pen_name_saves_nothing(self):
        before = self._pen_name()
        self._post(pen_name='')
        self.assertEqual(self._pen_name(), before)

    def test_missing_name_saves_nothing(self):
        before = User.objects.get(username='aidana').name
        self._post(name='')
        self.assertEqual(User.objects.get(username='aidana').name, before)

    def test_too_long_pen_name_saves_nothing(self):
        before = self._pen_name()
        self._post(pen_name='ә' * 61)
        self.assertEqual(self._pen_name(), before)

    def test_too_long_bio_saves_nothing(self):
        before = User.objects.get(username='aidana').bio
        self._post(bio='ә' * 201)
        self.assertEqual(User.objects.get(username='aidana').bio, before)

    def test_invalid_gender_saves_nothing(self):
        before = User.objects.get(username='aidana').gender
        self._post(gender='alien')
        self.assertEqual(User.objects.get(username='aidana').gender, before)

    def test_non_numeric_age_saves_nothing(self):
        before = User.objects.get(username='aidana').age
        self._post(age='abc')
        self.assertEqual(User.objects.get(username='aidana').age, before)

    def test_out_of_range_age_saves_nothing(self):
        before = User.objects.get(username='aidana').age
        self._post(age='999')
        self.assertEqual(User.objects.get(username='aidana').age, before)

    def test_validation_error_redirects_back_to_the_form(self):
        r = self._post(pen_name='')
        self.assertRedirects(r, reverse('core:profile_me_edit'))


class ProfileEditAvatarUpload(TestCase):
    """Тот же валидатор, что у Story.cover (BR-46) — SVG не проходит."""

    def setUp(self):
        login_as(self.client)

    def _post(self, avatar):
        return self.client.post(reverse('core:profile_me_edit'), {
            'pen_name': 'Аты', 'name': 'Есім', 'bio': '', 'gender': '',
            'age': '', 'avatar': avatar,
        })

    def test_png_is_accepted_and_lands_under_the_username(self):
        avatar = SimpleUploadedFile('фото.png', b'\x89PNG demo',
                                    content_type='image/png')
        self._post(avatar)
        user = User.objects.get(username='aidana')
        self.assertTrue(user.avatar.name.startswith('avatars/aidana'))
        self.assertTrue(user.avatar.name.endswith('.png'))

    def test_svg_is_refused(self):
        avatar = SimpleUploadedFile('фото.svg', b'<svg/>',
                                    content_type='image/svg+xml')
        self._post(avatar)
        self.assertFalse(User.objects.get(username='aidana').avatar)

    def test_svg_refusal_also_blocks_the_rest_of_the_form(self):
        """Ошибка одного поля — весь POST no-op, не частичное сохранение."""
        before = User.objects.get(username='aidana').pen_name
        avatar = SimpleUploadedFile('фото.svg', b'<svg/>',
                                    content_type='image/svg+xml')
        self.client.post(reverse('core:profile_me_edit'), {
            'pen_name': 'Басқа аты', 'name': 'Есім', 'bio': '',
            'gender': '', 'age': '', 'avatar': avatar,
        })
        self.assertEqual(User.objects.get(username='aidana').pen_name, before)


class ProfileEditGuestPostChangesNothing(TestCase):

    def test_guest_post_creates_nothing(self):
        guest = Client()
        before = User.objects.get(username='aidana').pen_name
        guest.post(reverse('core:profile_me_edit'), {
            'pen_name': 'Бөгде', 'name': 'Бөгде', 'bio': '', 'gender': '', 'age': '',
        })
        self.assertEqual(User.objects.get(username='aidana').pen_name, before)


class ProfileEditPrefillsRawPenName(TestCase):
    """`value=` раньше показывал `public_name` (pen_name or '@username'),
    не сырое поле: пустой pen_name автора отрисовался бы как «@username»,
    и несохранённая форма сохранила бы это буквально при первом же POST."""

    def test_blank_pen_name_shows_empty_not_at_username(self):
        user = User.objects.create_user(username='blankpen', password='x')
        self.assertEqual(user.pen_name, '')
        self.client.force_login(user)
        html = self.client.get(reverse('core:profile_me_edit')).content.decode()
        self.assertNotIn('value="@blankpen"', html)


class FollowingAnAuthorIsWrittenDown(TestCase):
    """Кнопка «Жазылу» заводит подписку (FR-PROF-04, BR-75).

    Обе формы — в шапке профиля и в карточке автора — стояли с
    `action="#"` и отвечали тостом «(демо)». Строки `Follow` при этом
    существовали и обслуживали списки: подписаться было нельзя, а
    отписаться от того, что положил сид, — тем более.
    """

    TARGET = 'rudazov'

    def _url(self, username=None):
        return reverse('core:follow_toggle',
                       kwargs={'username': username or self.TARGET})

    def _links(self, username=None):
        return Follow.objects.filter(
            following__username=username or self.TARGET).count()

    def _stored(self, username=None):
        return User.objects.get(username=username or self.TARGET).followers

    def test_subscribing_creates_the_link_and_moves_the_counter(self):
        login_as(self.client, 'sayyn')       # sayyn ещё не подписан
        before = self._links()
        self.client.post(self._url())
        self.assertEqual(self._links(), before + 1)
        self.assertEqual(self._stored(), before + 1)

    def test_pressing_again_unsubscribes(self):
        login_as(self.client, 'bekzhan_t')   # уже подписан
        before = self._links()
        self.client.post(self._url())
        self.assertEqual(self._links(), before - 1)
        self.assertEqual(self._stored(), before - 1)

    def test_the_stored_counter_always_matches_the_rows(self):
        """`User.followers` — колонка, и разъехаться с записями она не
        должна ни на одном шаге: пересчёт идёт по строкам."""
        login_as(self.client, 'sayyn')
        for _ in range(3):
            self.client.post(self._url())
            self.assertEqual(self._stored(), self._links())

    def test_nobody_follows_themselves(self):
        login_as(self.client, self.TARGET)
        before = self._links()
        self.client.post(self._url())
        self.assertEqual(self._links(), before)

    def test_a_guest_writes_nothing(self):
        before = self._links()
        self.client.post(self._url())
        self.assertEqual(self._links(), before)

    def test_get_writes_nothing(self):
        login_as(self.client, 'sayyn')
        before = self._links()
        self.client.get(self._url())
        self.assertEqual(self._links(), before)

    def test_it_comes_back_where_it_was_pressed(self):
        """Кнопок две и стоят они на разных страницах."""
        login_as(self.client, 'sayyn')
        story_page = reverse('core:story_detail', kwargs={'slug': 'kronchessii'})
        r = self.client.post(self._url(), {'next': story_page})
        self.assertRedirects(r, story_page)

    def test_it_refuses_to_leave_the_site(self):
        login_as(self.client, 'sayyn')
        r = self.client.post(self._url(), {'next': '//evil.example/'})
        self.assertRedirects(r, reverse('core:profile_other',
                                        kwargs={'username': self.TARGET}))

    def test_unknown_author_writes_nothing(self):
        login_as(self.client, 'sayyn')
        before = Follow.objects.count()
        self.client.post(self._url('no-such-user'))
        self.assertEqual(Follow.objects.count(), before)


class AchievementsAreDerivedNotStored(TestCase):
    """Знаки автора выводятся из его работ (BR-ACH-01, DEC-41).

    Колонки «награды автора» нет и быть не может — она разошлась бы с тем,
    что человек сделал. Рейтинга здесь тоже нет: знак говорит «ты
    сделал», рейтинг — «ты хуже вон того», и аудитории 14-18 второе не
    нужно.

    Проверки идут по всему корпусу, потому что вопрос именно такой:
    выполняется ли правило **для каждого** автора. Раньше это был десяток
    отдельных классов в `test_corpus`.
    """

    def _all(self):
        return [(a.username, ach)
                for a in data.all_authors()
                for ach in data.achievements_of(a.username)]

    def test_shape_and_uniqueness(self):
        self.assertEqual(data.achievements_of('ghost'), [])
        for username, ach in self._all():
            with self.subTest(author=username, key=ach.get('key')):
                self.assertEqual(set(ach), {'key', 'label', 'art', 'tier'})
                self.assertTrue(ach['label'])
                self.assertTrue(ach['art'])
                self.assertIn(ach['tier'], data.AWARD_TIERS)
        for author in data.all_authors():
            marks = data.achievements_of(author.username)
            with self.subTest(author=author.username):
                keys = [m['key'] for m in marks]
                arts = [m['art'] for m in marks]
                self.assertEqual(len(keys), len(set(keys)))
                self.assertEqual(len(arts), len(set(arts)))

    def test_only_the_highest_read_tier_is_shown(self):
        """«Мың» и «Он мың» рядом говорят одно и то же."""
        for author in data.all_authors():
            reads = [m for m in data.achievements_of(author.username)
                     if m['key'] == 'reads']
            with self.subTest(author=author.username):
                self.assertLessEqual(len(reads), 1)
                if reads:
                    self.assertEqual(reads[0]['label'],
                                     data.read_tier(author.username)[1])

    def test_gold_stays_rare(self):
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

    def test_every_tier_has_art(self):
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
            keys = {m['key'] for m in data.achievements_of(author.username)}
            with self.subTest(author=author.username):
                has_public_pick = any(
                    editorial in s.badges
                    for s in data.public_stories_of(author.username))
                self.assertEqual('editorial_choice' in keys, has_public_pick)
                if data.contest_awards_of(author.username):
                    self.assertIn('contest_participant', keys)
                    self.assertIn('contest_accepted', keys)
                if 'finished_serial' in keys:
                    self.assertTrue(any(
                        s.is_serial and s.status == 'Completed'
                        for s in data.public_stories_of(author.username)))
