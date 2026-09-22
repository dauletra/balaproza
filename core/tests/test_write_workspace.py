"""WRITE — кабинет и рабочее место автора.

`/write/` отвечает на один вопрос: что делать дальше. Полоса
«Назарыңды күтеді» молчит, когда ждать нечего, а статус работы говорится
одним словарём и на карточке, и в списке — расхождение здесь означало
бы, что автор видит два разных ответа про одну работу.

`/write/<slug>/` — список глав, редактор и чек-лист на одном экране:
узкая колонка рядом с редактором на широких, вкладки на телефоне. Было
четыре отдельных страницы, и переход между ними терял контекст.
"""


import re

from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.urls import reverse

from core import data
from core.domain.story import MAX_DRAFT_STORIES
from core.models import Chapter, Story
from core.tests import factories
from core.tests.base import login_as, login_as_newcomer, user
from core.templatetags.qazaqnovel import since, spaced


# ───────────────────────── Кабинет: my_stories_of / writer_stats ─────────

class TheCabinetAnswersWhatToDoNext(TestCase):
    """Список был описью имущества: он перечислял работы и
    молчал о том, что с ними делать. Порядок был порядком объявления в
    корпусе, а у непубличных строк вместо метрик стояло «0 · 0 · 0» —
    три нуля вместо ответа на единственный вопрос к такой работе."""

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:my_stories'))
        self.mine = data.my_stories_of(user('aidana'))

    def test_it_lists_every_work_with_its_status_and_its_actions(self):
        for story in self.mine:
            with self.subTest(story=story.slug):
                self.assertContains(self.response, story.title)
                self.assertContains(self.response, reverse(
                    'core:manage_story', kwargs={'slug': story.slug}))
                self.assertContains(self.response, reverse(
                    'core:story_settings', kwargs={'slug': story.slug}))
        for badge in ('Жарияланды', 'Жазылып жатыр', 'Модерацияда'):
            self.assertContains(self.response, badge)
        self.assertContains(self.response, 'open-delete-confirm')
        self.assertContains(self.response, reverse('core:new_story'))
        self.assertNotContains(self.response, 'Әлі шығарма жоқ')

    def test_only_a_public_work_offers_the_readers_view(self):
        """Сериал в работе публичен, хотя статус не `Published`."""
        for story in self.mine:
            url = reverse('core:story_detail', kwargs={'slug': story.slug})
            with self.subTest(story=story.slug, public=story.is_public):
                if story.is_public:
                    self.assertContains(self.response, url)
                else:
                    self.assertNotContains(self.response, url)

    def test_the_freshest_work_stands_first(self):
        days = [s.updated_days_ago for s in self.mine]
        self.assertEqual(days, sorted(days))
        body = self.response.content.decode()
        self.assertEqual([body.index(s.title) for s in self.mine],
                         sorted(body.index(s.title) for s in self.mine))
        self.assertContains(
            self.response,
            since(data.story_by_slug('aidana-tan').updated_at))

    def test_metrics_are_exact_spoken_and_never_zero_filler(self):
        """Значение в `stat_pill` помечено `aria-hidden`, иконка
        декоративна: пока подпись не передавалась, все цифры уходили из
        озвучки целиком. Кабинет при этом показывает точное число —
        «1,0 мың» здесь не годится."""
        story = data.story_by_slug('aidana-tan')
        views = spaced(story.recent_views)      # за две недели
        self.assertContains(self.response, f'{views} оқылым')
        self.assertContains(self.response, f'class="sr-only">{views} оқылым')
        self.assertContains(self.response, f'{spaced(story.likes)} реакция')
        self.assertNotContains(self.response, '1,0 мың')
        for zero in ('оқылым', 'реакция', 'пікір'):
            with self.subTest(metric=zero):
                self.assertNotContains(self.response, f'class="sr-only">0 {zero}')

    def test_a_non_public_row_says_what_is_happening_instead(self):
        self.assertContains(
            self.response,
            f"{data.story_by_slug_for_author('aidana-erteg', user('aidana')).updated_days_ago}"
            f" күн тексеруде")
        self.assertContains(self.response, 'әлі бір бөлім жоқ')

    def test_a_newcomer_gets_an_empty_state_with_a_way_in(self):
        login_as_newcomer(self.client, 'no-such-user')
        response = self.client.get(reverse('core:my_stories'))
        self.assertContains(response, 'Әлі шығарма жоқ')
        self.assertContains(response, 'Жаңа шығарма жазу')
        self.assertContains(response, reverse('core:new_story'))


