"""PROF · LIB · NOTIF — три раздела вошедшего.

Один вопрос проходит через все три и проверяется здесь чаще прочего —
**кто зритель** (BR-73): посторонний видит только публичное, и однажды эти
две выдачи уже склеили — на `/u/<username>/` висели черновик и работа на
модерации.

Два правила ленты живут в конце файла: **хранится момент, выводится
подпись** (BR-70a) и **уведомление ведёт к своему предмету и не
переписывает его имя** (BR-72a).
"""

import re
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import data
from core.domain.contests import timing_line
from core.models import Follow, Notification, Story, User
from core.templatetags.balaproza import outcome_label
from core.tests.base import TestCase, login_as, login_as_newcomer, user

TEMPLATES = Path(__file__).resolve().parents[2] / 'templates'
NOTIFICATION_ITEM = TEMPLATES / 'components' / 'notification_item.html'


def _aidana_notifications():
    """Лента демо-автора из базы — то же, что видит страница."""
    return list(Notification.objects.filter(user__username='aidana')
                .order_by('-created_at'))


def _notification(username='ghost', **fields):
    """Уведомление для проверки ветки, которой нет в демо-ленте.

    Создаётся в базе, а не подменяется в модуле: транзакция теста откатит
    его, и следующий тест увидит корпус нетронутым.
    """
    days = fields.pop('days_ago', 0)
    user, _ = User.objects.get_or_create(username=username)
    return Notification.objects.create(
        user=user, created_at=timezone.now() - timedelta(days=days), **fields)


def _titles(entries):
    return {e.story.slug: e.story.title for e in entries}


# ───────────────────────────────────────────────────────────────────────
# Профиль: что видно и кому
# ───────────────────────────────────────────────────────────────────────

class PublicSurfaceOfAnAuthor(TestCase):
    """Числа и списки, которые видит посторонний, — только публичные."""

    def test_public_numbers_count_only_public_work(self):
        # Одно правило публичности, посчитанное один раз: если works и
        # `Author.works` разойдутся, профиль и карточка автора на STORY
        # снова будут врать друг про друга (у aidana было 5 против 3).
        for author in data.all_authors():
            public = data.public_stories_of(author)
            stats = data.public_stats(author)
            with self.subTest(author=author.username):
                self.assertEqual(stats['works'], author.works)
                self.assertEqual(stats['reads'], sum(s.views for s in public))
                self.assertEqual(stats['likes'], sum(s.likes for s in public))
                self.assertTrue(all(s.is_public for s in public))

    def test_hidden_work_reaches_neither_the_count_nor_the_rail(self):
        hidden = [s for s in data.my_stories_of(user('aidana')) if not s.is_public]
        self.assertTrue(hidden, 'фикстура сломана: у aidana нет непубличных работ')
        self.assertEqual(
            data.public_stats(user('aidana'))['works'],
            len(data.my_stories_of(user('aidana'))) - len(hidden),
        )
        # Рейл — публичная поверхность, и BR-73 действует в нём так же.
        top = data.top_stories_of(user('aidana'), limit=99)
        self.assertTrue(all(s.is_public for s in top))
        for story in hidden:
            with self.subTest(story=story.slug):
                self.assertNotIn(story.slug, {s.slug for s in top})

    def test_public_list_keeps_serials(self):
        # DEC-37: публичный сериал носит OnProcess/Completed. Фильтр по
        # литералу 'Published' молча выкинул бы их все.
        public = data.public_stories_of(user('rudazov'))
        self.assertEqual(len(public), 3)
        self.assertIn('arhimag', {s.slug for s in public})   # OnProcess

    def test_own_stats_add_the_private_half(self):
        stats = data.reader_stats(user('aidana'))
        # Публичные числа те же, что у постороннего: свой профиль не
        # показывает владельцу другую арифметику, чем читателю.
        self.assertEqual(stats['works'], data.public_stats(user('aidana'))['works'])
        self.assertEqual(stats['works_total'], len(data.my_stories_of(user('aidana'))))
        self.assertGreater(stats['works_total'], stats['works'])
        self.assertEqual(stats['finished'], 1)
        self.assertEqual(stats['followers'],
                         User.objects.get(username='aidana').followers)

    def test_the_rail_top_is_sorted_and_capped(self):
        top = data.top_stories_of(user('aygerim_k'))
        self.assertEqual([s.views for s in top],
                         sorted((s.views for s in top), reverse=True))
        self.assertLessEqual(len(top), 3)
        self.assertEqual(len(data.top_stories_of(user('aygerim_k'), limit=1)), 1)

    def test_unknown_user_is_empty_everywhere(self):
        stats = data.public_stats(user('no-such-user'))
        self.assertEqual([stats['works'], stats['reads'],
                          stats['likes'], stats['followers']], [0, 0, 0, 0])
        reader = data.reader_stats(user('no-such-user'))
        self.assertEqual([reader['works'], reader['works_total'],
                          reader['finished'], reader['followers']], [0, 0, 0, 0])
        self.assertEqual(list(data.public_stories_of(user('no-such-user'))), [])
        self.assertEqual(list(data.top_stories_of(user('no-such-user'))), [])
        self.assertEqual(list(data.following_of(user('no-such-user'))), [])
        self.assertEqual(list(data.followers_of(user('no-such-user'))), [])


class FollowGraphHelpers(TestCase):

    def test_the_graph_answers_both_directions(self):
        self.assertTrue(data.is_following(user('aidana'), user('rudazov')))
        self.assertFalse(data.is_following(user('aidana'), user('bekzhan_t')))
        self.assertEqual({a.username for a in data.following_of(user('aidana'))},
                         {'rudazov', 'sayyn', 'dina_books'})
        followers = data.followers_of(user('aidana'))
        self.assertEqual([a.username for a in followers], ['aygerim_k'])

    def test_every_link_is_visible_from_both_ends(self):
        """Подписка — одна строка, и обе выдачи обязаны её называть."""
        for author in data.all_authors():
            for other in data.following_of(author):
                with self.subTest(who=author.username, whom=other.username):
                    self.assertIn(
                        author.username,
                        {a.username for a in data.followers_of(other)})


