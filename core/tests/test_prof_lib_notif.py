"""PROF / LIB / NOTIF — три родственных авторизованных раздела."""

import re
from html.parser import HTMLParser
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
        for b in stub_data.NOTIF_BUCKETS:
            self.assertIn(b, g)
        # Раскладка сходится с самими данными: числа-литералы здесь
        # устаревали бы при каждой правке демо-ленты.
        items = stub_data.NOTIFICATIONS_BY_USER['aidana']
        for b in stub_data.NOTIF_BUCKETS:
            self.assertEqual(len(g[b]), sum(1 for n in items if n.bucket == b))
        self.assertTrue(all(g[b] for b in stub_data.NOTIF_BUCKETS),
                        'у aidana должен быть непустым каждый из трёх бакетов')

    def test_unknown_user_empty_buckets(self):
        g = stub_data.notifications_for_user('no-such-user')
        for b in stub_data.NOTIF_BUCKETS:
            self.assertEqual(g[b], [])

    def test_unread_count(self):
        items = stub_data.NOTIFICATIONS_BY_USER['aidana']
        expected = sum(1 for n in items if not n.read and n.bucket)
        self.assertEqual(stub_data.unread_count_for_user('aidana'), expected)
        self.assertGreater(expected, 0)

    def test_unread_zero_for_unknown(self):
        self.assertEqual(stub_data.unread_count_for_user('ghost'), 0)

    def test_notification_kinds_within_set(self):
        for n in stub_data.NOTIFICATIONS_BY_USER['aidana']:
            with self.subTest(kind=n.kind):
                self.assertIn(n.kind, stub_data.NOTIF_KINDS)


class NotificationTime(TestCase):
    """Время уведомления выводится из `days_ago`, а не хранится строкой (BR-70a).

    Хранимые `when="5 күн бұрын"` и `bucket="past_week"` устаревали на
    следующий день — тот же класс ошибки, что `days_left=12` до DEC-45,
    только незаметнее: лента выглядит правдоподобной всегда.
    """

    def test_time_fields_are_not_stored(self):
        stored = stub_data.Notification.__dataclass_fields__
        for gone in ('when', 'bucket'):
            self.assertNotIn(
                gone, stored,
                f'`{gone}` снова стало полем — это хранимое производное (BR-70a)')

    def test_bucket_follows_the_calendar(self):
        cases = {0: 'today', 1: 'yesterday', 2: 'past_week',
                 7: 'past_week', 8: '', 400: ''}
        for days, expected in cases.items():
            with self.subTest(days=days):
                n = stub_data.Notification(kind='like', days_ago=days)
                self.assertEqual(n.bucket, expected)

    def test_older_than_a_week_is_not_shown_and_not_counted(self):
        """Групп три; четвёртой «раньше» в FR-NOTIF-01 нет.

        Значит, событие старше недели в ленту не попадает — и в бейдж
        тоже, иначе шапка звала бы на страницу, где его нет.
        """
        stale = stub_data.Notification(kind='like', days_ago=30)
        with mock.patch.dict(stub_data.NOTIFICATIONS_BY_USER, {'ghost': [stale]}):
            grouped = stub_data.notifications_for_user('ghost')
            self.assertEqual([], [n for b in grouped.values() for n in b])
            self.assertEqual(0, stub_data.unread_count_for_user('ghost'))

    def test_wording_of_kk_ago(self):
        self.assertEqual(stub_data.kk_ago(0, 2), '2 сағат бұрын')
        self.assertEqual(stub_data.kk_ago(0), 'бүгін')
        self.assertEqual(stub_data.kk_ago(1), 'кеше')
        self.assertEqual(stub_data.kk_ago(5), '5 күн бұрын')
        self.assertEqual(stub_data.kk_ago(60), '2 ай бұрын')
        self.assertEqual(stub_data.kk_ago(800), '2 жыл бұрын')

    def test_hours_only_refine_today(self):
        """«26 сағат бұрын» человек переводит в дни сам — короче «кеше»."""
        self.assertEqual(stub_data.kk_ago(1, 26), 'кеше')

    def test_freshest_first_inside_a_bucket(self):
        """Порядок объявления в данных — не порядок ленты.

        Сегодняшние события шли «2 сағат · 4 сағат · 9 сағат · 6 сағат».
        """
        for bucket in stub_data.notifications_for_user('aidana').values():
            keys = [(n.days_ago, n.hours_ago or 0) for n in bucket]
            self.assertEqual(keys, sorted(keys))