class TheAttentionStripSpeaksOnlyWhenThereIsSomething(TestCase):
    """Сигналы, которые лежали в данных и нигде не сходились.
    `slug` заполнен только когда элемент один — вести «3 шығарма
    модерацияда» в одну из трёх было бы враньём."""

    def test_it_names_moderation_unread_comments_and_the_empty_draft(self):
        login_as(self.client)
        response = self.client.get(reverse('core:my_stories'))
        self.assertEqual([i['kind'] for i in data.writer_attention(user('aidana'))],
                         ['moderation', 'comments', 'draft'])
        self.assertContains(response, 'модерацияда')
        self.assertContains(response, 'жоба бастамада тұр')

        unread = sum(len([n for n in items if n.kind == 'comment' and not n.read])
                     for items in data.notifications_for_user(user('aidana')).values())
        self.assertGreater(unread, 0, 'корпус потерял непрочитанные пікір')
        self.assertContains(response, f'{unread} жаңа пікір')
        self.assertContains(response, reverse('core:notifications'))

    def test_a_single_item_points_at_the_work_a_group_does_not(self):
        for item in data.writer_attention(user('aidana')):
            with self.subTest(kind=item['kind']):
                if item['count'] > 1 or item['kind'] == 'comments':
                    self.assertEqual(item['slug'], '')
                else:
                    # Полоса внимания ведёт в кабинет, и работа в ней —
                    # непубличная по определению: своя дверь, не читательская.
                    self.assertIsNotNone(data.story_by_slug_for_author(
                        item['slug'], user('aidana')))

    def test_silence_when_there_is_nothing_to_say(self):
        self.assertEqual(data.writer_attention(user('no-such-user')), [])
        login_as_newcomer(self.client, 'quiet-author')
        self.assertNotContains(self.client.get(reverse('core:my_stories')),
                               'Назарыңды күтеді')
        self.assertNotContains(self.client_class().get(reverse('core:my_stories')),
                               'Назарыңды күтеді')


class TheCabinetCarriesNoAuthorTotals(TestCase):
    """Агрегаты автора живут в профиле, а не в кабинете.

    Рейл повторял четыре плитки `partials/profile/_stats.html` — и на
    странице одного произведения читался как статистика этого
    произведения: в шапке «1 042 оқылым», в рейле «Оқылым 2 117», без
    единого слова о том, что второе про весь портфель.
    """

    WRITE_URLS = (
        ('core:my_stories',     {}),
        ('core:new_story',      {}),
        ('core:manage_story',   {'slug': 'aidana-tan'}),
        ('core:story_settings', {'slug': 'aidana-tan'}),
        ('core:chapter_new',    {'slug': 'aidana-tan'}),
    )

    def test_no_write_page_has_a_rail_at_all(self):
        login_as(self.client)
        for name, kwargs in self.WRITE_URLS:
            with self.subTest(url=name):
                self.assertNotContains(
                    self.client.get(reverse(name, kwargs=kwargs)), '<aside')
        self.assertNotContains(Client().get(reverse('core:my_stories')), '<aside')
        unknown = self.client.get(
            reverse('core:manage_story', kwargs={'slug': 'no-such-story'}))
        self.assertNotContains(unknown, '<aside', status_code=404)

    def test_the_only_way_to_totals_is_the_profile(self):
        login_as(self.client)
        stats = data.writer_stats(user('aidana'))
        story = data.story_by_slug('aidana-tan')
        self.assertNotEqual(stats['views'], story.views)   # иначе тест пуст
        body = self.client.get(reverse(
            'core:manage_story', kwargs={'slug': 'aidana-tan'})).content.decode()
        self.assertIn(spaced(story.views), body)
        self.assertNotIn(spaced(stats['views']), body)
        self.assertContains(self.client.get(reverse('core:my_stories')),
                            reverse('core:profile_me') + '?tab=stats')