class OwnProfile(TestCase):
    """`/me/` — четыре вкладки, приватная половина только владельцу."""

    def test_guest_gets_a_gate_without_data_and_without_an_empty_rail(self):
        # Рейл профиля состоит из одного блока «Жазылулар»; у гостя
        # `profile_user` пуст, и от рейла оставалась пустая колонка в
        # 300px, сдвигавшая гейт от центра.
        response = self.client.get(reverse('core:profile_me'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'кір')
        self.assertNotContains(response, 'Айдана Серікқызы')
        self.assertFalse(response.context['has_right_rail'])
        self.assertNotContains(response, 'w-[300px]')

    def test_it_opens_on_works_with_four_segments(self):
        login_as(self.client)
        response = self.client.get(reverse('core:profile_me'))
        self.assertContains(response, 'aidana')
        self.assertContains(response, '@aidana')
        # DEC-44: вкладка показывает публичные работы — то же, что видит
        # читатель. Черновик и работа на модерации сюда не попадают.
        for story in data.public_stories_of(user('aidana')):
            with self.subTest(story=story.slug):
                self.assertContains(response, story.title)
        # Список сегментов ведём из самого источника: добавленный в
        # `_PROF_TABS_ME` и забытый в шаблоне остался бы незамеченным.
        for slug in ('works', 'library', 'stats', 'about'):
            with self.subTest(tab=slug):
                self.assertContains(response, f'?tab={slug}')
        self.assertEqual(len(response.context['prof_items']), 4)
        # 4 числа из reader_stats. «Оқылды» значило то просмотры, то
        # «дочитано»; «Жазылулар» в плитке значило подписчиков, а в
        # заголовке рейла — подписки: одно слово на два смысла.
        for word in ('Шығарма', 'Реакциялар', 'Оқылым', 'Жазылушы'):
            with self.subTest(tile=word):
                self.assertContains(response, word)

    def test_the_active_segment_is_marked_once_for_screen_readers(self):
        # `role="tab"` убран (обещал панель, которой нет) — состояние несёт
        # aria-current, и оно обязано быть ровно одно.
        login_as(self.client)
        html = self.client.get(
            reverse('core:profile_me') + '?tab=about').content.decode()
        self.assertEqual(html.count('aria-current="page"'), 1)
        self.assertNotIn('aria-selected', html)

    def test_library_and_about_tabs_show_their_own_half(self):
        login_as(self.client)
        library = self.client.get(reverse('core:profile_me') + '?tab=library')
        self.assertContains(library, 'Оқу үстіндегі')
        self.assertContains(library, 'Сақталған')
        for entry in data.library_of(user('aidana'), 'reading'):
            with self.subTest(story=entry.story.slug):
                self.assertContains(library, entry.story.title)

        about = self.client.get(reverse('core:profile_me') + '?tab=about')
        self.assertContains(about, 'Жас прозаик')
        # Списка работ здесь нет. «Таң алдында» проверять нельзя: она
        # подана на конкурс и законно стоит в конкурсной истории.
        self.assertNotContains(about, 'Көше әндері')
        self.assertNotContains(about, 'my_story_row')
        # Приватный блок — только владельцу
        self.assertContains(about, 'Тек саған көрінеді')
        self.assertContains(about, 'Айдана Серікқызы')      # ресми аты-жөні
        self.assertContains(about, '2025 жылдан бері')      # joined_year
        self.assertContains(about, len(data.my_stories_of(user('aidana'))))
        self.assertContains(about, 'жобалармен бірге')

    def test_an_unknown_tab_falls_back_to_works(self):
        login_as(self.client)
        response = self.client.get(reverse('core:profile_me') + '?tab=garbage')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Таң алдында')


class StrangerProfile(TestCase):
    """`/u/<username>/` — публичный вид, без приватных полей и вкладок."""

    def test_it_lists_the_public_work_and_counts_it_honestly(self):
        response = self.client.get(
            reverse('core:profile_other', kwargs={'username': 'rudazov'}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Rudazov')
        for story in data.public_stories_of(user('rudazov')):
            with self.subTest(story=story.slug):
                self.assertContains(response, story.title)
        # Сегмент обещал «Шығармалар 5» и открывал список из трёх.
        item = next(i for i in response.context['prof_items']
                    if i['slug'] == 'works')
        self.assertEqual(item['count'], len(response.context['works']))

    def test_drafts_and_moderation_stay_hidden(self):
        """BR-10 / DEC-23: профиль строился на `my_stories_of` — выдаче
        кабинета, — и на `/u/aidana/` черновик с работой на модерации
        висели обычными кликабельными карточками."""
        response = self.client.get(
            reverse('core:profile_other', kwargs={'username': 'aidana'}))
        hidden = [s for s in data.my_stories_of(user('aidana')) if not s.is_public]
        self.assertTrue(hidden, 'фикстура сломана: у aidana нет непубличных работ')
        for story in hidden:
            with self.subTest(story=story.slug):
                self.assertNotContains(response, story.title)
                self.assertNotContains(response, f'/story/{story.slug}/')

    def test_the_follow_button_matches_the_viewer(self):
        url = reverse('core:profile_other', kwargs={'username': 'rudazov'})
        toggle = reverse('core:follow_toggle', kwargs={'username': 'rudazov'})

        guest = self.client.get(url)
        self.assertContains(guest, 'Жазылу')
        self.assertContains(guest, '/auth/login/')

        login_as(self.client, 'bekzhan_t')      # подписан
        subscribed = self.client.get(url)
        self.assertContains(subscribed, 'Жазылдың')
        self.assertContains(subscribed, toggle)

        login_as(self.client, 'sayyn')          # не подписан
        stranger = self.client.get(url)
        self.assertContains(stranger, 'Жазылу')
        self.assertNotContains(stranger, 'Жазылудан бас тарттың')

    def test_about_hides_the_private_fields(self):
        """Настоящее имя автора — не публичный факт.

        В своей копии вкладки лежал `profile_user.name` без всякой пометки,
        а шапку между двумя шаблонами уже копировали: следующее
        копирование унесло бы имя-фамилию в публичный профиль.
        """
        response = self.client.get(
            reverse('core:profile_other', kwargs={'username': 'rudazov'})
            + '?tab=about')
        self.assertContains(response, 'Фэнтези, шытырман')
        self.assertContains(response, 'жылдан бері')
        self.assertNotContains(response, 'Тек саған көрінеді')
        self.assertNotContains(response,
                               User.objects.get(username='rudazov').name)
        self.assertNotContains(response, 'жобалармен бірге')

    def test_private_sections_have_no_entrance_and_a_ghost_is_404(self):
        response = self.client.get(
            reverse('core:profile_other', kwargs={'username': 'rudazov'}))
        self.assertNotContains(response, '?tab=library')
        self.assertNotContains(response, '?tab=stats')
        # Заглушка с кодом 200 позволяла проиндексировать любой @username.
        self.assertEqual(self.client.get(reverse(
            'core:profile_other', kwargs={'username': 'ghost'})).status_code, 404)


class ProfileIsNotASecondCabinet(TestCase):
    """DEC-44: профиль — публичный вид на автора, кабинет — рабочее место.

    `/me/?tab=works` рендерил `my_stories_of` строками `my_story_row`, то
    есть ровно список из `/my-stories/` минус полоса внимания. Две
    страницы с одним содержимым, и ни одна не отвечала, зачем она.
    """

    def setUp(self):
        super().setUp()
        login_as(self.client)
        self.response = self.client.get(reverse('core:profile_me'))

    def test_the_owner_sees_exactly_what_a_reader_sees(self):
        self.assertEqual(
            [s.slug for s in self.response.context['works']],
            [s.slug for s in data.public_stories_of(user('aidana'))],
        )
        for slug in ('aidana-kus', 'aidana-erteg'):
            with self.subTest(story=slug):
                self.assertNotContains(self.response,
                                       data.story_by_slug(slug).title)
        # `my_story_row` — строка кабинета: статус, «когда трогали», меню.
        self.assertNotContains(self.response, 'Сайтта қарау')

    def test_the_hidden_ones_are_counted_and_linked(self):
        # Молча спрятать работы нельзя: автор должен видеть, что их не
        # потеряли, и знать, где они лежат.
        self.assertEqual(self.response.context['hidden_n'], 2)
        self.assertContains(self.response, reverse('core:my_stories'))
        # Разбивка не потеряна — она во вкладке «Статистика» (FR-PROF-08).
        stats = self.client.get(reverse('core:profile_me') + '?tab=stats')
        self.assertContains(stats, 'Тек саған көрінеді')
        self.assertEqual(stats.context['writer']['total'],
                         len(data.my_stories_of(user('aidana'))))

    def test_owner_and_stranger_count_works_the_same_way(self):
        theirs = self.client.get(reverse(
            'core:profile_other', kwargs={'username': 'aidana'})).context['prof_items']
        mine = self.response.context['prof_items']
        self.assertEqual(
            next(i['count'] for i in mine if i['slug'] == 'works'),
            next(i['count'] for i in theirs if i['slug'] == 'works'),
        )
        self.assertEqual(next(i['count'] for i in mine if i['slug'] == 'works'),
                         len(self.response.context['works']))


class ProfileRailByViewer(TestCase):
    """Рейл профиля разный по зрителю (FR-PROF-09).

    Чужой профиль показывал «Жазылулар» — на кого подписан **он**.
    Читателю это не сообщало ничего и занимало единственный блок колонки.
    """

    def test_a_stranger_gets_the_most_read_work_not_the_subscriptions(self):
        response = self.client.get(
            reverse('core:profile_other', kwargs={'username': 'aygerim_k'}))
        self.assertTrue(data.following_of(user('aygerim_k')))   # подписки есть
        self.assertNotContains(response, 'Жазылулар')     # и они не здесь
        self.assertContains(response, 'Ең көп оқылғаны')
        self.assertTrue(response.context['has_right_rail'])
        self.assertContains(response, data.top_stories_of(user('aygerim_k'))[0].title)

    def test_the_rail_stays_away_when_the_body_already_shows_everything(self):
        # Три работы: вкладка «Шығармалар» показывает их целиком, топ-3
        # рядом был бы дублем — тем же, за который убирали числа из рейла.
        url = reverse('core:profile_other', kwargs={'username': 'rudazov'})
        self.assertEqual(len(data.public_stories_of(user('rudazov'))), 3)
        self.assertFalse(self.client.get(url).context['has_right_rail'])
        # На «Туралы» работ в теле нет вовсе — там блок полезен с первой.
        self.assertTrue(self.client.get(url + '?tab=about').context['has_right_rail'])
        self.assertNotContains(self.client.get(url), 'w-[300px]')

    def test_the_owner_still_gets_the_list_of_who_he_reads(self):
        login_as(self.client)
        response = self.client.get(reverse('core:profile_me'))
        self.assertContains(response, 'Жазылулар')
        self.assertNotContains(response, 'Ең көп оқылғаны')


class PeoplePages(TestCase):
    """Подписчики и подписки открываются страницей (FR-PROF-10, BR-75)."""

    def _url(self, username, kind):
        return reverse('core:profile_people',
                       kwargs={'username': username, 'kind': kind})

    def test_both_lists_are_public_and_name_everyone(self):
        # BR-75: число подписчиков и так объявлено плиткой профиля, а
        # подписки показывал рейл. Гость получает обе страницы.
        for kind, fetch in (('followers', data.followers_of),
                            ('following', data.following_of)):
            with self.subTest(kind=kind):
                response = self.client.get(self._url('aidana', kind))
                self.assertEqual(response.status_code, 200)
                for author in fetch(user('aidana')):
                    self.assertContains(response, author.public_name)

    def test_segments_carry_real_paths_and_real_counts(self):
        response = self.client.get(self._url('aidana', 'followers'))
        self.assertContains(response, self._url('aidana', 'following'))
        self.assertNotContains(response, '?tab=following')
        counts = {it['slug']: it['count']
                  for it in response.context['people_items']}
        self.assertEqual(counts['followers'], len(data.followers_of(user('aidana'))))
        self.assertEqual(counts['following'], len(data.following_of(user('aidana'))))

    def test_a_row_leads_to_the_profile_not_to_a_decision(self):
        # Кнопка рядом с одним именем просит решение раньше, чем показано,
        # на основании чего его принимать. Строка ведёт в профиль, где она
        # стоит рядом с био, работами и знаками.
        response = self.client.get(self._url('rudazov', 'followers'))
        self.assertNotContains(response, 'Жазылдың')
        self.assertContains(response, reverse('core:profile_other',
                                              kwargs={'username': 'aidana'}))

    def test_empty_explains_itself_and_garbage_is_404(self):
        self.assertEqual(list(data.following_of(user('rudazov'))), [])
        self.assertContains(self.client.get(self._url('rudazov', 'following')),
                            'Әлі ешкімге жазылмаған')
        # Молчаливый фолбэк отдал бы подписчиков под чужим заголовком.
        self.assertEqual(self.client.get('/u/aidana/garbage/').status_code, 404)
        self.assertEqual(
            self.client.get(self._url('no-such-user', 'followers')).status_code, 404)


class ProfileStatTilesLinkToLists(TestCase):
    """Числа профиля кликабельны там, где за ними стоит список (FR-PROF-10)."""

    def test_only_the_tiles_with_a_list_behind_them_are_links(self):
        response = self.client.get(
            reverse('core:profile_other', kwargs={'username': 'rudazov'}))
        self.assertContains(response, reverse(
            'core:profile_people',
            kwargs={'username': 'rudazov', 'kind': 'followers'}))
        # «Оқылым» и «Реакциялар» — суммы, открывать в них нечего. Две
        # ссылки на четыре плитки, и ни одной лишней.
        self.assertEqual(
            response.content.decode().count('class="absolute inset-0 rounded-lg"'), 2)
        login_as(self.client)
        self.assertContains(self.client.get(reverse('core:profile_me')),
                            '/me/?tab=works')


class ProfileStatsTab(TestCase):
    """Вкладка «Статистика» — приватная и не повторяет кабинет."""

    def setUp(self):
        super().setUp()
        login_as(self.client)
        self.response = self.client.get(reverse('core:profile_me') + '?tab=stats')

    def test_it_is_marked_private_and_shows_the_private_breakdown(self):
        self.assertContains(self.response, 'Тек саған көрінеді')
        for word in ('Модерацияда', 'Жазылып жатыр', 'Оқып шыққаның'):
            with self.subTest(row=word):
                self.assertContains(self.response, word)
        # Кабинет отвечает «что делать», статистика — «как идёт».
        self.assertNotContains(self.response, 'Назарыңды күтеді')

    def test_it_shows_the_whole_ladder_and_the_awards_not_taken_yet(self):
        for _, label in data.READ_TIERS:
            with self.subTest(tier=label):
                self.assertContains(self.response, label)
        unearned = [a for a in data.award_catalog(user('aidana')) if not a['earned']]
        self.assertTrue(unearned, 'фикстура сломана: у aidana все награды взяты')
        for award in unearned:
            with self.subTest(award=award['key']):
                self.assertContains(self.response, award['hint'])

    def test_a_guest_never_reaches_the_tab(self):
        self.client.logout()
        response = self.client.get(reverse('core:profile_me') + '?tab=stats')
        self.assertNotContains(response, 'Тек саған көрінеді')
        self.assertNotContains(response, 'Оқылым сатылары')

    def test_an_author_without_a_single_award_still_gets_the_grid(self):
        # Спрятанная награда не отвечает на вопрос «что дальше».
        login_as_newcomer(self.client, 'lonely_writer')
        self.assertEqual(
            self.client.get(reverse('core:profile_me') + '?tab=stats').status_code,
            200)


class ProfileTemplatesShareParts(TestCase):
    """Свой и чужой профиль обязаны рендерить одни и те же партиалы.

    Шапка, четыре числа и «Туралы» были скопированы в оба шаблона — около
    шестидесяти строк, — и копии уже разъехались: в одной вкладке
    «Туралы» четыре поля, в другой только био. Тест ловит именно повторное
    заинлайнивание: поведенческие проверки такого не видят, пока копии
    случайно совпадают.
    """

    PAGES = ('pages/profile/profile_me.html', 'pages/profile/profile_other.html')
    PARTS = ('_header.html', '_achievements.html', '_stats.html', '_about.html')

    def test_both_pages_include_the_shared_partials_and_reinline_nothing(self):
        for page in self.PAGES:
            body = (TEMPLATES / page).read_text(encoding='utf-8')
            for part in self.PARTS:
                with self.subTest(page=page, part=part):
                    self.assertIn(f'partials/profile/{part}', body)
            with self.subTest(page=page):
                # Разметка чисел и шапки живёт только в партиалах.
                self.assertNotIn('Оқылым', body)
                self.assertNotIn('<header', body)


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

    def test_the_facts_line_names_the_year_and_the_contests(self):
        response = self.client.get(
            reverse('core:profile_other', kwargs={'username': 'aidana'}))
        self.assertContains(response, '2025 жылдан бері')
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
        self.assertContains(response, '2024 жылдан бері')
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


# ───────────────────────────────────────────────────────────────────────
# Запись: подписка и правка профиля
# ───────────────────────────────────────────────────────────────────────

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

    def test_the_button_toggles_and_the_counter_follows_the_rows(self):
        """`User.followers` — колонка, и разъехаться с записями она не
        должна ни на одном шаге: пересчёт идёт по строкам."""
        login_as(self.client, 'sayyn')       # ещё не подписан
        before = self._links()
        self.client.post(self._url())
        self.assertEqual(self._links(), before + 1)
        self.assertEqual(self._stored(), before + 1)
        for _ in range(3):
            self.client.post(self._url())
            self.assertEqual(self._stored(), self._links())

        login_as(self.client, 'bekzhan_t')   # уже подписан
        before = self._links()
        self.client.post(self._url())
        self.assertEqual(self._links(), before - 1)
        self.assertEqual(self._stored(), before - 1)

    def test_nobody_writes_what_they_may_not_write(self):
        before = self._links()
        # Гость
        self.client.post(self._url())
        self.assertEqual(self._links(), before)
        # Сам на себя
        login_as(self.client, self.TARGET)
        self.client.post(self._url())
        self.assertEqual(self._links(), before)
        # GET
        login_as(self.client, 'sayyn')
        self.client.get(self._url())
        self.assertEqual(self._links(), before)
        # Несуществующий автор
        total = Follow.objects.count()
        self.client.post(self._url('no-such-user'))
        self.assertEqual(Follow.objects.count(), total)

    def test_it_comes_back_where_it_was_pressed_and_not_off_the_site(self):
        """Кнопок две и стоят они на разных страницах."""
        login_as(self.client, 'sayyn')
        story_page = reverse('core:story_detail', kwargs={'slug': 'kronchessii'})
        self.assertRedirects(self.client.post(self._url(), {'next': story_page}),
                             story_page)
        self.assertRedirects(
            self.client.post(self._url(), {'next': '//evil.example/'}),
            reverse('core:profile_other', kwargs={'username': self.TARGET}))


class ProfileEdit(TestCase):
    """Ф15, Этап 6: `/me/edit/` — настоящий POST, ошибка поля = no-op."""

    FIELDS = {'pen_name': 'Аты', 'name': 'Есім',
              'bio': '', 'gender': '', 'age': ''}

    def setUp(self):
        super().setUp()
        login_as(self.client)

    def _post(self, client=None, **overrides):
        payload = dict(self.FIELDS)
        payload.update(overrides)
        return (client or self.client).post(
            reverse('core:profile_me_edit'), payload)

    def _aidana(self):
        return User.objects.get(username='aidana')

    def test_it_saves_every_field_and_returns_to_the_profile(self):
        response = self._post(pen_name='Жаңа лақап', name='Жаңа есім',
                              bio='Жаңа био.', gender='girl', age='16')
        self.assertRedirects(response, reverse('core:profile_me'))
        user = self._aidana()
        self.assertEqual(
            [user.pen_name, user.name, user.bio, user.gender, user.age],
            ['Жаңа лақап', 'Жаңа есім', 'Жаңа био.', 'girl', 16])

    def test_the_optional_half_may_be_left_blank(self):
        self._post(bio='Бар.', gender='girl', age='16')
        self._post(bio='', gender='', age='')
        user = self._aidana()
        self.assertIsNone(user.age)
        self.assertEqual(user.gender, '')
        self.assertEqual(user.bio, '')

    def test_a_bad_field_saves_nothing_and_returns_to_the_form(self):
        cases = {
            'pen_name': ('', 'ә' * 61),
            'name': ('',),
            'bio': ('ә' * 201,),
            'gender': ('alien',),
            'age': ('abc', '999'),
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value[:12]):
                    before = getattr(self._aidana(), field)
                    self._post(**{field: value})
                    self.assertEqual(getattr(self._aidana(), field), before)
        self.assertRedirects(self._post(pen_name=''),
                             reverse('core:profile_me_edit'))

    def test_the_avatar_takes_raster_only_and_a_refusal_blocks_the_form(self):
        """Тот же валидатор, что у Story.cover (BR-46) — SVG не проходит."""
        self._post(avatar=SimpleUploadedFile('фото.png', b'\x89PNG demo',
                                             content_type='image/png'))
        user = self._aidana()
        self.assertTrue(user.avatar.name.startswith('avatars/aidana'))
        self.assertTrue(user.avatar.name.endswith('.png'))

        user.avatar = ''
        user.save(update_fields=['avatar'])
        before = self._aidana().pen_name
        # Ошибка одного поля — весь POST no-op, не частичное сохранение.
        self._post(pen_name='Басқа аты',
                   avatar=SimpleUploadedFile('фото.svg', b'<svg/>',
                                             content_type='image/svg+xml'))
        self.assertFalse(self._aidana().avatar)
        self.assertEqual(self._aidana().pen_name, before)

    def test_a_guest_writes_nothing(self):
        before = self._aidana().pen_name
        self._post(Client(), pen_name='Бөгде', name='Бөгде')
        self.assertEqual(self._aidana().pen_name, before)

    def test_the_form_prefills_the_raw_pen_name(self):
        """`value=` показывал `public_name` (pen_name or '@username'), не
        сырое поле: пустой pen_name отрисовался бы как «@username», и
        несохранённая форма сохранила бы это буквально при первом POST."""
        user = User.objects.create_user(username='blankpen', password='x')
        self.assertEqual(user.pen_name, '')
        self.client.force_login(user)
        html = self.client.get(reverse('core:profile_me_edit')).content.decode()
        self.assertNotIn('value="@blankpen"', html)


# ───────────────────────────────────────────────────────────────────────
# LIB — библиотека читателя: три непересекающиеся полки (BR-60/61)
# ───────────────────────────────────────────────────────────────────────

class LibraryShelves(TestCase):

    KINDS = ('saved', 'reading', 'done')

    def test_the_shelves_partition_the_library(self):
        everything = data.library_of(user('aidana'))
        by_kind = {k: data.library_of(user('aidana'), k) for k in self.KINDS}
        self.assertEqual(sum(len(v) for v in by_kind.values()), len(everything))
        slugs = [e.story.slug for shelf in by_kind.values() for e in shelf]
        self.assertEqual(len(slugs), len(set(slugs)), 'работа лежит на двух полках')
        self.assertTrue(all(by_kind.values()), 'у aidana пустая полка')
        self.assertEqual(data.library_of(user('no-such-user')), [])
        for entry in by_kind['reading']:
            with self.subTest(entry=entry.story.slug):
                self.assertGreaterEqual(entry.progress_chapter, 1)
                self.assertLessEqual(entry.progress_chapter, entry.story.chapters)

    def test_a_guest_sees_a_gate_instead_of_someone_elses_shelf(self):
        response = self.client.get(reverse('core:library'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'кір')
        for entry in data.library_of(user('aidana')):
            with self.subTest(story=entry.story.slug):
                self.assertNotContains(response, entry.story.title)

    def test_each_tab_shows_its_own_shelf_and_nothing_else(self):
        login_as(self.client)
        everything = _titles(data.library_of(user('aidana')))
        for kind, cta in (('saved', None), ('reading', 'Жалғастыру'),
                          ('done', 'Қайта оқу')):
            shelf = data.library_of(user('aidana'), kind)
            response = self.client.get(reverse('core:library') + f'?tab={kind}')
            with self.subTest(tab=kind):
                self.assertContains(response, f'?tab={kind}')
                if cta:
                    self.assertContains(response, cta)
                mine = {e.story.slug for e in shelf}
                for entry in shelf:
                    self.assertContains(response, entry.story.title)
                for slug, title in everything.items():
                    if slug not in mine:
                        self.assertNotContains(response, title)
        # Прогресс «N / M бөлім» считается, а не хранится (DEC-52).
        reading = self.client.get(reverse('core:library') + '?tab=reading')
        for entry in data.library_of(user('aidana'), 'reading'):
            with self.subTest(story=entry.story.slug):
                self.assertContains(
                    reading,
                    f'{entry.progress_chapter} / {entry.story.chapters} бөлім')

    def test_an_unknown_tab_falls_back_to_saved(self):
        login_as(self.client)
        response = self.client.get(reverse('core:library') + '?tab=garbage')
        self.assertEqual(response.status_code, 200)
        for entry in data.library_of(user('aidana'), 'saved'):
            with self.subTest(story=entry.story.slug):
                self.assertContains(response, entry.story.title)

    def test_every_empty_shelf_explains_itself(self):
        login_as_newcomer(self.client, 'lonely_reader')
        for kind, words in (('saved', 'Сақталғандар жоқ'),
                            ('reading', 'Оқу үстіндегі шығарма жоқ'),
                            ('done', 'Әлі ешнәрсе оқылмаған')):
            with self.subTest(tab=kind):
                response = self.client.get(
                    reverse('core:library') + f'?tab={kind}')
                self.assertContains(response, words)
        self.assertContains(self.client.get(reverse('core:library')),
                            reverse('core:catalog'))


# ───────────────────────────────────────────────────────────────────────
# NOTIF — лента событий автора и бейдж непрочитанного
# ───────────────────────────────────────────────────────────────────────

class NotificationFeed(TestCase):

    def setUp(self):
        super().setUp()
        login_as(self.client)
        self.response = self.client.get(reverse('core:notifications'))

    def test_the_buckets_come_from_the_registry_and_match_the_data(self):
        grouped = data.notifications_for_user(user('aidana'))
        items = _aidana_notifications()
        for bucket in data.NOTIF_BUCKETS:
            with self.subTest(bucket=bucket):
                self.assertEqual(len(grouped[bucket]),
                                 sum(1 for n in items if n.bucket == bucket))
                self.assertTrue(grouped[bucket],
                                'у aidana должен быть непустым каждый бакет')
        for bucket in data.notifications_for_user(user('no-such-user')).values():
            self.assertEqual(bucket, [])
        # Секции строит реестр, а не три копии блока.
        keys = [s['key'] for s in self.response.context['sections']]
        self.assertEqual(keys, sorted(keys, key=data.NOTIF_BUCKETS.index))
        for section in self.response.context['sections']:
            with self.subTest(section=section['key']):
                self.assertEqual(section['label'],
                                 data.NOTIF_BUCKET_LABELS[section['key']])
        # `<ul>/<li>`: иначе скринридер не назовёт число событий в группе.
        self.assertContains(self.response, '<ul class="flex flex-col gap-3">')

    def test_an_empty_bucket_renders_no_heading(self):
        grouped = data.notifications_for_user(user('aidana'))
        lonely = {b: (items if b == 'today' else [])
                  for b, items in grouped.items()}
        # Патчится фасад: view ходит через `core.data`.
        with mock.patch.object(data, 'notifications_for_user',
                               return_value=lonely):
            response = self.client.get(reverse('core:notifications'))
        self.assertEqual([s['key'] for s in response.context['sections']],
                         ['today'])
        self.assertNotContains(response, data.NOTIF_BUCKET_LABELS['yesterday'])

    def test_every_kind_gets_its_own_words(self):
        for bucket in ('Бүгін', 'Кеше', 'Өткен аптада'):
            with self.subTest(bucket=bucket):
                self.assertContains(self.response, bucket)
        # `like` больше не говорит «ұнатты»: DEC-32 заменил одиночный лайк
        # главы пятью реакциями. Модерация называет исход, а не раздел.
        for words in ('пікір қалдырды', 'реакция қалдырды', 'саған жазылды',
                      'жаңа бөлім', 'Модерацияда', 'Байқау'):
            with self.subTest(words=words):
                self.assertContains(self.response, words)
        for notification in _aidana_notifications():
            with self.subTest(kind=notification.kind):
                self.assertIn(notification.kind, data.NOTIF_KINDS)
        self.assertContains(self.response, reverse(
            'core:profile_other', kwargs={'username': 'aygerim_k'}))

    def test_the_summary_counts_the_unread_and_offers_the_button(self):
        items = _aidana_notifications()
        unread = sum(1 for n in items if not n.read and n.bucket)
        self.assertGreater(unread, 0)
        self.assertEqual(data.unread_count_for_user(user('aidana')), unread)
        self.assertEqual(data.unread_count_for_user(user('ghost')), 0)
        self.assertContains(self.response, f'{unread} оқылмаған')
        self.assertContains(self.response, 'Барлығын оқылды деп белгілеу')

    def test_a_guest_gets_a_gate_and_a_newcomer_gets_an_empty_state(self):
        self.client.logout()
        gate = self.client.get(reverse('core:notifications'))
        self.assertEqual(gate.status_code, 200)
        self.assertContains(gate, 'кір')

        login_as_newcomer(self.client, 'lonely_user')
        empty = self.client.get(reverse('core:notifications'))
        self.assertContains(empty, 'Әзірге хабарлама жоқ')
        self.assertNotContains(empty, 'Барлығын оқылды')

    def test_the_header_says_nothing_about_data_that_is_not_on_screen(self):
        """DEC-17: шапка стояла выше ветвления по `page_state`, и в
        `?state=error` страница сообщала «жүктеу мүмкін болмады» и
        «4 оқылмаған» — с рабочей кнопкой «оқылды деп белгілеу»."""
        html = self.response.content.decode()
        self.assertIn('оқылмаған', html)
        self.assertIn('Барлығын оқылды деп белгілеу', html)
        self.assertNotIn('action="#"', html)   # без JS форма уходила в никуда
        for state in ('loading', 'error'):
            with self.subTest(state=state):
                broken = self.client.get(
                    reverse('core:notifications') + f'?state={state}'
                ).content.decode()
                self.assertNotIn('Барлығын оқылды деп белгілеу', broken)
                self.assertNotIn('оқылмаған.', broken)
                # Заголовок — часть структуры документа, а не данных.
                self.assertIn('<h1', broken)


class NotificationTimeIsDerived(TestCase):
    """Время выводится из момента, а не хранится строкой (BR-70a).

    Хранимые `when="5 күн бұрын"` и `bucket="past_week"` устаревали на
    следующий день — тот же класс ошибки, что `days_left=12` до DEC-45,
    только незаметнее: лента выглядит правдоподобной всегда.
    """

    def test_neither_the_label_nor_the_bucket_is_a_column(self):
        stored = {f.name for f in Notification._meta.get_fields()}
        for gone in ('when', 'bucket'):
            with self.subTest(field=gone):
                self.assertNotIn(gone, stored,
                                 f'`{gone}` снова стало полем — хранимое производное')

    def test_the_bucket_follows_the_calendar(self):
        for days, expected in {0: 'today', 1: 'yesterday', 2: 'past_week',
                               7: 'past_week', 8: '', 400: ''}.items():
            with self.subTest(days=days):
                self.assertEqual(
                    _notification(kind='like', days_ago=days).bucket, expected)

    def test_older_than_a_week_is_neither_shown_nor_counted(self):
        """Групп три; четвёртой «раньше» в FR-NOTIF-01 нет.

        Значит, событие старше недели в ленту не попадает — и в бейдж
        тоже, иначе шапка звала бы на страницу, где его нет.
        """
        _notification(kind='like', days_ago=30)
        grouped = data.notifications_for_user(user('ghost'))
        self.assertEqual([], [n for b in grouped.values() for n in b])
        self.assertEqual(0, data.unread_count_for_user(user('ghost')))

    def test_the_wording_of_kk_ago(self):
        self.assertEqual(data.kk_ago(0, 2), '2 сағат бұрын')
        self.assertEqual(data.kk_ago(0), 'бүгін')
        self.assertEqual(data.kk_ago(1), 'кеше')
        self.assertEqual(data.kk_ago(5), '5 күн бұрын')
        self.assertEqual(data.kk_ago(60), '2 ай бұрын')
        self.assertEqual(data.kk_ago(800), '2 жыл бұрын')
        # «26 сағат бұрын» человек переводит в дни сам — короче «кеше».
        self.assertEqual(data.kk_ago(1, 26), 'кеше')

    def test_the_freshest_comes_first_inside_a_bucket(self):
        """Порядок объявления в данных — не порядок ленты: сегодняшние
        события шли «2 сағат · 4 сағат · 9 сағат · 6 сағат»."""
        for bucket in data.notifications_for_user(user('aidana')).values():
            moments = [n.created_at for n in bucket]
            self.assertEqual(moments, sorted(moments, reverse=True))


class NotificationsLeadSomewhere(TestCase):
    """Уведомление ведёт к своему предмету (FR-NOTIF-05, BR-72a).

    Конкурсное событие знало о конкурсе только по имени внутри `text`
    и потому не вело никуда: прочитав «шорт-лист басталды», автор шёл
    искать конкурс через меню.
    """

    def setUp(self):
        super().setUp()
        login_as(self.client)
        self.response = self.client.get(reverse('core:notifications'))

    def _opens_at(self, notification):
        """Куда приводит клик по уведомлению.

        Ссылка ведёт не прямо на предмет, а через `notification_open`: по
        BR-71 метку «непрочитано» снимает именно открытие. Проверяется
        поэтому конечная точка, а не строка адреса в разметке, — заодно
        это ловит и саму таблицу соответствий `notification_href`.
        """
        url = reverse('core:notification_open', kwargs={'pk': notification.pk})
        self.assertContains(self.response, url)
        return self.client.get(url)

    def test_each_kind_lands_on_its_own_subject(self):
        contests = [n for n in _aidana_notifications() if n.kind == 'contest']
        self.assertTrue(contests, 'корпус потерял конкурсные уведомления')
        for notification in contests:
            with self.subTest(contest=notification.contest.slug):
                self.assertRedirects(
                    self._opens_at(notification),
                    reverse('core:contest_detail',
                            kwargs={'slug': notification.contest.slug}))

        moderation = [n for n in _aidana_notifications()
                      if n.kind == 'moderation' and n.story]
        self.assertTrue(moderation, 'корпус потерял уведомление о модерации')
        for notification in moderation:
            with self.subTest(story=notification.story.slug):
                # Работа на модерации не публична — вести на неё можно
                # только в авторский кабинет (BR-73).
                self.assertRedirects(
                    self._opens_at(notification),
                    reverse('core:manage_story',
                            kwargs={'slug': notification.story.slug}))

    def test_the_text_does_not_repeat_the_name_of_its_subject(self):
        """Имя предмета берётся у предмета, а не переписывается литералом.

        Второй литерал разошёлся бы с первым ровно так же, как хранимый
        `Author.works` разошёлся с числом произведений (DEC-40).
        """
        for notification in _aidana_notifications():
            if notification.kind == 'comment':
                continue  # у комментария `text` — цитата читателя, чужой UGC
            with self.subTest(kind=notification.kind):
                if notification.contest:
                    self.assertNotIn(notification.contest.name.strip('«»'),
                                     notification.text)
                if notification.story:
                    self.assertNotIn(notification.story.title, notification.text)

    def test_the_deadline_is_counted_by_the_contest(self):
        """FR-NOTIF-06: срок считает конкурс, а не текст уведомления."""
        contest = data.contest_by_slug('bolashak-mektebi')
        line = timing_line(contest.phase, contest.opens_on,
                           contest.closes_on, contest.results_on)
        self.assertTrue(line)
        self.assertContains(self.response, line)


class ModerationNotificationNamesItsOutcome(TestCase):
    """Исход модерации хранится и назван словом (BR-11).

    Поля не было вовсе: и одобрение, и отказ, и «ещё идёт» приходили
    одной строкой с зелёной галкой. Выводить исход из `Story.status`
    нельзя — статус живёт дальше события: автор правит работу и шлёт её
    снова, и вчерашний отказ начал бы говорить «Модерацияда». Тот же
    довод, по которому DEC-46 хранит `AwardGrant`.
    """

    def setUp(self):
        super().setUp()
        login_as(self.client)
        self.response = self.client.get(reverse('core:notifications'))

    def test_the_outcome_is_stored_and_labelled_by_the_registry(self):
        self.assertIn('outcome',
                      {f.name for f in Notification._meta.get_fields()})
        for outcome, label in data.MODERATION_OUTCOME_LABELS.items():
            with self.subTest(outcome=outcome or 'pending'):
                self.assertEqual(
                    outcome_label(_notification(kind='moderation', outcome=outcome)),
                    label)
        # Лучше пусто, чем чужая подпись: реестр — единственный источник.
        self.assertEqual(
            outcome_label(_notification(kind='moderation', outcome='whatever')), '')

    def test_the_outcome_belongs_to_moderation_and_agrees_with_the_story(self):
        for notification in _aidana_notifications():
            if notification.kind != 'moderation':
                with self.subTest(kind=notification.kind):
                    self.assertEqual(notification.outcome, '',
                                     'исход есть только у модерации')
                continue
            if not notification.story or notification.outcome not in (
                    'needs_work', 'rejected'):
                continue
            with self.subTest(story=notification.story.slug,
                              outcome=notification.outcome):
                # Непринятая работа не может лежать опубликованной.
                self.assertFalse(notification.story.is_public,
                                 'работа не прошла модерацию и при этом публична')

    def test_a_negative_outcome_carries_a_reason(self):
        """BR-11: автор узнаёт, что именно исправить.

        Без причины «Толықтыру қажет» сообщает ровно столько же, сколько
        «Қабылданбады», — то есть ничего, кроме факта неудачи.
        """
        negative = [n for n in _aidana_notifications()
                    if n.kind == 'moderation'
                    and n.outcome in ('needs_work', 'rejected')]
        self.assertTrue(negative, 'в корпусе нет ни одного отрицательного исхода')
        for notification in negative:
            with self.subTest(story=notification.story.slug):
                self.assertTrue(notification.text.strip(),
                                'исход без причины ничего не сообщает')
                self.assertContains(self.response, notification.text)
                self.assertContains(
                    self.response,
                    data.MODERATION_OUTCOME_LABELS[notification.outcome])

    def test_the_three_outcomes_are_distinguishable_by_word_and_colour(self):
        labels = [data.MODERATION_OUTCOME_LABELS[o]
                  for o in data.MODERATION_OUTCOMES]
        self.assertEqual(len(labels), len(set(labels)))

        chip = NOTIFICATION_ITEM.read_text(encoding='utf-8')
        # Срез обрывается на следующем `kind`: у `contest` тот же `warning`,
        # и без границы тест ловил бы соседа вместо второго исхода.
        moderation = chip.split("n.kind == 'moderation'", 1)[1].split(
            '{% elif n.kind', 1)[0]
        tokens = re.findall(r'bg-status-([a-z]+)-bg', moderation)
        self.assertEqual(len(tokens), len(set(tokens)),
                         f'два исхода носят один цвет: {tokens}')
        self.assertEqual(len(tokens), len(data.MODERATION_OUTCOMES) + 1,
                         'у какого-то исхода нет своей ветки цвета')

        # docs/ui.md: «толықтыру қажет» — приглашение, а не приговор.
        # Пока оба отрицательных исхода были одним `rejected`, возврат на
        # доработку приходил под красным `status-error` — токеном,
        # подписанным «Отказ и удаление» (DEC-39).
        branch = chip.split("n.outcome == 'needs_work'", 1)[1].split('{% el', 1)[0]
        self.assertNotIn('status-error', branch)
        self.assertIn('status-warning', branch)

    def test_a_hard_refusal_keeps_its_own_words_and_colour(self):
        """`rejected` остаётся твёрдым — иначе смягчение стало бы враньём.

        В демо-ленте его нет намеренно: свободной непубличной работы под
        него не осталось, а вешать отказ на ту же работу, которую только
        что попросили доработать, значит противоречить данным.
        """
        Notification.objects.filter(user__username='aidana').delete()
        _notification(username='aidana', kind='moderation', days_ago=2,
                      story=Story.objects.get(slug='aidana-kus'),
                      outcome='rejected', text='Ережеге қайшы келеді.')
        response = self.client.get(reverse('core:notifications'))
        self.assertContains(response, data.MODERATION_OUTCOME_LABELS['rejected'])
        self.assertNotContains(response,
                               data.MODERATION_OUTCOME_LABELS['needs_work'])
        self.assertContains(response, 'status-error')


class NotificationChipFollowsTheRegistry(TestCase):
    """Иконку выбирают по значению, а не по наличию формы (docs/ui.md).

    Конкурс носил `bookmark-filled` — глиф, который по DEC-09b означает
    активное «сохранено» и стоит на текущей главе и на кнопке «сақталды».
    Модерация носила `check`: галка утверждает «одобрено», хотя событие
    бывает отказом и ожиданием. Лайк носил пару `status-error-*` — токен,
    подписанный в `@theme` как «Отказ и удаление (DEC-39)».
    """

    def setUp(self):
        super().setUp()
        login_as(self.client)

    def _chip(self):
        """Блок выбора иконки — без окружающих комментариев.

        Сравнивать с текстом всего файла нельзя: объяснение правки само
        называет глифы, от которых она уводит.
        """
        body = NOTIFICATION_ITEM.read_text(encoding='utf-8')
        return body.split('{% endcomment %}\n    <span class="grid',
                          1)[1].split('</span>', 1)[0]

    def test_each_kind_wears_the_glyph_that_means_it(self):
        chip = self._chip()
        html = self.client.get(reverse('core:notifications')).content.decode()
        self.assertIn('icon-trophy', html)
        self.assertNotIn('bookmark', chip,
                         'залитая закладка по DEC-09b значит «сохранено»')
        self.assertIn('icon-shield', html)
        self.assertNotIn('name="check"', chip,
                         'галка утверждает «одобрено» независимо от исхода')
        for kind in data.NOTIF_KINDS:
            with self.subTest(kind=kind):
                self.assertIn(f"n.kind == '{kind}'", chip)

    def test_the_reaction_borrows_neither_the_error_token_nor_a_single_face(self):
        """`heart-filled` после DEC-32 — реакция «Жүрегім», одна из пяти.

        Совокупность в проекте уже подписана контурным `heart`: им помечен
        `Chapter.likes` в списке глав, а это сумма всех пяти.
        """
        chip = self._chip()
        # Веток у `like` две — цвет и глиф; берём каждую отдельно.
        colour = chip.split("n.kind == 'like'", 1)[1].split('{% elif', 1)[0]
        self.assertNotIn('status-error', colour,
                         'красный на лайке — это «ошибка», а не «сердце»')
        glyph = chip.split("{% elif n.kind == 'like' %}", 2)[2].split('{% elif', 1)[0]
        self.assertIn('name="heart"', glyph)
        self.assertNotIn('heart-filled', glyph)

        response = self.client.get(reverse('core:notifications'))
        self.assertContains(response, 'реакция қалдырды')
        self.assertNotContains(response, 'ұнатты')
        html = response.content.decode()
        for reaction in data.REACTIONS:
            with self.subTest(reaction=reaction.slug):
                self.assertNotIn(reaction.label, html)

    def test_unread_is_visible_and_announced(self):
        """Оба признака были сломаны одновременно, и страница выглядела
        рабочей. Фон задавался двумя классами на одном элементе —
        `bg-white` и `bg-slate-50/60`; побеждает та утилита, что стоит
        позже в собранном CSS, а `.bg-white` идёт после. Точка же несла
        `aria-label` на `<span>` без роли — атрибут, который скринридер
        игнорирует. Для незрячего непрочитанных не существовало.
        """
        body = NOTIFICATION_ITEM.read_text(encoding='utf-8')
        opening = body.split('<article', 1)[1].split('>', 1)[0]
        self.assertNotIn(
            'bg-white', opening.split('{% if n.read %}')[0],
            'фон непрочитанного перекрывается безусловным bg-white: две '
            'bg-утилиты на одном элементе разрешает не порядок в class, '
            'а порядок в собранном CSS')
        self.assertIn('{% if n.read %}bg-white{% else %}', opening)

        html = self.client.get(reverse('core:notifications')).content.decode()
        marker = '<span class="sr-only">оқылмаған</span>'
        self.assertIn(marker, html)
        self.assertNotIn('aria-label="оқылмаған"', html)
        # Отметка стоит только у непрочитанного — иначе она ничего не значит.
        self.assertEqual(html.count(marker), data.unread_count_for_user(user('aidana')))


class ReadingANotificationClearsIt(TestCase):
    """«Непрочитано» снимает открытие уведомления (BR-71).

    Метку не выставлял никто, кроме сида: колокольчик в шапке навсегда
    показывал число из демо-данных, а кнопка «Барлығын оқылды деп
    белгілеу» отвечала тостом «(демо)».
    """

    def setUp(self):
        super().setUp()
        login_as(self.client)
        self.unread = [n for n in _aidana_notifications() if not n.read]
        self.assertTrue(self.unread, 'корпус потерял непрочитанные')

    def _badge(self):
        return data.unread_count_for_user(user('aidana'))

    def _open(self, notification):
        return self.client.get(
            reverse('core:notification_open', kwargs={'pk': notification.pk}))

    def test_opening_one_clears_one_and_only_once(self):
        before = self._badge()
        self._open(self.unread[0])
        self.assertTrue(Notification.objects.get(pk=self.unread[0].pk).read)
        self.assertEqual(self._badge(), before - 1)
        self._open(self.unread[0])
        self.assertEqual(self._badge(), before - 1)

    def test_the_feed_itself_clears_nothing(self):
        """Строка, погасшая раньше, чем её прочли, — это ровно то
        состояние, ради которого бейдж и заводился."""
        before = self._badge()
        self.client.get(reverse('core:notifications'))
        self.assertEqual(self._badge(), before)

    def test_mark_all_needs_a_post_and_then_takes_the_button_away(self):
        before = self._badge()
        self.client.get(reverse('core:notifications_read_all'))
        self.assertEqual(self._badge(), before)
        self.client.post(reverse('core:notifications_read_all'))
        self.assertEqual(self._badge(), 0)
        self.assertNotContains(self.client.get(reverse('core:notifications')),
                               'Барлығын оқылды деп белгілеу')

    def test_nobody_clears_a_feed_that_is_not_theirs(self):
        """`user` в фильтре — закрытая дверь, а не удобство."""
        before = self._badge()
        target = self.unread[0]
        self.client.logout()
        self.client.post(reverse('core:notifications_read_all'))
        self._open(target)
        self.assertEqual(self._badge(), before)

        login_as(self.client, 'bekzhan_t')
        self._open(target)
        self.assertFalse(Notification.objects.get(pk=target.pk).read)


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
    SHOWN_AT = re.compile(
        r'\b(sm|md|lg|xl|2xl):(flex|block|grid|inline-flex|inline-block|table)\b')

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

    def test_the_link_survives_outside_the_desktop_cluster(self):
        login_as(self.client)
        for name in ('core:home', 'core:library', 'core:profile_me'):
            with self.subTest(page=name):
                self.assertTrue(
                    self._reachable_on(reverse(name)),
                    'ссылка на уведомления лежит только внутри поддерева, '
                    'скрытого до брейкпоинта: на телефоне раздел не открыть')

    def test_the_guard_actually_sees_the_desktop_cluster(self):
        """Страховка от теста, который проходит по недосмотру.

        Если бы `_desktop_only` не срабатывал ни на чём, предыдущий тест
        был бы зелёным при любой вёрстке.
        """
        self.assertTrue(
            self._desktop_only('ml-auto hidden items-center gap-6 md:flex'))
        self.assertFalse(
            self._desktop_only('ml-auto -mr-2 flex items-center md:hidden'))

    def test_the_badge_appears_only_when_there_is_something_to_count(self):
        login_as(self.client)
        self.assertContains(self.client.get(reverse('core:home')), 'оқылмаған')
        login_as_newcomer(self.client, 'no_notifs_user')
        self.assertNotContains(self.client.get(reverse('core:home')), 'оқылмаған')
        # Гостю считать нечего — колокольчик без сессии не рендерится.
        self.client.logout()
        home = self.client.get(reverse('core:home'))
        self.assertNotContains(home, 'Хабарламалар (')
        self.assertFalse(self._reachable_on(reverse('core:home')))


class StoryMetricIsCalledAReaction(TestCase):
    """Метрика произведения — сумма реакций по главам, а не лайки (DEC-32).

    Слово «ұнату» стояло на шести поверхностях: карточка каталога, строка
    кабинета, шапка произведения, «Аптаның кітабы», плитка профиля и
    список глав. Ни одна из них не показывала лайки — все показывали
    `Chapter.likes`, то есть сумму пяти реакций.

    **Лайк комментария (BR-31) — другое понятие и остаётся лайком.**
    Читатель действительно нажимает «ұнату» под комментарием; там нет ни
    глав, ни пяти реакций. Тест обязан различать эти два случая, иначе
    следующий проход по «ұнату» сравняет и его.
    """

    SURFACES = [
        ('core:catalog',      {},                        'карточка каталога'),
        ('core:my_stories',   {},                        'строка кабинета'),
        ('core:story_detail', {'slug': 'dalney-berega'}, 'шапка произведения'),
        ('core:home',         {},                        'Аптаның кітабы'),
        ('core:profile_me',   {},                        'плитка профиля'),
    ]

    def setUp(self):
        super().setUp()
        login_as(self.client)

    def test_no_surface_calls_the_sum_a_like_but_the_comment_keeps_its_own(self):
        for name, kwargs, label in self.SURFACES:
            with self.subTest(surface=label):
                html = self.client.get(
                    reverse(name, kwargs=kwargs)).content.decode()
                # Вырезаем комментарии: их «Ұнату» законен (BR-31).
                without_comments = html.replace('aria-label="Ұнату"', '')
                self.assertNotIn('ұнату', without_comments)
                self.assertNotIn('ұнатты', without_comments)
        story = self.client.get(reverse('core:story_detail',
                                        kwargs={'slug': 'dalney-berega'}))
        self.assertContains(story, 'aria-label="Ұнату"')

    def test_one_glyph_for_one_metric(self):
        """`thumbs-up` означал жест, который DEC-32 убрал."""
        offenders = []
        for path in list((TEMPLATES / 'components').glob('*.html')) + \
                list((TEMPLATES / 'pages').rglob('*.html')):
            body = path.read_text(encoding='utf-8')
            if 'story.likes' in body and 'thumbs-up' in body:
                offenders.append(path.name)
        self.assertFalse(offenders,
                         f'сумма реакций под иконкой лайка: {offenders}')