class NotificationsLeadSomewhere(TestCase):
    """Уведомление ведёт к своему предмету (FR-NOTIF-05, BR-72a).

    Конкурсное событие знало о конкурсе только по имени внутри `text`
    и потому не вело никуда: прочитав «шорт-лист басталды», автор шёл
    искать конкурс через меню.
    """

    def setUp(self):
        _login_as_aidana(self.client)
        self.response = self.client.get(reverse('core:notifications'))

    def test_contest_notification_links_to_its_contest(self):
        contest_notifs = [n for n in stub_data.NOTIFICATIONS_BY_USER['aidana']
                          if n.kind == 'contest']
        self.assertTrue(contest_notifs, 'стаб потерял конкурсные уведомления')
        for n in contest_notifs:
            with self.subTest(contest=n.contest_slug):
                self.assertTrue(n.contest, 'конкурсное уведомление без конкурса')
                self.assertContains(
                    self.response,
                    reverse('core:contest_detail', kwargs={'slug': n.contest.slug}))

    def test_moderation_notification_links_to_the_story(self):
        mods = [n for n in stub_data.NOTIFICATIONS_BY_USER['aidana']
                if n.kind == 'moderation' and n.story]
        self.assertTrue(mods, 'стаб потерял уведомление о модерации')
        for n in mods:
            with self.subTest(story=n.story_slug):
                # Работа на модерации не публична — вести на неё можно
                # только в авторский кабинет (BR-73).
                self.assertContains(
                    self.response,
                    reverse('core:manage_story', kwargs={'slug': n.story.slug}))

    def test_text_does_not_repeat_the_name_of_its_subject(self):
        """Имя предмета берётся у предмета, а не переписывается литералом.

        Второй литерал разошёлся бы с первым ровно так же, как хранимый
        `Author.works` разошёлся с числом произведений (DEC-40).
        """
        for n in stub_data.NOTIFICATIONS_BY_USER['aidana']:
            if n.kind == 'comment':
                continue  # у комментария `text` — цитата читателя, чужой UGC
            with self.subTest(kind=n.kind):
                if n.contest:
                    self.assertNotIn(n.contest.name.strip('«»'), n.text)
                if n.story:
                    self.assertNotIn(n.story.title, n.text)

    def test_contest_notification_names_the_deadline(self):
        """FR-NOTIF-06: срок считает конкурс, а не текст уведомления."""
        contest = stub_data.CONTESTS_BY_SLUG['bolashak-mektebi']
        self.assertTrue(contest.timing_line)
        self.assertContains(self.response, contest.timing_line)


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
        # DEC-44: вкладка показывает публичные работы — то же, что видит
        # читатель. Черновик и работа на модерации сюда не попадают.
        for s in stub_data.public_stories_of('aidana'):
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
        # У sayyn три публичные работы, и все три уже стоят в теле вкладки —
        # топ-3 рядом был бы копией соседней колонки, поэтому блока нет.
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'sayyn'}))
        self.assertEqual(len(stub_data.public_stories_of('sayyn')), 3)
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


class ProfileIsNotASecondCabinet(TestCase):
    """DEC-44: профиль — публичный вид на автора, кабинет — рабочее место.

    `/me/?tab=works` рендерил `my_stories_of` строками `my_story_row`, то
    есть ровно список из `/my-stories/` минус полоса внимания. Две страницы
    с одним содержимым, и ни одна не отвечала, зачем она.
    """

    def setUp(self):
        _login_as_aidana(self.client)

    def test_owner_sees_what_a_reader_sees(self):
        r = self.client.get(reverse('core:profile_me'))
        self.assertEqual(
            [s.slug for s in r.context['works']],
            [s.slug for s in stub_data.public_stories_of('aidana')],
        )

    def test_drafts_and_moderation_stay_in_the_cabinet(self):
        r = self.client.get(reverse('core:profile_me'))
        for slug in ('aidana-kus', 'aidana-erteg'):
            with self.subTest(story=slug):
                self.assertNotContains(r, stub_data.STORIES_BY_SLUG[slug].title)

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
                         len(stub_data.my_stories_of('aidana')))