class StatusIsSpokenInOneVocabulary(TestCase):
    """«Жоба» — дефолт нового произведения, то есть первое,
    что видит автор; красным помечено то, что означает отказ или
    необратимое действие, а не нормальный этап пути."""

    def test_each_status_keeps_its_own_semantics(self):
        expected = {
            'NotPublished': 'bg-slate-100',
            'Published':    'status-published',
            'OnProcess':    'status-warning',
            'Completed':    'status-info',
            'OnModeration': 'status-attention',
        }
        for key, token in expected.items():
            with self.subTest(status=key):
                html = render_to_string('components/status_badge.html', {'key': key})
                self.assertIn(token, html)
        draft = render_to_string('components/status_badge.html',
                                 {'key': 'NotPublished'})
        self.assertIn('Жоба', draft)
        self.assertNotIn('status-error', draft)
        self.assertIn('status-error', render_to_string(
            'components/badge.html', {'kind': 'error', 'label': 'Қабылданбады'}))

    def test_the_breakdown_always_sums_to_the_total(self):
        """Черновик считался только в `total`, и «Барлығы 5» стояло над
        разбивкой 2+1+1. Слагаемые, не дающие целого, — то же враньё, что
        и хранимый счётчик, только разложенное на части."""
        for author in data.all_authors():
            stats = data.writer_stats(author)
            with self.subTest(author=author.username):
                self.assertEqual(
                    stats['published'] + stats['ongoing']
                    + stats['on_moderation'] + stats['draft']
                    + stats['needs_work'],
                    stats['total'])
        # Шестой статус обязан попасть и в разбивку: иначе
        # возвращённая работа считалась бы только в `total`.
        buckets = ('Published', 'Completed', 'OnProcess',
                   'OnModeration', 'NotPublished', 'NeedsWork')
        self.assertEqual(set(buckets), set(data.STORY_STATUSES))

    def test_the_helper_answers_only_about_its_own_author(self):
        mine = data.my_stories_of(user('aidana'))
        self.assertEqual(len(mine), 5)
        for story in mine:
            self.assertEqual(story.author.username, 'aidana')
        self.assertEqual(list(data.my_stories_of(user('no-such-user'))), [])
        stats = data.writer_stats(user('aidana'))
        self.assertEqual(stats['views'], sum(s.views for s in mine))
        self.assertEqual(stats['followers'],
                         data.author_by_username('aidana').followers)


class TheTextButtonOpensTheTextThatExists(TestCase):
    """Обе ветки кнопки указывали на `chapter_new`. У `single` глава ровно
    одна, и автор, нажав «Мәтін», получал чистый редактор: сохранение
    завело бы вторую главу у книги, у которой текст один по определению."""

    def test_a_single_work_edits_its_only_chapter_a_serial_adds_one(self):
        login_as(self.client)
        listing = self.client.get(reverse('core:my_stories'))
        for story in data.my_stories_of(user('aidana')):
            if not story.text_chapter:
                continue
            with self.subTest(story=story.slug):
                self.assertContains(listing, reverse(
                    'core:chapter_edit',
                    kwargs={'slug': story.slug, 'chapter': story.text_chapter}))
                self.assertNotContains(listing, reverse(
                    'core:chapter_new', kwargs={'slug': story.slug}))
        self.assertContains(listing, reverse(
            'core:chapter_new', kwargs={'slug': 'aidana-tan'}))

        manage = self.client.get(
            reverse('core:manage_story', kwargs={'slug': 'aidana-koshe'}))
        chapter_id = Chapter.objects.get(story__slug='aidana-koshe', number=1).pk
        self.assertContains(manage, reverse(
            'core:chapter_edit', kwargs={'slug': 'aidana-koshe', 'chapter': chapter_id}))
        self.assertNotContains(manage, reverse(
            'core:chapter_new', kwargs={'slug': 'aidana-koshe'}))


