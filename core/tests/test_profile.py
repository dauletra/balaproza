"""PROF — профиль автора: что видно и кому.

Один вопрос проходит через весь файл и проверяется здесь чаще прочего —
**кто зритель** (BR-73): посторонний видит только публичное, и однажды эти
две выдачи уже склеили — на `/u/<username>/` висели черновик и работа на
модерации.

Знаки и награды — в `test_awards.py`, полки — в `test_library.py`, лента
уведомлений — в `test_notification_feed.py`. Файл назывался «PROF · LIB ·
NOTIF» и держал три раздела сразу; разделены они не по длине, а потому
что отвечают на разные вопросы.
"""


from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import data
from core.models import Follow, Story, User
from core.tests import factories
from core.tests.base import TEMPLATES, TestCase, login_as, login_as_newcomer, user


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
        # Рейл профиля состоит из одного блока «Жазылымдар»; у гостя
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
        # «дочитано» — теперь плитка «Жазылушы» и заголовок рейла
        # «Жазылымдар» называют подписчиков и подписки разными словами.
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
        # Строка выводится из даты прихода, а не сверяется с литералом: она
        # относительная (DEC-57), и корпус двигает её вместе с сегодня.
        self.assertContains(about, user('aidana').joined_since)
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
        """Черновики автора — не публичный факт: чужой профиль не должен
        выдавать «Тек саған көрінеді» и число работ вместе с черновиками."""
        response = self.client.get(
            reverse('core:profile_other', kwargs={'username': 'rudazov'})
            + '?tab=about')
        self.assertContains(response, 'Фэнтези, шытырман')
        self.assertContains(response, user('rudazov').joined_since)
        self.assertNotContains(response, 'Тек саған көрінеді')
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
                self.assertNotContains(
                    self.response,
                    data.story_by_slug_for_author(slug, user('aidana')).title)
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

    Чужой профиль показывал «Жазылымдар» — на кого подписан **он**.
    Читателю это не сообщало ничего и занимало единственный блок колонки.
    """

    def test_a_stranger_gets_the_most_read_work_not_the_subscriptions(self):
        response = self.client.get(
            reverse('core:profile_other', kwargs={'username': 'aygerim_k'}))
        self.assertTrue(data.following_of(user('aygerim_k')))   # подписки есть
        self.assertNotContains(response, 'Жазылымдар')     # и они не здесь
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
        self.assertContains(response, 'Жазылымдар')
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

    FIELDS = {'username': 'aidana', 'pen_name': 'Аты', 'bio': ''}

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
        response = self._post(pen_name='Жаңа лақап', bio='Жаңа био.')
        self.assertRedirects(response, reverse('core:profile_me'))
        user = self._aidana()
        self.assertEqual([user.pen_name, user.bio],
                         ['Жаңа лақап', 'Жаңа био.'])

    def test_the_optional_half_may_be_left_blank(self):
        self._post(bio='Бар.')
        self._post(bio='')
        self.assertEqual(self._aidana().bio, '')

    def test_the_page_does_not_ask_for_age_or_gender(self):
        """Оба поля сняты (D4/D5): пол не показывался нигде, а возрастную
        вилку конкурса решает чекбокс формы подачи. Проверяется разметка —
        иначе снятое поле вернулось бы в неё и молча ничего не сохраняло."""
        page = self.client.get(reverse('core:profile_me_edit'))

        self.assertNotContains(page, 'name="gender"')
        self.assertNotContains(page, 'name="birth_date"')

    def test_a_bad_field_saves_nothing_and_returns_to_the_form(self):
        cases = {
            'username': ('ab', 'a' * 31, 'has space', 'a-b', 'rudazov'),
            'pen_name': ('', 'ә' * 61),
            'bio': ('ә' * 201,),
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
        self._post(avatar=factories.tiny_image('фото.png'))
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

    def test_resubmitting_the_same_username_is_not_a_conflict_with_self(self):
        """BR-91: `clean_username` исключает себя из проверки уникальности —
        иначе форма без единого изменения ника всегда отвечала бы «занят»."""
        response = self._post()
        self.assertRedirects(response, reverse('core:profile_me'))
        self.assertEqual(self._aidana().username, 'aidana')

    def test_changing_the_username_moves_the_public_address_and_frees_the_old_one(self):
        """BR-91: адрес меняется вместе с ником, старый — обычный 404
        (BR-76), не редирект и не «занято навсегда»."""
        pk = self._aidana().pk
        response = self._post(username='zhanaidana')
        self.assertRedirects(response, reverse('core:profile_me'))

        renamed = User.objects.get(pk=pk)
        self.assertEqual(renamed.username, 'zhanaidana')
        self.assertEqual(self.client.get(reverse(
            'core:profile_other', kwargs={'username': 'zhanaidana'})).status_code, 200)
        self.assertEqual(self.client.get(reverse(
            'core:profile_other', kwargs={'username': 'aidana'})).status_code, 404)

    def test_remove_avatar_clears_it_without_a_new_file(self):
        """BR-86: убрать фото, не заменив его другим."""
        self._post(avatar=factories.tiny_image('фото.png'))
        self.assertTrue(self._aidana().avatar)
        self._post(remove_avatar='on')
        self.assertFalse(self._aidana().avatar)

    def test_a_guest_writes_nothing(self):
        before = self._aidana().pen_name
        self._post(Client(), pen_name='Бөгде', name='Бөгде')
        self.assertEqual(self._aidana().pen_name, before)

    def test_the_form_prefills_the_raw_pen_name(self):
        """`value=` показывал `public_name` (pen_name or '@username'), не
        сырое поле: пустой pen_name отрисовался бы как «@username», и
        несохранённая форма сохранила бы это буквально при первом POST."""
        user = User.objects.create_user(username='blankpen', password='x',
                                        terms_accepted_at=timezone.now())
        self.assertEqual(user.pen_name, '')
        self.client.force_login(user)
        html = self.client.get(reverse('core:profile_me_edit')).content.decode()
        self.assertNotIn('value="@blankpen"', html)


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