class TopStoriesHelper(TestCase):
    """`top_stories_of` — данные для рейла чужого профиля (FR-PROF-09)."""

    def test_sorted_by_views_desc(self):
        top = stub_data.top_stories_of('aygerim_k')
        self.assertEqual([s.views for s in top], sorted((s.views for s in top), reverse=True))

    def test_only_public_work_reaches_the_rail(self):
        # У aidana есть черновик и работа на модерации: рейл — публичная
        # поверхность, и BR-73 действует здесь ровно так же, как в теле.
        slugs = {s.slug for s in stub_data.top_stories_of('aidana', limit=99)}
        self.assertNotIn('aidana-kus', slugs)
        self.assertNotIn('aidana-erteg', slugs)
        self.assertTrue(all(s.is_public for s in stub_data.top_stories_of('aidana', limit=99)))

    def test_limit_is_respected(self):
        self.assertLessEqual(len(stub_data.top_stories_of('aygerim_k')), 3)
        self.assertEqual(len(stub_data.top_stories_of('aygerim_k', limit=1)), 1)

    def test_unknown_user_is_empty(self):
        self.assertEqual(stub_data.top_stories_of('no-such-user'), [])


class ProfileRailByViewer(TestCase):
    """Рейл профиля разный по зрителю (FR-PROF-09).

    Чужой профиль показывал «Жазылулар» — на кого подписан **он**. Читателю
    это не сообщало ничего и занимало единственный блок колонки.
    """

    def test_stranger_does_not_see_whom_the_author_follows(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'aygerim_k'}))
        self.assertTrue(stub_data.following_of('aygerim_k'))   # подписки есть
        self.assertNotContains(r, 'Жазылулар')                 # и они не здесь

    def test_stranger_sees_the_most_read_work(self):
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'aygerim_k'}))
        self.assertContains(r, 'Ең көп оқылғаны')
        self.assertTrue(r.context['has_right_rail'])
        self.assertContains(r, stub_data.top_stories_of('aygerim_k')[0].title)

    def test_rail_stays_away_when_the_body_already_shows_everything(self):
        # Три работы: вкладка «Шығармалар» показывает их целиком, топ-3
        # рядом был бы дублем — тем же, за который убирали числа из рейла.
        url = reverse('core:profile_other', kwargs={'username': 'rudazov'})
        self.assertEqual(len(stub_data.public_stories_of('rudazov')), 3)
        self.assertFalse(self.client.get(url).context['has_right_rail'])
        # На «Туралы» работ в теле нет вовсе — там блок полезен с первой.
        self.assertTrue(self.client.get(url + '?tab=about').context['has_right_rail'])

    def test_owner_still_gets_the_list_of_who_he_reads(self):
        _login_as_aidana(self.client)
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
        for a in stub_data.followers_of('rudazov'):
            self.assertContains(r, a.public_name)

    def test_following_list_names_everyone(self):
        r = self.client.get(self._url('aidana', 'following'))
        for a in stub_data.following_of('aidana'):
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
        self.assertEqual(counts['followers'], len(stub_data.followers_of('aidana')))
        self.assertEqual(counts['following'], len(stub_data.following_of('aidana')))

    def test_empty_list_explains_itself(self):
        # rudazov ни на кого не подписан.
        self.assertEqual(stub_data.following_of('rudazov'), [])
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
        _login_as_aidana(self.client)
        r = self.client.get(reverse('core:profile_me'))
        self.assertContains(r, '/me/?tab=works')

    def test_sums_get_no_link(self):
        # «Оқылым» и «Ұнатулар» — суммы, открывать в них нечего. Две ссылки
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

    JURY_NOTE = 'Көлемі шарттан аз'

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
        """Строка называет номинацию, а не общее «Жеңімпаз» (DEC-46):
        «Оқырман таңдауы» и «Бас жүлде» — разные вещи, и одинаковая
        подпись у обеих скрывала бы, что именно взял автор."""
        r = self.client.get(reverse('core:profile_other', kwargs={'username': 'dina_books'}) + '?tab=about')
        self.assertContains(r, 'Оқырман таңдауы')
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

    MARKER = '<symbol id="award-first-publication"'

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
        # Уникальные тексты по типам
        self.assertContains(self.response, 'пікір қалдырды')   # comment
        self.assertContains(self.response, 'ұнатты')           # like
        self.assertContains(self.response, 'саған жазылды')    # follower
        self.assertContains(self.response, 'жаңа бөлім')       # new_chapter
        self.assertContains(self.response, 'Модерация')        # moderation
        self.assertContains(self.response, 'Байқау')           # contest

    def test_unread_summary_shows_count(self):
        unread = stub_data.unread_count_for_user('aidana')
        self.assertContains(self.response, f'{unread} оқылмаған')

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