class TheCreationFormAsksThreeThings(TestCase):
    """Атау, формат, негізгі жанр. Форма из восьми полей
    стояла между автором и первой строкой текста и спрашивала о работе,
    которой ещё нет: тег к ненаписанному рассказу не выбирается,
    аннотация к нему не пишется."""

    def setUp(self):
        login_as(self.client)
        self.response = self.client.get(reverse('core:new_story'))

    def test_it_asks_for_three_and_nothing_more(self):
        for field in ('title', 'format', 'genre_primary'):
            with self.subTest(field=field):
                self.assertContains(self.response, f'name="{field}"')
        for field in ('annotation', 'genre_secondary', 'tags', 'agree'):
            with self.subTest(field=field):
                self.assertNotContains(self.response, f'name="{field}"')
        for genre in data.all_genres():
            with self.subTest(genre=genre.slug):
                self.assertContains(self.response, f'value="{genre.slug}"')
        # Формат перестраивает читательскую страницу целиком (docs/ui.md),
        # парой радио между аннотацией и жанром он подавался слабее жанра.
        self.assertContains(self.response, 'id="format-single"')
        self.assertContains(self.response, 'id="format-serial"')
        # Правила остаются на виду и остаются ссылкой, но без чекбокса.
        self.assertContains(self.response, reverse('core:legal_publishing'))
        self.assertContains(self.response, 'Жазуға кірісу')

    def test_status_is_not_asked_but_is_stated(self):
        """Новое произведение — всегда черновик. Форма предлагала
        `OnProcess` и `Completed` — оба публичные, причём «Аяқталды»
        стояло вариантом для работы с нулём бөлім. Убрать выбор мало:
        автор должен понимать, в каком состоянии окажется работа."""
        self.assertNotContains(self.response, 'name="status"')
        self.assertNotContains(self.response, 'value="OnProcess"')
        self.assertNotContains(self.response, 'value="Completed"')
        self.assertContains(self.response, 'жоба')

    def test_the_tag_dictionary_does_not_ride_along(self):
        """Автокомплит с блок-листом был самым тяжёлым элементом первого
        экрана автора — на экране, где теги не выбираются."""
        self.assertNotContains(self.response, 'id="tag-input-accepted"')
        self.assertNotIn('accepted_tags', self.response.context)
        self.assertNotIn('blocked_patterns', self.response.context)
        self.assertContains(
            self.client.get(reverse('core:story_settings',
                                    kwargs={'slug': 'aidana-tan'})),
            'id="tag-input-accepted"')