class NotificationsHeaderFollowsTheState(TestCase):
    """Шапка не говорит о данных, которых на экране нет (DEC-17).

    Она стояла выше ветвления по `page_state`, поэтому в `?state=error`
    страница одновременно сообщала «жүктеу мүмкін болмады» и «4 оқылмаған»
    — с рабочей кнопкой «барлығын оқылды деп белгілеу».
    """

    def setUp(self):
        _login_as_aidana(self.client)

    def _get(self, state=''):
        url = reverse('core:notifications') + (f'?state={state}' if state else '')
        return self.client.get(url).content.decode()

    def test_content_state_keeps_the_summary(self):
        html = self._get()
        self.assertIn('оқылмаған', html)
        self.assertIn('Барлығын оқылды деп белгілеу', html)

    def test_error_state_drops_summary_and_action(self):
        html = self._get('error')
        self.assertNotIn('Барлығын оқылды деп белгілеу', html)
        self.assertNotIn('оқылмаған.', html)

    def test_loading_state_drops_summary_and_action(self):
        html = self._get('loading')
        self.assertNotIn('Барлығын оқылды деп белгілеу', html)
        self.assertNotIn('оқылмаған.', html)

    def test_heading_survives_every_state(self):
        """Заголовок — часть структуры документа, а не часть данных."""
        for state in ('', 'loading', 'error'):
            with self.subTest(state=state or 'content'):
                self.assertIn('<h1', self._get(state))

    def test_mark_all_posts_somewhere_real(self):
        """`action="#"` без JS отправлял форму в никуда."""
        self.assertNotIn('action="#"', self._get())


class NotificationsRenderFromTheRegistry(TestCase):
    """Секции строит реестр `NOTIF_BUCKETS`, а не три копии блока."""

    def setUp(self):
        _login_as_aidana(self.client)
        self.response = self.client.get(reverse('core:notifications'))

    def test_sections_follow_the_registry_order(self):
        keys = [s['key'] for s in self.response.context['sections']]
        self.assertEqual(keys, [b for b in stub_data.NOTIF_BUCKETS if keys.count(b)])
        self.assertEqual(keys, sorted(keys, key=stub_data.NOTIF_BUCKETS.index))

    def test_empty_bucket_renders_no_heading(self):
        grouped = stub_data.notifications_for_user('aidana')
        lonely = {b: (items if b == 'today' else []) for b, items in grouped.items()}
        with mock.patch.object(stub_data, 'notifications_for_user', return_value=lonely):
            r = self.client.get(reverse('core:notifications'))
        self.assertEqual([s['key'] for s in r.context['sections']], ['today'])
        self.assertNotContains(r, stub_data.NOTIF_BUCKET_LABELS['yesterday'])

    def test_labels_come_from_the_registry(self):
        for s in self.response.context['sections']:
            with self.subTest(bucket=s['key']):
                self.assertEqual(s['label'], stub_data.NOTIF_BUCKET_LABELS[s['key']])

    def test_group_is_a_list(self):
        """`<ul>/<li>`: иначе скринридер не называет число событий в группе."""
        self.assertContains(self.response, '<ul class="flex flex-col gap-3">')


class NotificationIconsFollowTheRegistry(TestCase):
    """Иконку выбирают по значению, а не по наличию формы (docs/04 §4.2).

    Конкурс носил `bookmark-filled` — глиф, который по DEC-09b означает
    активное «сохранено» и стоит на текущей главе и на кнопке «сақталды».
    Модерация носила `check`: галка утверждает «одобрено», хотя событие
    бывает отказом и ожиданием. Лайк носил пару `status-error-*` — токен,
    подписанный в `@theme` как «Отказ и удаление (DEC-39)».
    """

    ITEM = TEMPLATES / 'components' / 'notification_item.html'

    def _chip(self):
        """Блок выбора иконки — без окружающих комментариев.

        Сравнивать с текстом всего файла нельзя: объяснение правки само
        называет глифы, от которых она уводит.
        """
        body = self.ITEM.read_text(encoding='utf-8')
        return body.split('{% endcomment %}\n    <span class="grid', 1)[1].split('</span>', 1)[0]

    def _rendered(self):
        _login_as_aidana(self.client)
        return self.client.get(reverse('core:notifications')).content.decode()

    def test_contest_wears_the_trophy(self):
        self.assertIn('icon-trophy', self._rendered())
        self.assertNotIn('bookmark', self._chip(),
                         'залитая закладка по DEC-09b значит «сохранено»')

    def test_moderation_wears_the_shield(self):
        self.assertIn('icon-shield', self._rendered())
        self.assertNotIn('name="check"', self._chip(),
                         'галка утверждает «одобрено» независимо от исхода')

    def test_like_does_not_borrow_the_error_token(self):
        like = self._chip().split("n.kind == 'like'", 1)[1].split('{% elif', 1)[0]
        self.assertNotIn('status-error', like,
                         'красный на лайке — это «ошибка», а не «сердце»')

    def test_every_kind_still_has_an_icon(self):
        """Правка иконок не должна оставить тип без глифа."""
        chip = self._chip()
        for kind in stub_data.NOTIF_KINDS:
            with self.subTest(kind=kind):
                self.assertIn(f"n.kind == '{kind}'", chip)