class ManageStoryShowsTheWorkAndItsParts(TestCase):

    SLUG = 'aidana-tan'

    def test_it_names_this_work_its_status_and_every_chapter(self):
        """Бейдж показывает статус ЭТОЙ работы. Проверка искала
        «Жарияланды» и проходила по слову из разбивки в правом рейле — та
        самая подмена, из-за которой рейл и убрали."""
        login_as(self.client)
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.SLUG}))
        story = data.story_by_slug(self.SLUG)
        self.assertEqual(story.status, 'OnProcess')
        self.assertContains(response, story.title)
        self.assertContains(response, 'Жазылып жатыр')
        for chapter in data.chapters_of(self.SLUG):
            with self.subTest(chapter=chapter.number):
                self.assertContains(response, chapter.title)
                self.assertContains(response, reverse(
                    'core:chapter_edit',
                    kwargs={'slug': self.SLUG, 'chapter': chapter.pk}))
        for route in ('core:chapter_new', 'core:story_settings', 'core:story_detail'):
            self.assertContains(response, reverse(route, kwargs={'slug': self.SLUG}))
        self.assertContains(response, 'open-delete-confirm')

    def test_a_work_without_chapters_says_so_and_an_unknown_one_is_not_found(self):
        login_as(self.client)
        self.assertContains(
            self.client.get(reverse('core:manage_story',
                                    kwargs={'slug': 'aidana-kus'})),
            'Әлі бөлім жоқ')
        self.assertEqual(
            self.client.get(reverse('core:manage_story',
                                    kwargs={'slug': 'no-such-story'})).status_code,
            404)

    def test_a_draft_shows_no_zero_metrics(self):
        """V8: «0 оқылым · 0 реакция · 0 пікір» у непубличной работы читалось
        как провал на пустом месте, хотя других значений там быть не может.
        Тот же приём, что у my_story_row.html в кабинете."""
        login_as(self.client)
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': 'aidana-kus'}))
        self.assertContains(response, 'жарияланбаған')
        for zero in ('оқылым', 'реакция', 'пікір'):
            with self.subTest(metric=zero):
                self.assertNotIn(f'0 {zero}', response.content.decode())

    def test_a_guest_is_shown_the_door_not_a_404(self):
        """M4/M7: гостю на кабинет — auth_gate (как у my_stories/new_story),
        а не та же карточка, что у вошедшего на чужой слаг."""
        response = Client().get(
            reverse('core:manage_story', kwargs={'slug': self.SLUG}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Шығармаңды басқару үшін')


class TheWorkspaceMergesListAndEditor(TestCase):
    """`manage_story` и `chapter_edit`/
    `chapter_new` рендерят одно тело (`partials/write/workspace_body.html`)
    — список глав и редактор активной главы на одном экране, не два
    отдельных шаблона с половиной разметки, повторённой один в один."""

    SLUG = 'aidana-tan'

    def setUp(self):
        login_as(self.client)
        self.story = Story.objects.get(slug=self.SLUG)

    def test_manage_story_embeds_the_chapter_editor_form(self):
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.SLUG}))
        self.assertContains(response, 'name="body"')
        self.assertContains(response, 'chapterEditor(')
        self.assertContains(response, 'Жоба ретінде сақтау')

    def test_chapter_edit_embeds_the_chapters_list(self):
        chapter = self.story.chapter_set.first()
        response = self.client.get(reverse(
            'core:chapter_edit', kwargs={'slug': self.SLUG, 'chapter': chapter.pk}))
        self.assertContains(response, 'Бөлімдер')
        for c in self.story.chapter_set.all():
            with self.subTest(chapter=c.number):
                self.assertContains(response, reverse(
                    'core:chapter_edit', kwargs={'slug': self.SLUG, 'chapter': c.pk}))

    def test_no_chapter_param_shows_the_last_chapter(self):
        """`_active_chapter_id`: без явного выбора — последняя по порядку
        написанная, а не первая (автор чаще всего продолжает, а не
        перечитывает начало)."""
        last = self.story.chapter_set.order_by('position', 'id').last()
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.SLUG}))
        self.assertContains(response, f'value="{last.title}"')

    def test_chapter_param_picks_that_chapter(self):
        first = self.story.chapter_set.order_by('position', 'id').first()
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.SLUG})
            + f'?chapter={first.pk}')
        self.assertContains(response, f'value="{first.title}"')

    def test_a_foreign_chapter_param_falls_back_quietly(self):
        """Чужой или несуществующий `?chapter=` — не 404 на всю страницу
        (в отличие от `/chapter/<id>/edit/`, где id — часть адреса, а не
        подсказка): молча возвращается дефолт."""
        foreign = Chapter.objects.exclude(story=self.story).first()
        last = self.story.chapter_set.order_by('position', 'id').last()
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.SLUG})
            + f'?chapter={foreign.pk}')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'value="{last.title}"')

    def test_switching_chapter_links_carry_htmx(self):
        """11.1c: строка главы и «Болдырмау» — обычные ссылки (рабочий
        адрес, фолбэк без JS, как у reaction_bar.html) с htmx поверх,
        подменяющим только #editor-pane."""
        chapter = self.story.chapter_set.first()
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.SLUG}))
        edit_url = reverse('core:chapter_edit',
                           kwargs={'slug': self.SLUG, 'chapter': chapter.pk})
        self.assertContains(response, f'hx-get="{edit_url}"')
        self.assertContains(response, 'hx-target="#editor-pane"')
        self.assertContains(response, 'hx-swap="outerHTML"')
        self.assertContains(response, 'hx-push-url="true"')

    def test_hx_request_returns_only_the_editor_pane(self):
        """Полный показ несёт список глав и опасную зону; ответ на
        `HX-Request` — только `#editor-pane`, без остального тела."""
        full = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.SLUG}))
        self.assertContains(full, 'Бөлімдер')
        self.assertContains(full, 'Қауіпті аймақ')

        fragment = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.SLUG}),
            HTTP_HX_REQUEST='true')
        self.assertContains(fragment, 'id="editor-pane"')
        self.assertContains(fragment, 'name="body"')
        self.assertNotContains(fragment, 'Бөлімдер')
        self.assertNotContains(fragment, 'Қауіпті аймақ')

    # Класс `<details>` чек-листа — свой, отдельный от двух других
    # `<details>` на этом экране (опрос главы, «Дайын тармақтар» внутри
    # самой панели): без этого якоря regex мог бы зацепить не тот узел.
    PANEL_DETAILS = 'group mb-8 rounded-lg border border-slate-200 bg-white'

    def test_the_checklist_panel_collapses_when_nothing_is_actionable(self):
        """11.2: 'aidana-tan' — публичный сериал, чек-лист закрыт, слать
        нечего (см. test_readiness_asks_the_text_and_not_the_status),
        замечания модератора нет. Панели нечего показывать активного —
        она свёрнута по умолчанию, а не занимает место рядом с
        редактором ради одного списка закрытых пунктов."""
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.SLUG}))
        body = response.content.decode()
        self.assertIn('Дайын', body)
        self.assertIn(self.PANEL_DETAILS, body)
        self.assertNotRegex(body, rf'<details class="{re.escape(self.PANEL_DETAILS)}"\s*open>')

    def test_the_checklist_panel_stays_open_with_missing_items(self):
        """'aidana-kus' — черновик, не хватает текста и жас белгісі:
        панели есть что показать, поэтому она раскрыта."""
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': 'aidana-kus'}))
        self.assertContains(response, 'Жас белгісін қой')
        self.assertRegex(response.content.decode(),
                         rf'<details class="{re.escape(self.PANEL_DETAILS)}"\s*open>')

    def test_the_chapter_row_no_longer_carries_its_own_edit_pencil(self):
        """11.2: вся строка теперь ссылка с тем же hx-* переключением —
        отдельная иконка «Өңдеу» стала лишней в узкой колонке."""
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.SLUG}))
        self.assertNotContains(response, 'aria-label="Өңдеу"')

    def test_hx_request_on_chapter_edit_also_returns_only_the_pane(self):
        chapter = self.story.chapter_set.first()
        fragment = self.client.get(
            reverse('core:chapter_edit',
                   kwargs={'slug': self.SLUG, 'chapter': chapter.pk}),
            HTTP_HX_REQUEST='true')
        self.assertContains(fragment, 'id="editor-pane"')
        self.assertContains(fragment, f'value="{chapter.title}"')
        self.assertNotContains(fragment, 'Бөлімдер')


class TheMobileLayoutTabsInsteadOfStacking(TestCase):
    """На узком экране чек-лист, редактор и
    список глав переключаются вкладками (`x-data`), а не идут одна под
    другой длинной прокруткой. С `lg` все три показаны разом — вкладки
    только прячут/показывают то, что и так есть в разметке."""

    SLUG = 'aidana-tan'

    def setUp(self):
        login_as(self.client)

    def test_the_three_panes_carry_lg_block_for_the_wide_layout(self):
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.SLUG}))
        self.assertContains(response, "x-data=\"{ tab: 'editor' }\"")
        self.assertContains(response, 'lg:block" :class="tab === \'checklist\'')
        self.assertContains(response, 'lg:block" :class="tab === \'editor\'')
        self.assertContains(response, 'lg:order-1 lg:block" :class="tab === \'chapters\'')

    def test_no_aria_tablist_role_is_claimed(self):
        """`role="tablist"`/`role="tab"`/`aria-selected` обещают
        скринридеру клавиатурную раскладку табов, которой тут нет —
        только три кнопки, переключающие видимость. Тот же разбор, что
        уже привёл к правке `segmented_control.html`."""
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.SLUG}))
        body = response.content.decode()
        self.assertNotIn('role="tablist"', body)
        self.assertNotIn('role="tab"', body)
        self.assertNotIn('aria-selected', body)

    def test_picking_a_chapter_on_the_list_tab_switches_to_the_editor_tab(self):
        """Строка главы живёт на вкладке «Бөлімдер»; без переключения
        обратно на «Жазу» свап #editor-pane прошёл бы незаметно для
        автора — панель обновилась бы за скрытой вкладкой."""
        story = Story.objects.get(slug=self.SLUG)
        chapter = story.chapter_set.first()
        edit_url = reverse('core:chapter_edit',
                           kwargs={'slug': self.SLUG, 'chapter': chapter.pk})
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.SLUG}))
        body = response.content.decode()
        row = re.search(rf'<a href="{re.escape(edit_url)}".*?</a>', body, flags=re.S)
        self.assertIsNotNone(row)
        self.assertIn("@click=\"tab = 'editor'\"", row.group())