class UnreadIsVisibleAndAnnounced(TestCase):
    """Непрочитанное отличимо и глазами, и на слух.

    Оба признака были сломаны одновременно, и страница выглядела рабочей.
    Фон задавался двумя классами на одном элементе — `bg-white` и
    `bg-slate-50/60`; побеждает та утилита, что стоит позже в собранном
    CSS, а `.bg-white` идёт после. Подсветка не появлялась никогда.
    Точка же несла `aria-label` на `<span>` без роли — атрибут, который
    скринридер игнорирует. Для незрячего непрочитанных не существовало.
    """

    ITEM = TEMPLATES / 'components' / 'notification_item.html'

    def test_background_is_exclusive_not_layered(self):
        body = self.ITEM.read_text(encoding='utf-8')
        opening = body.split('<article', 1)[1].split('>', 1)[0]
        self.assertNotIn(
            'bg-white', opening.split('{% if n.read %}')[0],
            'фон непрочитанного перекрывается безусловным bg-white: две '
            'bg-утилиты на одном элементе разрешает не порядок в class, '
            'а порядок в собранном CSS',
        )
        self.assertIn('{% if n.read %}bg-white{% else %}', opening)

    def test_unread_dot_is_announced_by_text(self):
        _login_as_aidana(self.client)
        html = self.client.get(reverse('core:notifications')).content.decode()
        self.assertIn('<span class="sr-only">оқылмаған</span>', html)
        self.assertNotIn('aria-label="оқылмаған"', html)

    def test_read_notification_carries_no_marker(self):
        """Отметка стоит только у непрочитанного — иначе она ничего не значит."""
        unread = stub_data.unread_count_for_user('aidana')
        _login_as_aidana(self.client)
        html = self.client.get(reverse('core:notifications')).content.decode()
        self.assertEqual(html.count('<span class="sr-only">оқылмаған</span>'), unread)


class NotificationsReachableWithoutDesktopHeader(TestCase):
    """Раздел открывается с телефона (FR-NOTIF-02).

    Единственная ссылка на уведомления лежала внутри `hidden … md:flex` —
    десктопного кластера шапки. В mobile bottom nav уведомлений нет
    намеренно (07 §7.6), профиль на них не ссылается, и на телефоне
    раздел не открывался ниоткуда: страница существовала, входа не было.

    Проверка идёт обходом DOM, а не поиском подстроки: важно не то, что
    ссылка есть в разметке, а то, что она лежит вне поддерева, скрытого
    до `md`. Конкретная вёрстка мобильного кластера при этом не
    закрепляется — тест утверждает достижимость, а не расположение.
    """

    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
            'link', 'meta', 'source', 'track', 'wbr'}

    # `hidden` + возврат к display на брейкпоинте = «только с этой ширины».
    DESKTOP_ONLY = re.compile(r'\bhidden\b')
    SHOWN_AT = re.compile(r'\b(sm|md|lg|xl|2xl):(flex|block|grid|inline-flex|inline-block|table)\b')

    class _Scan(HTMLParser):
        def __init__(self, void, is_desktop_only, href):
            super().__init__(convert_charrefs=True)
            self.void = void
            self.is_desktop_only = is_desktop_only
            self.href = href
            self.stack = []        # [(tag, скрыт ли до брейкпоинта)]
            self.reachable = False

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            hidden = self.is_desktop_only(attrs.get('class') or '')
            buried = hidden or any(h for _, h in self.stack)
            if tag == 'a' and attrs.get('href') == self.href and not buried:
                self.reachable = True
            if tag not in self.void:
                self.stack.append((tag, buried))

        def handle_endtag(self, tag):
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    return

    def _desktop_only(self, cls):
        return bool(self.DESKTOP_ONLY.search(cls) and self.SHOWN_AT.search(cls))

    def _reachable_on(self, url):
        parser = self._Scan(self.VOID, self._desktop_only,
                            reverse('core:notifications'))
        parser.feed(self.client.get(url).content.decode())
        return parser.reachable

    def test_link_survives_outside_the_desktop_cluster(self):
        _login_as_aidana(self.client)
        for name in ('core:home', 'core:library', 'core:profile_me'):
            with self.subTest(page=name):
                self.assertTrue(
                    self._reachable_on(reverse(name)),
                    'ссылка на уведомления лежит только внутри поддерева, '
                    'скрытого до брейкпоинта: на телефоне раздел не открыть',
                )

    def test_the_guard_actually_sees_the_desktop_cluster(self):
        """Страховка от теста, который проходит по недосмотру.

        Если бы `_desktop_only` не срабатывал ни на чём, предыдущий тест
        был бы зелёным при любой вёрстке.
        """
        self.assertTrue(self._desktop_only('ml-auto hidden items-center gap-6 md:flex'))
        self.assertFalse(self._desktop_only('ml-auto -mr-2 flex items-center md:hidden'))

    def test_guest_gets_no_bell(self):
        """Гостю считать нечего — колокольчик без сессии не рендерится."""
        self.assertFalse(self._reachable_on(reverse('core:home')))


# ════════════════════════════ Header / nav badges ═════════════════════════

class HeaderUnreadBadge(TestCase):

    def test_authed_aidana_sees_unread_badge(self):
        _login_as_aidana(self.client)
        r = self.client.get(reverse('core:home'))
        # Бейдж непрочитанных — из stub_data.unread_count_for_user
        self.assertContains(r, 'оқылмаған')

    def test_authed_no_notifs_no_badge_number(self):
        _login_as(self.client, 'no_notifs_user')
        r = self.client.get(reverse('core:home'))
        # У этого юзера 0 — текст «оқылмаған» в aria-label не должен появиться
        self.assertNotContains(r, 'оқылмаған')

    def test_guest_no_bell_at_all(self):
        r = self.client.get(reverse('core:home'))
        self.assertNotContains(r, 'Хабарламалар (')


class ContestAwardsInProfile(TestCase):
    """DEC-46: награды конкурсов стоят тем же рядом, что и системные знаки."""

    def test_helper_returns_awards_for_a_winner(self):
        awards = stub_data.contest_awards_of('bekzhan_t')
        self.assertEqual([a['title'] for a in awards], ['Бас жүлде'])
        self.assertEqual(awards[0]['year'], 2023)

    def test_helper_is_empty_for_an_author_without_awards(self):
        self.assertEqual(stub_data.contest_awards_of('aidana'), [])
        self.assertEqual(stub_data.contest_awards_of('ghost'), [])

    def test_shape_is_complete(self):
        for a in stub_data.AUTHORS:
            for item in stub_data.contest_awards_of(a.username):
                with self.subTest(author=a.username, key=item['key']):
                    self.assertEqual(
                        set(item),
                        {'key', 'title', 'image', 'contest', 'story', 'year', 'note'})
                    self.assertTrue(item['title'])

    def test_row_renders_the_emblem(self):
        r = self.client.get(reverse('core:profile_other',
                                    kwargs={'username': 'bekzhan_t'}))
        award = stub_data.contest_awards_of('bekzhan_t')[0]
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
        for a in stub_data.AUTHORS:
            for item in stub_data.contest_awards_of(a.username):
                with self.subTest(author=a.username, key=item['key']):
                    self.assertTrue(item['title'])
                    if item['story'] is not None:
                        self.assertTrue(item['story'].is_public)

    def test_author_without_contest_awards_shows_no_medallion(self):
        """Системные знаки у неё есть, конкурсных нет — и медальона тоже."""
        self.assertFalse(stub_data.contest_awards_of('aidana'))
        r = self.client.get(reverse('core:profile_other',
                                    kwargs={'username': 'aidana'}))
        self.assertNotContains(r, '/media/awards/')