# ═════════════════════ Ф15, Этап 1: запись (POST) ══════════════════════════
# До этой точки в файле — только GET/рендер. Ни один из этих тестов не
# существовал до Этапа 1: до него формы ничего не сохраняли.

class NewStoryCreatesADraft(TestCase):

    def setUp(self):
        login_as(self.client)
        self.genre = data.all_genres()[0]

    def test_creates_a_draft_owned_by_the_author_and_redirects_to_the_editor(self):
        r = self.client.post(reverse('core:new_story'), {
            'title': 'Сынақ шығармасы', 'format': 'serial',
            'genre_primary': self.genre.slug,
        })
        story = Story.objects.get(title='Сынақ шығармасы')
        self.assertEqual(story.author.username, 'aidana')
        self.assertEqual(story.status, 'NotPublished')
        self.assertEqual(story.format, 'serial')
        self.assertEqual(story.primary_genre_id, self.genre.pk)
        self.assertRedirects(
            r, reverse('core:chapter_new', kwargs={'slug': story.slug}))

    def test_slug_is_transliterated_and_url_safe(self):
        # Story.slug — ASCII (маршрут <slug:slug> кириллицу не матчит),
        # заголовок — казахский (domain/slugs.py).
        self.client.post(reverse('core:new_story'), {
            'title': 'Тау бөктеріндегі үй', 'format': 'single',
            'genre_primary': self.genre.slug,
        })
        story = Story.objects.get(title='Тау бөктеріндегі үй')
        self.assertRegex(story.slug, r'^[-a-zA-Z0-9_]+$')
        self.assertTrue(story.slug)

    def test_a_second_story_with_the_same_title_gets_a_distinct_slug(self):
        for _ in range(2):
            self.client.post(reverse('core:new_story'), {
                'title': 'Қайталанған атау', 'format': 'serial',
                'genre_primary': self.genre.slug,
            })
        slugs = set(Story.objects.filter(title='Қайталанған атау')
                    .values_list('slug', flat=True))
        self.assertEqual(len(slugs), 2)

    def test_missing_required_field_returns_the_form_not_an_empty_page(self):
        """Здесь стоял `assertRedirects` — то есть тест закреплял
        саму потерю ввода: у редиректа нет тела, и набранное пропадало
        вместе с ним."""
        before = Story.objects.count()
        r = self.client.post(reverse('core:new_story'), {
            'title': '', 'format': 'serial', 'genre_primary': self.genre.slug,
        })
        self.assertEqual(Story.objects.count(), before)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Атауын жаз.')
        self.assertContains(r, 'aria-invalid="true"')
        # Выбранное не сбрасывается к дефолтам формы.
        self.assertContains(r, f'value="{self.genre.slug}" selected')
        # `checked` стоит на следующей строке разметки карточки формата.
        self.assertRegex(r.content.decode(),
                         r'id="format-serial"[^>]*checked')

    def test_guest_post_creates_nothing(self):
        guest = Client()
        before = Story.objects.count()
        guest.post(reverse('core:new_story'), {
            'title': 'Қонақтың шығармасы', 'format': 'serial',
            'genre_primary': self.genre.slug,
        })
        self.assertEqual(Story.objects.count(), before)

    def test_a_pile_of_empty_drafts_hits_a_ceiling(self):
        """Ничем не ограниченное создание заводило горы черновиков
        — 25 POST подряд давали 25 работ. Опубликованное или поданное на
        модерацию в потолок не идёт — считаются только `NotPublished`, и
        корпус уже даёт автору один такой (`aidana-kus`)."""
        already = Story.objects.filter(author=user('aidana'), status='NotPublished').count()
        for _ in range(MAX_DRAFT_STORIES - already):
            self.client.post(reverse('core:new_story'), {
                'title': 'Жоба', 'format': 'serial',
                'genre_primary': self.genre.slug,
            })
        self.assertEqual(
            Story.objects.filter(author=user('aidana'), status='NotPublished').count(),
            MAX_DRAFT_STORIES)

        before = Story.objects.count()
        r = self.client.post(reverse('core:new_story'), {
            'title': 'Артық жоба', 'format': 'serial',
            'genre_primary': self.genre.slug,
        })
        self.assertEqual(Story.objects.count(), before)
        self.assertContains(r, 'тым көп')


class DeleteStoryRemovesIt(TestCase):

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)

    def test_get_does_not_delete(self):
        # Не «ничего не произошло», а «метод не тот»: удаление живёт только
        # за POST'ом из модалки подтверждения.
        response = self.client.get(
            reverse('core:delete_story', kwargs={'slug': self.SLUG}))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(Story.objects.filter(slug=self.SLUG).exists())

    def test_a_guest_is_sent_to_the_door_not_to_the_deletion(self):
        guest = Client()
        response = guest.post(reverse('core:delete_story',
                                      kwargs={'slug': self.SLUG}))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/auth/login/', response['Location'])
        self.assertTrue(Story.objects.filter(slug=self.SLUG).exists())

    def test_post_deletes_and_redirects_to_my_stories(self):
        r = self.client.post(reverse('core:delete_story', kwargs={'slug': self.SLUG}))
        self.assertFalse(Story.objects.filter(slug=self.SLUG).exists())
        self.assertRedirects(r, reverse('core:my_stories'))


class OwnershipIsEnforced(TestCase):
    """Ф15, Этап 1: `story_by_slug_for_author` фильтрует по автору — чужой
    slug и несуществующий неотличимы снаружи (IDOR)."""

    def setUp(self):
        login_as(self.client)  # aidana
        self.foreign = Story.objects.exclude(author__username='aidana').first()

    def test_manage_story_of_a_foreign_slug_is_not_found(self):
        # M6/M8: раньше чужой слаг рисовал ту же карточку «табылмады» кодом
        # 200, что и у вошедшего гостя на любую страницу, — теперь у уже
        # вошедшего это настоящий 404, а auth_gate остаётся у гостя.
        r = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.foreign.slug}))
        self.assertEqual(r.status_code, 404)

    def test_story_settings_post_does_not_touch_a_foreign_story(self):
        original_title = self.foreign.title
        self.client.post(
            reverse('core:story_settings', kwargs={'slug': self.foreign.slug}),
            {'title': 'Басып алынды', 'annotation': '', 'format': 'serial',
             'genre_primary': self.foreign.primary_genre.slug,
             'audience': '10+', 'tags': ''})
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.title, original_title)

    def test_chapter_editor_post_does_not_create_a_chapter_on_a_foreign_story(self):
        before = self.foreign.chapter_set.count()
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.foreign.slug}),
            {'title': 'Бөтен бөлім', 'body': 'Мәтін', 'action': 'draft'})
        self.assertEqual(self.foreign.chapter_set.count(), before)

    def test_delete_post_does_not_remove_a_foreign_story(self):
        self.client.post(
            reverse('core:delete_story', kwargs={'slug': self.foreign.slug}))
        self.assertTrue(Story.objects.filter(pk=self.foreign.pk).exists())

    def test_a_foreign_chapter_id_is_not_editable_deletable_or_movable(self):
        """Адрес кабинета — `pk`, но `pk` чужой главы своей
        работой всё равно не находится."""
        foreign_chapter = self.foreign.chapter_set.first()
        if foreign_chapter is None:
            foreign_chapter = Chapter.objects.create(
                story=self.foreign, number=1, position=1, title='Бөтен', body='Мәтін.')
        mine = factories.story(author=user('aidana'), chapters=1,
                               format='serial', published=False, slug='aidana-idor-target')

        edit = self.client.get(reverse(
            'core:chapter_edit', kwargs={'slug': mine.slug, 'chapter': foreign_chapter.pk}))
        self.assertEqual(edit.status_code, 404)

        before = self.foreign.chapter_set.count()
        self.client.post(reverse(
            'core:chapter_delete', kwargs={'slug': mine.slug, 'chapter': foreign_chapter.pk}))
        self.assertEqual(self.foreign.chapter_set.count(), before)

        before_position = foreign_chapter.position
        self.client.post(
            reverse('core:chapter_move',
                    kwargs={'slug': mine.slug, 'chapter': foreign_chapter.pk}),
            {'direction': 'down'})
        foreign_chapter.refresh_from_db()
        self.assertEqual(foreign_chapter.position, before_position)

        r = self.client.post(
            reverse('core:chapter_autosave',
                    kwargs={'slug': mine.slug, 'chapter': foreign_chapter.pk}),
            {'title': 'Басып алынды', 'body': 'Мәтін'})
        self.assertEqual(r.status_code, 404)
