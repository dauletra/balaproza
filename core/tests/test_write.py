"""WRITE: авторский кабинет — my_stories, new, manage, settings, chapter_editor."""

import re
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core import data
from core.domain.story import MAX_DRAFT_STORIES
from core.models import Chapter, ChapterPoll, Story, Tag
from core.tests import factories
from core.tests.base import login_as, login_as_newcomer, user
from core.templatetags.balaproza import reading_meta, since, spaced


# ───────────────────────── Кабинет: my_stories_of / writer_stats ─────────

class TheCabinetAnswersWhatToDoNext(TestCase):
    """FR-WRITE-02/08. Список был описью имущества: он перечислял работы и
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
        """DEC-37: сериал в работе публичен, хотя статус не `Published`."""
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
        views = spaced(story.recent_views)      # за две недели (DEC-36)
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
        login_as_newcomer(self.client, 'no-such-user', name='Тест')
        response = self.client.get(reverse('core:my_stories'))
        self.assertContains(response, 'Әлі шығарма жоқ')
        self.assertContains(response, 'Жаңа шығарма жазу')
        self.assertContains(response, reverse('core:new_story'))


class TheAttentionStripSpeaksOnlyWhenThereIsSomething(TestCase):
    """FR-WRITE-08: сигналы, которые лежали в данных и нигде не сходились.
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
    """DEC-48: агрегаты автора живут в профиле, а не в кабинете.

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
    """BR-10/DEC-39. «Жоба» — дефолт нового произведения, то есть первое,
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
        # Шестой статус (BR-80) обязан попасть и в разбивку: иначе
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
    """FR-WRITE-01: атау, формат, негізгі жанр. Форма из восьми полей
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
        """BR-10: новое произведение — всегда черновик. Форма предлагала
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
        самая подмена, из-за которой рейл и убрали (DEC-48)."""
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
    """11.1b (AUDIT-WRITE-FLOW): `manage_story` и `chapter_edit`/
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


class SettingsOfferOnlyWhatMayBeChanged(TestCase):
    """BR-10a/BR-11: радио «Мәртебесі» рендерилось всегда и в ветке `else`
    подставляло черновику отмеченным «Аяқталды» — статус, которого у
    работы с нулём бөлім быть не может. У `single` допустимый статус один,
    а перевести работу в публичный может только модератор."""

    def _get(self, slug):
        return self.client.get(reverse('core:story_settings', kwargs={'slug': slug}))

    def setUp(self):
        login_as(self.client)

    def test_the_form_arrives_prefilled(self):
        story = data.story_by_slug('aidana-tan')
        response = self._get('aidana-tan')
        self.assertContains(response, f'value="{story.title}"')
        self.assertContains(response, f'value="{story.primary_genre.slug}" selected')
        for name in ('саяхат', 'жасөспірім', 'арман', 'эксперимент'):
            with self.subTest(tag=name):
                self.assertContains(response, name)

    def test_the_status_radio_belongs_to_public_serials_only(self):
        cases = {'aidana-kus': False,      # черновик
                 'aidana-erteg': False,    # на модерации
                 'aidana-koshe': False,    # одночастное
                 'aidana-tan': True}       # публичный сериал
        for slug, offered in cases.items():
            with self.subTest(story=slug):
                response = self._get(slug)
                if offered:
                    self.assertContains(response, 'name="status"')
                else:
                    self.assertNotContains(response, 'name="status"')
                # Отметка нужна именно черновику — без неё он из черновика
                # не выйдет, поэтому предлагается везде.
                self.assertContains(response, 'name="audience"')

    def test_the_age_mark_is_offered_and_preselected(self):
        """BR-10b: отметку выбирает автор, и выбирает он её здесь."""
        story = data.story_by_slug('aidana-tan')
        response = self._get('aidana-tan')
        for key, _mark, _hint in data.STORY_AUDIENCES:
            with self.subTest(audience=key):
                self.assertContains(response, f'value="{key}"')
        checked = re.findall(r'id="audience-([^"]+)"[^>]*?\bchecked\b',
                             response.content.decode(), flags=re.S)
        self.assertEqual(checked, [story.audience])

    def test_the_danger_zone_stays_on_one_page(self):
        """Две одинаковые красные секции на соседних экранах делают
        удаление фоном: то, что встречается на каждом шагу, перестаёт
        читаться как необратимое."""
        self.assertNotContains(self._get('aidana-tan'),
                               "$dispatch('open-delete-confirm'")
        self.assertContains(
            self.client.get(reverse('core:manage_story',
                                    kwargs={'slug': 'aidana-tan'})),
            "$dispatch('open-delete-confirm'")

    def test_a_guest_is_shown_the_door_not_a_404(self):
        response = Client().get(
            reverse('core:story_settings', kwargs={'slug': 'aidana-tan'}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Баптауларды өзгерту үшін')


class TheAgeMarkIsChosenNotDefaulted(TestCase):
    """BR-10b: поле хранилось с дефолтом «10+», не спрашивалось ни в одной
    форме и при этом раскладывало работы по оси «Жасың» каталога.
    Чек-лист рисовал за это решение зелёную галку — галку за несделанное."""

    def test_the_schema_carries_no_default(self):
        self.assertFalse(Story._meta.get_field('audience').has_default())
        self.assertEqual(Story().audience, '')

    def test_nothing_leaves_the_draft_stage_unmarked(self):
        for story in Story.objects.exclude(status='NotPublished'):
            with self.subTest(story=story.slug):
                self.assertIn(story.audience, data.AUDIENCE_ORDER,
                              f'{story.slug} вышла из черновика без отметки')

    def test_the_form_and_the_catalog_speak_differently(self):
        """В каталоге подпись называет вилку читателя («10-13»), в форме —
        отметку работы. Одна константа на оба места означала бы, что автор
        ставит работе метку «10-13», то есть «старше не читают»."""
        form = {mark for _k, mark, _h in data.STORY_AUDIENCES}
        catalog = {label for key, label in data.CATALOG_AUDIENCE_FILTERS if key}
        self.assertNotEqual(form, catalog)
        self.assertEqual([k for k, _m, _h in data.STORY_AUDIENCES],
                         list(data.AUDIENCE_ORDER))


class TheChecklistLeadsToTheFieldItNames(TestCase):
    """FR-WRITE-09: прежний список был описью — шесть строк, ни одна не
    кликалась, и над ними не было перехода, ради которого список нужен."""

    def setUp(self):
        login_as(self.client)

    def test_every_item_carries_a_link_to_where_it_is_closed(self):
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': 'aidana-kus'}))
        for item in data.publish_checklist(
                data.story_by_slug_for_author('aidana-kus', user('aidana'))):
            with self.subTest(item=item['key']):
                self.assertIn(item['target'], ('settings', 'text'))
        for item in response.context['checklist']:
            with self.subTest(item=item['key']):
                self.assertTrue(item['href'], f'{item["key"]} ведёт в никуда')
        text = next(i for i in response.context['checklist'] if i['key'] == 'text')
        self.assertEqual(text['href'], reverse('core:chapter_new',
                                               kwargs={'slug': 'aidana-kus'}))

    def test_for_a_single_work_the_text_item_opens_the_existing_chapter(self):
        story = data.story_by_slug('aidana-koshe')
        self.assertTrue(story.is_single and story.text_chapter)
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': 'aidana-koshe'}))
        text = next(i for i in response.context['checklist'] if i['key'] == 'text')
        self.assertEqual(text['href'], reverse(
            'core:chapter_edit',
            kwargs={'slug': 'aidana-koshe', 'chapter': story.text_chapter}))

    def test_settings_items_carry_their_own_field_anchor(self):
        """V6: пункт «Аннотация жаз» вёл на верх `/settings/` целиком —
        якорь есть, поля в нём нет. Теперь у каждого пункта баптаулар
        свой `#id`, и он совпадает с полем, которое реально существует
        на странице (иначе браузер просто не проскроллит)."""
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': 'aidana-kus'}))
        settings_page = self.client.get(
            reverse('core:story_settings', kwargs={'slug': 'aidana-kus'})).content.decode()
        anchors = {
            'annotation': 't-annotation', 'audience': 'audience',
            'cover': 'cover', 'tags': 'tags',
        }
        settings_href = reverse('core:story_settings', kwargs={'slug': 'aidana-kus'})
        for item in response.context['checklist']:
            if item['key'] not in anchors:
                continue
            with self.subTest(item=item['key']):
                anchor = anchors[item['key']]
                self.assertEqual(item['href'], f'{settings_href}#{anchor}')
                self.assertIn(f'id="{anchor}"', settings_page)

    def test_it_is_honest_about_the_age_mark_and_about_what_is_optional(self):
        """Обложка и теги улучшают карточку, но не держат публикацию."""
        draft = data.story_by_slug_for_author('aidana-kus', user('aidana'))
        self.assertEqual(draft.audience, '')
        self.assertContains(
            self.client.get(reverse('core:manage_story',
                                    kwargs={'slug': 'aidana-kus'})),
            'Жас белгісін қой')
        marked = data.story_by_slug('aidana-tan')
        self.assertContains(
            self.client.get(reverse('core:manage_story',
                                    kwargs={'slug': 'aidana-tan'})),
            f'Жас белгісі: {marked.audience}')
        required = {i['key'] for i in data.publish_checklist(draft)
                    if i['required']}
        self.assertEqual(required, {'text', 'annotation', 'audience'})


class OnlyAReadyDraftMayBeSubmitted(TestCase):
    """BR-11: «готова» и «уже ушла» — разные вопросы. У работы на
    модерации кнопка означала бы повторную заявку, у публичной — откат в
    непубличное, чего автор ею не просит."""

    def setUp(self):
        login_as(self.client)

    def _get(self, slug):
        return self.client.get(reverse('core:manage_story', kwargs={'slug': slug}))

    def test_an_incomplete_draft_sees_the_button_disabled(self):
        draft = data.story_by_slug_for_author('aidana-kus', user('aidana'))
        self.assertFalse(data.can_submit_for_review(draft))
        self.assertEqual(data.missing_for_review(draft), ['text', 'audience'])
        response = self._get('aidana-kus')
        self.assertFalse(response.context['can_submit'])
        self.assertContains(response, 'disabled')
        self.assertContains(response, 'Модерацияға жіберу')

    def test_a_work_that_already_left_the_drafts_sees_no_button(self):
        for slug in ('aidana-tan', 'aidana-erteg'):
            with self.subTest(story=slug):
                story = data.story_by_slug_for_author(slug, user('aidana'))
                self.assertIsNotNone(story)
                self.assertFalse(data.can_submit_for_review(story))
                self.assertNotContains(self._get(slug), 'Модерацияға жіберу')

    def test_readiness_asks_the_text_and_not_the_status(self):
        """BR-79: подаётся то, что изменилось, и статус тут ни при чём.

        Прежняя проверка требовала `status == 'NotPublished'` — то есть
        публичный сериал не мог отправить дописанную главу вовсе, и она
        публиковалась мимо модерации (C1).
        """
        published = data.story_by_slug_for_author('aidana-tan', user('aidana'))
        self.assertEqual(data.missing_for_review(published), [])
        # Всё опубликовано — подавать нечего, хотя чек-лист закрыт.
        self.assertFalse(data.can_submit_for_review(published))

        chapter = published.chapter_set.first()
        chapter.body += ' Автор бір сөйлем қосты.'
        chapter.save()
        self.assertTrue(data.can_submit_for_review(published))

    def test_a_brand_new_work_sees_the_editor_button_disabled_not_a_trap(self):
        """V14: на первой странице совсем новой работы кнопка была активна,
        хотя аннотации и жас белгісі ещё нет и быть не может, — нажатие
        гарантированно било мимо. Здесь — та же неактивная кнопка с
        подсказкой, что и на manage_story, а не молчаливая (см. ниже)."""
        draft = data.story_by_slug_for_author('aidana-kus', user('aidana'))
        self.assertEqual(data.missing_for_review(draft), ['text', 'audience'])
        response = self.client.get(
            reverse('core:chapter_new', kwargs={'slug': 'aidana-kus'}))
        self.assertFalse(response.context['can_submit'])
        self.assertContains(response, 'Модерацияға жіберу')
        self.assertContains(response, 'disabled')

    def test_nothing_to_submit_hides_the_editor_button_quietly(self):
        """Чек-лист закрыт, слать нечего (test_readiness_asks_the_text_...)
        — кнопка молчит совсем, а не остаётся мимо-кнопкой и не врёт
        disabled-подсказкой про несуществующие незакрытые пункты."""
        published = data.story_by_slug_for_author('aidana-tan', user('aidana'))
        self.assertEqual(data.missing_for_review(published), [])
        self.assertFalse(data.can_submit_for_review(published))
        chapter = published.chapter_set.first()
        response = self.client.get(reverse(
            'core:chapter_edit', kwargs={'slug': 'aidana-tan', 'chapter': chapter.pk}))
        self.assertNotContains(response, 'Модерацияға жіберу')


class TheChapterEditorReportsTheTruth(TestCase):
    """FR-WRITE-05. Счётчик знаков не двигался при вводе, кнопки уходили за
    нижний край, а индикатор изображал автосохранение, которого нет."""

    SLUG = 'aidana-tan'

    def setUp(self):
        login_as(self.client)

    def test_a_new_chapter_opens_empty_with_both_ways_to_save(self):
        """BR-11: автор не публикует, публикует модератор. Кнопка
        называлась «Жариялау», а тост рядом говорил «модерацияға
        жіберілді» — правду говорил тост. «Тексеруге» тоже не годится:
        docs/ui.md отводит ему оттенок экзамена.

        'aidana-kus' — черновик без бөлім и жас белгісі: кнопка здесь
        стоит неактивной с самого начала (V14), а не самим же 'aidana-tan',
        у которого слать нечего и кнопки нет вовсе (см.
        OnlyAReadyDraftMayBeSubmitted)."""
        response = self.client.get(
            reverse('core:chapter_new', kwargs={'slug': 'aidana-kus'}))
        body = response.content.decode()
        self.assertContains(response, 'Жаңа бөлім')
        self.assertContains(response, 'name="title"')
        self.assertContains(response, 'name="body"')
        self.assertContains(response, 'Жоба ретінде сақтау')
        self.assertIn('Модерацияға жіберу', body)
        self.assertContains(response, 'disabled')
        self.assertNotIn('Тексеруге жіберу', body)

    def test_the_counter_counts_typing_and_the_actions_stay_in_view(self):
        """Статичное `{{ current.char_count }}` не двигалось при вводе,
        хотя соседняя аннотация считала живьём — две механики одного и
        того же на одном экране. `bottom-24` разводит панель с плавающей
        пилюлей `mobile_nav` (docs/ui.md)."""
        body = self.client.get(reverse(
            'core:chapter_new', kwargs={'slug': self.SLUG})).content.decode()
        self.assertIn('x-text="count"', body)
        self.assertIn('charCounter(', body)
        self.assertIn('@input="recount"', body)
        self.assertIn('sticky bottom-24', body)
        self.assertIn('md:bottom-0', body)

    def test_the_mobile_panel_is_compact_and_the_box_is_tall(self):
        """V5: на 375×812 панель в три строки плюс плавающая пилюля
        занимали около половины экрана, а от textarea `rows=20` со своим
        внутренним скроллом оставалась полоса в четыре строки.

        Подписи уходят в `sr-only`, не `hidden`: скринридер видит их и на
        узком экране, только зрячий — нет (`not-sr-only` возвращает их с
        `sm`). Панель — сплошная на мобильном, а не просвечивающая
        `backdrop-blur`; коробка текста — высотой во вьюпорт, а не строками."""
        body = self.client.get(reverse(
            'core:chapter_new', kwargs={'slug': self.SLUG})).content.decode()
        self.assertIn('sr-only sm:not-sr-only', body)
        self.assertNotIn('rows="20"', body)
        self.assertIn('min-h-[62vh]', body)
        self.assertIn('[field-sizing:content]', body)
        self.assertIn('bg-white px-4 py-2.5', body)
        self.assertIn('sm:bg-white/95', body)

    def test_saved_state_is_server_truth_not_a_timer(self):
        """На новой главе «Жоба сақталды» не должно быть вовсе: сообщать о
        сохранении того, что ни разу не сохранялось, — та же ложь, что
        рисовал прежний фейковый submit."""
        fresh = self.client.get(reverse(
            'core:chapter_new', kwargs={'slug': self.SLUG})).content.decode()
        # Состояние ведёт `chapterEditor` (BR-78): индикатор больше не
        # изображает автосохранение — оно у него настоящее, и «сақталды»
        # он говорит по ответу сервера, а не по таймеру.
        self.assertIn('chapterEditor(', fresh)
        self.assertIn('@input="touch"', fresh)
        self.assertIn('Сақталмаған өзгеріс бар', fresh)
        self.assertNotIn('Жоба сақталды', fresh)
        self.assertNotIn('setInterval', fresh)

        first_chapter = Chapter.objects.get(story__slug=self.SLUG, number=1)
        existing = self.client.get(reverse(
            'core:chapter_edit', kwargs={'slug': self.SLUG, 'chapter': first_chapter.pk}))
        self.assertContains(existing, 'Жоба сақталды')
        self.assertContains(existing, f'value="{first_chapter.title}"')
        self.assertContains(existing, 'Бірде ерте таңда')

    def test_an_unknown_work_has_no_editor(self):
        self.assertEqual(
            self.client.get(reverse('core:chapter_new',
                                    kwargs={'slug': 'no-such-story'})).status_code,
            404)

    def test_a_guest_is_shown_the_door_not_a_404(self):
        """11.1b: `chapter_edit`/`chapter_new` рендерят то же тело, что
        `manage_story` (`workspace_body.html`) — один и тот же
        auth_gate на весь объединённый экран, не свой на каждый URL."""
        response = Client().get(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Шығармаңды басқару үшін')


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
        """BR-77. Здесь стоял `assertRedirects` — то есть тест закреплял
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
        """M2/BR-88: ничем не ограниченное создание заводило горы черновиков
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


class StorySettingsSavesFields(TestCase):

    SLUG = 'aidana-kus'  # NotPublished, 0 бөлім, audience='' — aidana-нікі

    def setUp(self):
        login_as(self.client)
        self.genre = data.all_genres()[0]
        # `title='Жаңа атау'` в дефолте `_post` меняет название, а с ним, у
        # непубличной работы, и слаг (M1, BR-87) — дальше по классу объект
        # ищется по `pk`, застрахованному от этого сдвига, а не по слагу.
        self.pk = Story.objects.get(slug=self.SLUG).pk

    def _post(self, **overrides):
        payload = {
            'title': 'Жаңа атау', 'annotation': 'Жаңа аннотация мәтіні.',
            'format': 'serial', 'genre_primary': self.genre.slug,
            'genre_secondary': '', 'audience': '10+', 'tags': '',
        }
        payload.update(overrides)
        return self.client.post(
            reverse('core:story_settings', kwargs={'slug': self.SLUG}), payload)

    def test_saves_title_annotation_and_audience(self):
        r = self._post()
        story = Story.objects.get(pk=self.pk)
        self.assertEqual(story.title, 'Жаңа атау')
        self.assertEqual(story.annotation, 'Жаңа аннотация мәтіні.')
        self.assertEqual(story.audience, '10+')
        # M1/BR-87: переименование до публикации сдвигает и адрес — работа
        # не живёт вечно по адресу первого черновика.
        self.assertNotEqual(story.slug, self.SLUG)
        self.assertRedirects(
            r, reverse('core:story_settings', kwargs={'slug': story.slug}))

    def test_missing_title_saves_nothing(self):
        self._post(title='')
        story = Story.objects.get(pk=self.pk)
        self.assertNotEqual(story.title, '')
        self.assertNotEqual(story.audience, '10+')

    def test_cannot_switch_to_single_with_more_than_one_chapter(self):
        story = Story.objects.get(pk=self.pk)
        Chapter.objects.create(story=story, number=1, title='1', body='т')
        Chapter.objects.create(story=story, number=2, title='2', body='т')
        self._post(format='single')
        story.refresh_from_db()
        self.assertEqual(story.format, 'serial')

    def test_an_annotation_past_the_limit_saves_nothing(self):
        """BR-16: 500 знаков. Число жило в поле счётчика шаблона и в этом
        правиле, но в проверке не участвовало вовсе — сохранялось что
        угодно."""
        before = Story.objects.get(pk=self.pk).annotation
        self._post(annotation='ә' * 501)
        self.assertEqual(Story.objects.get(pk=self.pk).annotation, before)
        self._post(annotation='ә' * 500)
        self.assertEqual(len(Story.objects.get(pk=self.pk).annotation), 500)

    def test_status_field_outside_the_allowed_set_is_ignored(self):
        # 'aidana-kus' — черновик, радио «Мәртебесі» на этой странице у
        # него вообще не рендерится (BR-10a) — POST в обход формы не
        # должен провести статус мимо модерации.
        self._post(status='Published')
        story = Story.objects.get(pk=self.pk)
        self.assertFalse(story.is_public)
        # Статус вообще не берётся из формы — он выводится из глав (BR-79),
        # а эту работу корпус вернул автору на доработку (BR-80).
        self.assertEqual(story.status, 'NeedsWork')


class StorySettingsCoverUpload(TestCase):
    """Тот же валидатор, что у User.avatar (BR-46) — SVG не проходит.

    Отсекает его сам `RASTER_ONLY` на поле модели: форма страницы —
    `StorySettingsForm`, и валидаторы поля в ней срабатывают. Ручной вызов
    рядом с присваиванием, который держал это правило раньше, был третьим
    местом, где его можно было забыть.
    """

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)
        self.genre = data.all_genres()[0]
        # Название в payload остаётся тем же, что уже стоит: смена вызвала
        # бы сдвиг слага непубличной работы (M1, BR-87), а эти тесты про
        # обложку, не про адрес.
        self.title = Story.objects.get(slug=self.SLUG).title

    def _post(self, **overrides):
        payload = {
            'title': self.title, 'annotation': 'Жаңа аннотация мәтіні.',
            'format': 'serial', 'genre_primary': self.genre.slug,
            'genre_secondary': '', 'audience': '10+', 'tags': '',
        }
        payload.update(overrides)
        return self.client.post(
            reverse('core:story_settings', kwargs={'slug': self.SLUG}), payload)

    def test_svg_is_refused(self):
        cover = SimpleUploadedFile('мұқаба.svg', b'<svg/>',
                                   content_type='image/svg+xml')
        self._post(cover=cover)
        story = Story.objects.get(slug=self.SLUG)
        self.assertFalse(story.cover)

    def test_svg_refusal_also_blocks_the_rest_of_the_form(self):
        """Ошибка одного поля — весь POST no-op, не частичное сохранение."""
        before = Story.objects.get(slug=self.SLUG).title
        cover = SimpleUploadedFile('мұқаба.svg', b'<svg/>',
                                   content_type='image/svg+xml')
        self._post(cover=cover, title='Басқа атау')
        self.assertEqual(Story.objects.get(slug=self.SLUG).title, before)

    def test_png_is_accepted(self):
        self._post(cover=factories.tiny_image('мұқаба.png'))
        story = Story.objects.get(slug=self.SLUG)
        self.assertTrue(story.cover.name.startswith(f'covers/{self.SLUG}'))

    def test_the_refused_cover_does_not_take_the_rest_of_the_form_with_it(self):
        """BR-77. Отказ по обложке — самая дорогая ошибка этой страницы:
        вместе с файлом уносило аннотацию, отметку и теги, то есть всё, что
        человек только что набрал. Файл вернуть нельзя, браузер его не
        отдаёт, — об этом форма говорит прямо; остальное на месте."""
        cover = SimpleUploadedFile('мұқаба.svg', b'<svg/>',
                                   content_type='image/svg+xml')
        r = self._post(cover=cover, annotation='Жазылған аннотация мәтіні.',
                       audience='14+', tags='мектеп')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Жазылған аннотация мәтіні.')
        self.assertContains(r, 'value="14+"')
        self.assertContains(r, "name:'мектеп'")
        self.assertContains(r, 'Файлды қайта таңда')
        # И ничего из этого не сохранилось: отказ есть отказ.
        story = Story.objects.get(slug=self.SLUG)
        self.assertNotEqual(story.annotation, 'Жазылған аннотация мәтіні.')
        self.assertEqual(story.tags.count(), 0)

    def test_a_refused_form_does_not_leave_pending_tags_behind(self):
        """Набранный тег возвращается чипом, но в базу не пишется: иначе
        `pending`-тег пережил бы работу, которая не сохранилась."""
        cover = SimpleUploadedFile('мұқаба.svg', b'<svg/>',
                                   content_type='image/svg+xml')
        self._post(cover=cover, tags='мүлдем-жаңа-тег')
        self.assertFalse(Tag.objects.filter(name='мүлдем-жаңа-тег').exists())

    def test_remove_cover_clears_it_without_a_new_file(self):
        """BR-86: третье состояние рядом с «новый файл» и «пусто значит не
        меняем» — раньше убрать обложку, не заменив её другой, было нечем."""
        self._post(cover=factories.tiny_image('мұқаба.png'))
        self.assertTrue(Story.objects.get(slug=self.SLUG).cover)
        self._post(remove_cover='on')
        self.assertFalse(Story.objects.get(slug=self.SLUG).cover)

    def test_a_new_file_wins_over_remove_cover(self):
        self._post(cover=factories.tiny_image('бірінші.png'))
        self._post(cover=factories.tiny_image('екінші.jpg'), remove_cover='on')
        self.assertTrue(Story.objects.get(slug=self.SLUG).cover)


class StorySettingsTagResolution(TestCase):

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)
        self.genre = data.all_genres()[0]
        # Тот же довод, что у StorySettingsCoverUpload: неизменное название
        # не сдвигает слаг непубличной работы (M1, BR-87).
        self.title = Story.objects.get(slug=self.SLUG).title

    def _post(self, tags):
        return self.client.post(
            reverse('core:story_settings', kwargs={'slug': self.SLUG}),
            {'title': self.title, 'annotation': 'Аннотация.', 'format': 'serial',
             'genre_primary': self.genre.slug, 'audience': '10+', 'tags': tags})

    def test_existing_accepted_tag_is_reused_not_duplicated(self):
        before = Tag.objects.filter(slug='mektep').count()
        self._post('мектеп')
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(Tag.objects.filter(slug='mektep').count(), before)
        self.assertIn('mektep', story.tags.values_list('slug', flat=True))

    def test_new_name_creates_a_pending_tag(self):
        self._post('жаңа-тег-осында')
        story = Story.objects.get(slug=self.SLUG)
        tag = story.tags.get(name='жаңа-тег-осында')
        self.assertEqual(tag.status, 'pending')

    def test_blocked_pattern_is_dropped_silently(self):
        patterns = data.blocked_tag_patterns_list()
        if not patterns:
            self.skipTest('блок-лист демо-корпуса пуст')
        self._post(patterns[0])
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.tags.count(), 0)


class ChapterEditorSavesADraft(TestCase):

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)

    def test_draft_action_creates_a_chapter_without_changing_status(self):
        r = self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
            {'title': '1-бөлім', 'body': 'Бір кездері...', 'action': 'draft'})
        story = Story.objects.get(slug=self.SLUG)
        chapter = story.chapter_set.get(number=1)
        self.assertEqual(chapter.title, '1-бөлім')
        self.assertEqual(chapter.char_count, len('Бір кездері...'))
        self.assertEqual(story.status, 'NotPublished')
        self.assertRedirects(r, reverse(
            'core:chapter_edit', kwargs={'slug': self.SLUG, 'chapter': chapter.pk}))

    def test_empty_body_saves_nothing(self):
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
            {'title': '1-бөлім', 'body': '  ', 'action': 'draft'})
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.chapter_set.count(), 0)

    def test_saving_a_chapter_touches_the_story(self):
        """S4: письмо главы — правка работы. Кабинет сортирует «что трогал
        последним» по `Story.updated_at`, а `Chapter.save()` его не
        трогал — автор писал часами и не поднимался в списке."""
        old = timezone.now() - timedelta(days=1)
        Story.objects.filter(slug=self.SLUG).update(updated_at=old)
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
            {'title': '1-бөлім', 'body': 'Мәтін.', 'action': 'draft'})
        self.assertGreater(Story.objects.get(slug=self.SLUG).updated_at, old)

    def test_line_endings_are_normalized_before_counting(self):
        """V1: браузер шлёт textarea нормализованным в `\\r\\n`, живой
        счётчик в редакторе считает JS-строку с голым `\\n` — без
        нормализации здесь объём расходился на число абзацев."""
        body_with_crlf = 'Бірінші жол.\r\nЕкінші жол.\r\nҮшінші жол.'
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
            {'title': '1-бөлім', 'body': body_with_crlf, 'action': 'draft'})
        chapter = Story.objects.get(slug=self.SLUG).chapter_set.get(number=1)
        normalized = body_with_crlf.replace('\r\n', '\n')
        self.assertEqual(chapter.body, normalized)
        self.assertEqual(chapter.char_count, len(normalized))

    def test_written_chapters_show_up_in_the_count(self):
        """«N бөлім» на карточке — то, что автор написал.

        Раньше число было колонкой, которую заполняли при создании работы,
        а запись главы её не трогала: автор писал три бөлім и видел «0».
        Проверяется в обоих видах — у одиночного объекта и в выдаче
        каталога, где число приезжает аннотацией.
        """
        for number in (1, 2, 3):
            self.client.post(
                reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
                {'title': f'{number}-бөлім', 'body': 'Мәтін.', 'action': 'draft'})

        story = Story.objects.get(slug=self.SLUG)
        # Написанное, а не опубликованное (BR-79): автор, написавший три
        # бөлім, обязан видеть три — даже пока их никто не одобрил.
        self.assertEqual(story.chapters_written, 3)
        self.assertEqual(story.chapters, 0)

        from_feed = next(s for s in data.my_stories_of(user('aidana'))
                         if s.slug == self.SLUG)
        self.assertEqual(from_feed.chapters_written, 3)

    def test_a_rejected_form_gives_the_text_back(self):
        """BR-77 — главный отказ этой страницы.

        Автор набирал текст, ошибался в заголовке и получал **пустую**
        форму с тостом «Атауын және мәтінін жаз» — требованием написать
        ровно то, что только что стёрли вместе с редиректом.
        """
        body = 'Тау басында бір хат жатыр екен. ' * 60
        r = self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
            {'title': '   ', 'body': body, 'action': 'draft'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Story.objects.get(slug=self.SLUG).chapter_set.count(), 0)
        self.assertContains(r, 'Бөлім атауын жаз.')
        self.assertContains(r, 'Тау басында бір хат жатыр екен.')
        self.assertContains(r, 'aria-invalid="true"')
        # И не утверждает обратного: зелёное «Жоба сақталды» рядом с
        # красным полем — прямая ложь о том, что ничего не сохранилось.
        self.assertNotContains(r, 'Жоба сақталды')

    def test_the_form_shows_what_was_typed_not_what_is_stored(self):
        """Значения приходят из формы, а не из базы. Иначе отказ показывал
        бы сохранённое — то есть молча откатывал правку на экране."""
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
            {'title': '1-бөлім', 'body': 'Сақталған мәтін.', 'action': 'draft'})
        chapter_id = Chapter.objects.get(story__slug=self.SLUG, number=1).pk
        r = self.client.post(
            reverse('core:chapter_edit', kwargs={'slug': self.SLUG, 'chapter': chapter_id}),
            {'title': '', 'body': 'Терілген жаңа мәтін.', 'action': 'draft'})
        self.assertContains(r, 'Терілген жаңа мәтін.')
        self.assertNotContains(r, 'Сақталған мәтін.')
        self.assertEqual(
            Story.objects.get(slug=self.SLUG).chapter_set.get(number=1).body,
            'Сақталған мәтін.')

    def test_editing_an_existing_chapter_does_not_duplicate_it(self):
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
            {'title': '1-бөлім', 'body': 'Бастапқы мәтін.', 'action': 'draft'})
        chapter_id = Chapter.objects.get(story__slug=self.SLUG, number=1).pk
        self.client.post(
            reverse('core:chapter_edit', kwargs={'slug': self.SLUG, 'chapter': chapter_id}),
            {'title': '1-бөлім (өңделген)', 'body': 'Жаңа мәтін.', 'action': 'draft'})
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.chapter_set.count(), 1)
        self.assertEqual(story.chapter_set.get(number=1).title, '1-бөлім (өңделген)')


class ChapterEditorSavesAPoll(TestCase):

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)

    def test_two_or_more_options_create_a_poll(self):
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}), {
                'title': '1-бөлім', 'body': 'Мәтін.', 'action': 'draft',
                'poll_question': 'Кім жеңеді?',
                'poll_option': ['Біріншісі', 'Екіншісі'],
            })
        chapter = Story.objects.get(slug=self.SLUG).chapter_set.get(number=1)
        self.assertEqual(chapter.poll.question, 'Кім жеңеді?')
        self.assertEqual(chapter.poll.option_set.count(), 2)

    def test_a_single_option_is_an_error_and_not_silence(self):
        """BR-POLL-02 остаётся, меняется способ сказать о нём.

        Раньше глава сохранялась, опрос молча исчезал, и автор получал
        «Жоба сақталды» — про главу правду, про опрос ложь. Молчание было
        возможно потому, что варианты приходили мимо формы.
        """
        r = self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}), {
                'title': '1-бөлім', 'body': 'Ұзақ жазылған мәтін.',
                'action': 'draft',
                'poll_question': 'Кім жеңеді?', 'poll_option': ['Жалғыз нұсқа'],
            })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Story.objects.get(slug=self.SLUG).chapter_set.count(), 0)
        self.assertContains(r, 'кемінде 2 нұсқа жаз')
        # И всё набранное — на месте, включая сам опрос.
        self.assertContains(r, 'Ұзақ жазылған мәтін.')
        self.assertContains(r, 'Кім жеңеді?')
        self.assertContains(r, 'Жалғыз нұсқа')

    def test_options_without_a_question_are_an_error_too(self):
        r = self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}), {
                'title': '1-бөлім', 'body': 'Мәтін бар.', 'action': 'draft',
                'poll_question': '', 'poll_option': ['Бірі', 'Екіншісі'],
            })
        self.assertContains(r, 'сұрақтың өзін де жаз')
        self.assertEqual(Story.objects.get(slug=self.SLUG).chapter_set.count(), 0)

    def test_clearing_the_question_removes_the_poll(self):
        """Автор передумал — это законный исход, а не ошибка."""
        url = reverse('core:chapter_new', kwargs={'slug': self.SLUG})
        self.client.post(url, {
            'title': '1-бөлім', 'body': 'Мәтін.', 'action': 'draft',
            'poll_question': 'Кім жеңеді?', 'poll_option': ['Бірі', 'Екіншісі']})
        chapter = Story.objects.get(slug=self.SLUG).chapter_set.get(number=1)
        self.assertTrue(hasattr(chapter, 'poll'))

        self.client.post(
            reverse('core:chapter_edit',
                    kwargs={'slug': self.SLUG, 'chapter': chapter.pk}),
            {'title': '1-бөлім', 'body': 'Мәтін.', 'action': 'draft',
             'poll_question': '', 'poll_option': ['', '']})
        chapter.refresh_from_db()
        self.assertFalse(ChapterPoll.objects.filter(chapter=chapter).exists())


class AutosaveKeepsTheTextWithoutBeingAsked(TestCase):
    """BR-78. Индикатор «Сақталмаған өзгеріс бар» честно показывал, что
    текст не сохранён, и ничего с этим не делал: сохранить мог только сам
    автор, нажав кнопку. Теперь черновик доезжает до сервера сам."""

    SLUG = 'aidana-kus'      # NotPublished — своя работа Айданы

    def setUp(self):
        super().setUp()
        login_as(self.client)

    def _url(self, chapter=None):
        if chapter is None:
            return reverse('core:chapter_autosave_new', kwargs={'slug': self.SLUG})
        return reverse('core:chapter_autosave',
                       kwargs={'slug': self.SLUG, 'chapter': chapter})

    def test_it_creates_the_chapter_and_names_its_number(self):
        """`pk` в ответе обязателен (BR-83): без него редактор писал бы
        снова по адресу новой главы и заводил вторую на каждом
        автосохранении."""
        r = self.client.post(self._url(), {'title': '', 'body': 'Жаза бастадым'})
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertTrue(payload['ok'])
        story = Story.objects.get(slug=self.SLUG)
        chapter = story.chapter_set.get(number=1)
        self.assertEqual(payload['chapter'], chapter.pk)
        self.assertIn(f'/chapter/{chapter.pk}/autosave/', payload['autosave_url'])
        self.assertEqual(chapter.body, 'Жаза бастадым')

    def test_a_second_autosave_updates_the_same_chapter(self):
        self.client.post(self._url(), {'title': '', 'body': 'Бірінші нұсқа'})
        chapter_id = Story.objects.get(slug=self.SLUG).chapter_set.get(number=1).pk
        self.client.post(self._url(chapter_id), {'title': '', 'body': 'Екінші нұсқа'})
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.chapter_set.count(), 1)
        self.assertEqual(story.chapter_set.get(number=1).body, 'Екінші нұсқа')

    def test_an_unfinished_title_is_not_an_error(self):
        """Посреди набора пустой заголовок — состояние, а не ошибка:
        требовать законченности каждые три секунды нельзя."""
        r = self.client.post(self._url(), {'title': '', 'body': 'Мәтін'})
        self.assertTrue(r.json()['ok'])

    def test_it_does_not_touch_the_poll(self):
        """Автосохранение шлёт только текст. Затирать опрос содержимым
        полей, которых на экране может не быть, оно не вправе."""
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}), {
                'title': '1-бөлім', 'body': 'Мәтін.', 'action': 'draft',
                'poll_question': 'Кім жеңеді?', 'poll_option': ['Бірі', 'Екіншісі']})
        chapter_id = Story.objects.get(slug=self.SLUG).chapter_set.get(number=1).pk
        self.client.post(self._url(chapter_id), {'title': '1-бөлім', 'body': 'Жаңа мәтін'})
        chapter = Story.objects.get(slug=self.SLUG).chapter_set.get(number=1)
        self.assertEqual(chapter.body, 'Жаңа мәтін')
        self.assertEqual(chapter.poll.question, 'Кім жеңеді?')
        self.assertEqual(chapter.poll.option_set.count(), 2)

    def test_a_public_work_may_autosave_without_showing_anything(self):
        """Ограничение снято разделением ревизий (BR-79): автосохранение
        пишет рабочую копию, которой читатель не видит. Раньше оно было
        запрещено публичной работе, потому что записанная глава уходила
        читателю немедленно."""
        public = factories.story(author=user('aidana'), status='OnProcess',
                                 format='serial', chapters=1)
        r = self.client.post(
            reverse('core:chapter_autosave_new', kwargs={'slug': public.slug}),
            {'title': '', 'body': 'Аяқталмаған жаңа бөлім'})
        self.assertTrue(r.json()['ok'])
        self.assertEqual(public.chapter_set.count(), 2)
        # И читателю новой главы по-прежнему нет.
        self.assertEqual(len(data.chapters_of(public.slug)), 1)

    def test_a_foreign_story_is_not_found(self):
        foreign = Story.objects.exclude(author__username='aidana').first()
        r = self.client.post(
            reverse('core:chapter_autosave_new', kwargs={'slug': foreign.slug}),
            {'title': '', 'body': 'Бөтен мәтін'})
        self.assertEqual(r.status_code, 404)

    def test_a_guest_is_sent_to_the_door(self):
        guest = Client()
        r = guest.post(self._url(), {'title': '', 'body': 'Мәтін'})
        self.assertEqual(r.status_code, 302)
        self.assertIn('/auth/login/', r['Location'])

    def test_get_is_not_a_way_to_save(self):
        self.assertEqual(self.client.get(self._url()).status_code, 405)

    def test_the_editor_carries_the_autosave_address_and_the_switch(self):
        r = self.client.get(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}))
        self.assertContains(r, self._url())
        self.assertContains(r, 'enabled: true')
        self.assertContains(r, 'js/editor.js')

    def test_a_public_editor_has_the_switch_on_too(self):
        public = factories.story(author=user('aidana'), status='OnProcess',
                                 format='serial', chapters=1)
        r = self.client.get(
            reverse('core:chapter_new', kwargs={'slug': public.slug}))
        self.assertContains(r, 'enabled: true')


class ChapterEditorSubmitsForReview(TestCase):

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)

    def test_incomplete_checklist_keeps_the_draft(self):
        # 'aidana-kus' без жас белгісі — чек-лист толық емес БЖ.
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
            {'title': '1-бөлім', 'body': 'Мәтін.', 'action': 'submit_review'})
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.status, 'NotPublished')
        self.assertTrue(story.has_chapters)  # глава при этом сохранилась

    def test_complete_checklist_sends_it_to_moderation(self):
        Story.objects.filter(slug=self.SLUG).update(audience='10+')
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
            {'title': '1-бөлім', 'body': 'Мәтін.', 'action': 'submit_review'})
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.status, 'OnModeration')


class ManageStorySubmitsForReview(TestCase):

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)

    def test_post_without_a_ready_checklist_keeps_the_draft(self):
        r = self.client.post(reverse('core:manage_story', kwargs={'slug': self.SLUG}))
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.status, 'NotPublished')
        self.assertRedirects(
            r, reverse('core:manage_story', kwargs={'slug': self.SLUG}))

    def test_post_with_a_ready_checklist_sends_it_to_moderation(self):
        story = Story.objects.get(slug=self.SLUG)
        story.audience = '10+'
        story.save(update_fields=['audience'])
        Chapter.objects.create(story=story, number=1, title='1-бөлім', body='Мәтін бар.')
        self.client.post(reverse('core:manage_story', kwargs={'slug': self.SLUG}))
        story.refresh_from_db()
        self.assertEqual(story.status, 'OnModeration')


class ModerationIsPerChapterNotPerWork(TestCase):
    """BR-79 — то, ради чего заведены ревизии.

    До них одобрение выдавалось работе один раз и дальше не значило
    ничего: вторая глава публичного сериала появлялась у читателя в момент
    сохранения, а переписанный одобренный текст — тем же движением. То
    есть модерация фактически отсутствовала у всего длинного контента
    (C1/C2 в AUDIT-WRITE-FLOW).
    """

    def setUp(self):
        super().setUp()
        self.author = login_as_newcomer(self.client, 'revisions_author')
        self.reader = Client()
        self.serial = factories.story(
            author=self.author, status='OnProcess', format='serial',
            chapters=1, slug='revisions-serial')

    def _reader_sees(self, chapter_number=None):
        url = reverse('core:story_detail', kwargs={'slug': self.serial.slug})
        if chapter_number:
            url = f'{url}?chapter={chapter_number}'
        return self.reader.get(url).content.decode()

    # ── C1: новая глава ──────────────────────────────────────────────────
    def test_a_new_chapter_waits_for_the_moderator(self):
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.serial.slug}),
            {'title': 'Екінші бөлім', 'body': 'ТЕКСЕРІЛМЕГЕН МӘТІН',
             'action': 'draft'})
        self.serial.refresh_from_db()
        self.assertEqual(self.serial.chapter_set.count(), 2)
        self.assertNotIn('ТЕКСЕРІЛМЕГЕН МӘТІН', self._reader_sees(2))
        self.assertEqual(len(data.chapters_of(self.serial.slug)), 1)
        # И работа не ушла из каталога: опубликованное осталось на месте.
        self.assertEqual(self.serial.status, 'OnProcess')

    def test_the_chapter_appears_only_after_approval(self):
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.serial.slug}),
            {'title': 'Екінші бөлім', 'body': 'ТЕКСЕРІЛГЕН МӘТІН',
             'action': 'submit_review'})
        self.assertNotIn('ТЕКСЕРІЛГЕН МӘТІН', self._reader_sees(2))

        self.serial.refresh_from_db()
        self.serial.apply_moderation('approved')
        self.assertIn('ТЕКСЕРІЛГЕН МӘТІН', self._reader_sees(2))
        self.assertEqual(len(data.chapters_of(self.serial.slug)), 2)

    # ── C2: правка одобренного ───────────────────────────────────────────
    def test_rewriting_an_approved_chapter_does_not_reach_the_reader(self):
        first = self.serial.chapter_set.get(number=1)
        published_before = first.published_revision_id

        self.client.post(
            reverse('core:chapter_edit',
                    kwargs={'slug': self.serial.slug, 'chapter': first.pk}),
            {'title': first.title, 'body': 'ТҮГЕЛ АУЫСТЫРЫЛҒАН МӘТІН',
             'action': 'submit_review'})

        first.refresh_from_db()
        self.assertEqual(first.body, 'ТҮГЕЛ АУЫСТЫРЫЛҒАН МӘТІН')  # рабочая копия
        self.assertEqual(first.published_revision_id, published_before)
        self.assertNotIn('ТҮГЕЛ АУЫСТЫРЫЛҒАН МӘТІН', self._reader_sees(1))

        self.serial.refresh_from_db()
        self.serial.apply_moderation('approved')
        first.refresh_from_db()
        self.assertNotEqual(first.published_revision_id, published_before)
        self.assertIn('ТҮГЕЛ АУЫСТЫРЫЛҒАН МӘТІН', self._reader_sees(1))

    # ── Отказ не уносит опубликованное ───────────────────────────────────
    def test_a_returned_chapter_leaves_the_published_ones_alone(self):
        """Прежний исход назначал `NotPublished` любому отказу — и публичный
        сериал, чью новую главу вернули, исчезал из каталога целиком."""
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.serial.slug}),
            {'title': 'Екінші бөлім', 'body': 'Шикі мәтін.',
             'action': 'submit_review'})
        self.serial.refresh_from_db()
        self.serial.apply_moderation('needs_work', 'Соңы жоқ.')

        self.serial.refresh_from_db()
        self.assertEqual(self.serial.status, 'OnProcess')
        self.assertTrue(self.serial.is_public)
        self.assertEqual(len(data.chapters_of(self.serial.slug)), 1)
        # Рабочая копия автора при этом цела — править есть что.
        self.assertEqual(self.serial.chapter_set.get(number=2).body,
                         'Шикі мәтін.')

    # ── V10: правка во время очереди ─────────────────────────────────────
    def test_editing_while_queued_replaces_what_was_submitted(self):
        """Автор правил текст после отправки, и модератор читал не то, что
        ему прислали. Вторая заявка при этом не заводится."""
        first_id = self.serial.chapter_set.get(number=1).pk
        url = reverse('core:chapter_edit',
                      kwargs={'slug': self.serial.slug, 'chapter': first_id})
        self.client.post(url, {'title': '1-бөлім', 'body': 'Бірінші нұсқа.',
                               'action': 'submit_review'})
        self.client.post(url, {'title': '1-бөлім', 'body': 'Түзетілген нұсқа.',
                               'action': 'submit_review'})

        first = self.serial.chapter_set.get(number=1)
        pending = [r for r in first.revisions.all() if r.state == 'pending']
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].body, 'Түзетілген нұсқа.')

    # ── S10: история ─────────────────────────────────────────────────────
    def test_every_version_stays_in_history(self):
        """Перезаписи больше нет: у главы копятся ревизии, и потерянного
        текста, который нечем восстановить, не остаётся."""
        first = self.serial.chapter_set.get(number=1)
        url = reverse('core:chapter_edit',
                      kwargs={'slug': self.serial.slug, 'chapter': first.pk})
        for text in ('Бірінші түзету.', 'Екінші түзету.'):
            self.client.post(url, {'title': '1-бөлім', 'body': text,
                                   'action': 'submit_review'})
            self.serial.refresh_from_db()
            self.serial.apply_moderation('approved')

        bodies = [r.body for r in first.revisions.all()]
        self.assertIn('Бірінші түзету.', bodies)
        self.assertIn('Екінші түзету.', bodies)
        self.assertEqual(first.revisions.filter(state='approved').count(), 3)


class ReturnedWorkKnowsItWasReturned(TestCase):
    """BR-80/BR-81. Возврат «на доработку» не оставлял следа: работа падала
    в черновики, чек-лист снова горел зелёным, кнопка отправки была
    активна, и единственный экземпляр причины лежал в ленте уведомлений —
    автор должен был помнить её наизусть, пока правит (S1)."""

    def setUp(self):
        super().setUp()
        self.author = login_as_newcomer(self.client, 'returned_author')
        self.story = factories.story(
            author=self.author, chapters=1, format='single',
            slug='returned-work', published=False)
        factories.submit(self.story)
        self.story.refresh_status()

    def _manage(self):
        return self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.story.slug}))

    def test_the_reason_stays_on_the_working_screen(self):
        self.story.apply_moderation('needs_work', 'Диалогтар үзіліп қалған.')
        response = self._manage()
        self.assertContains(response, 'Диалогтар үзіліп қалған.')
        self.assertContains(response, 'Толықтыру қажет')
        self.story.refresh_from_db()
        self.assertEqual(self.story.status, 'NeedsWork')

    def test_the_reason_goes_away_once_it_was_resubmitted(self):
        """Замечание — про прошлую версию: после повторной подачи оно уже
        не про то, что лежит у модератора."""
        self.story.apply_moderation('needs_work', 'Соңы жоқ.')
        chapter = self.story.chapter_set.first()
        chapter.body += ' Соңы жазылды.'
        chapter.save()
        self.client.post(reverse('core:manage_story',
                                 kwargs={'slug': self.story.slug}))
        self.assertNotContains(self._manage(), 'Соңы жоқ.')

    def test_a_returned_work_is_told_apart_from_an_untouched_draft(self):
        untouched = factories.story(author=self.author, chapters=1,
                                    format='single', published=False,
                                    slug='untouched-draft')
        untouched.refresh_status()
        self.story.apply_moderation('needs_work', 'Түзет.')

        self.story.refresh_from_db()
        untouched.refresh_from_db()
        self.assertEqual(self.story.status, 'NeedsWork')
        self.assertEqual(untouched.status, 'NotPublished')

        listing = self.client.get(reverse('core:my_stories'))
        self.assertContains(listing, 'толықтыруды күтеді')

    def test_a_public_serial_stays_public_when_a_chapter_is_returned(self):
        """`NeedsWork` — только у непубличного: увести работу из каталога
        значит наказать читателя за то, чего он не видел."""
        serial = factories.story(author=self.author, chapters=1,
                                 format='serial', status='OnProcess',
                                 slug='public-returned')
        factories.chapter(serial, number=2, chars=300)
        factories.submit(serial)
        serial.refresh_status()
        serial.apply_moderation('needs_work', 'Екінші бөлім шикі.')

        serial.refresh_from_db()
        self.assertEqual(serial.status, 'OnProcess')
        self.assertTrue(serial.is_public)


class TheAuthorMayTakeTheSubmissionBack(TestCase):
    """BR-80 (S2). Кнопки отзыва не было вовсе: заметив опечатку через
    минуту после отправки, автор мог только ждать модератора."""

    def setUp(self):
        super().setUp()
        self.author = login_as_newcomer(self.client, 'withdraw_author')
        self.story = factories.story(
            author=self.author, chapters=1, format='single',
            slug='withdraw-work', published=False)
        self.url = reverse('core:manage_story',
                           kwargs={'slug': self.story.slug})
        self.client.post(self.url)          # отправили на модерацию

    def test_the_queue_shows_the_button_and_how_long_it_waits(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Мәтін модераторда')
        self.assertContains(response, 'Өтінімді кері қайтару')

    def test_withdrawing_empties_the_queue_without_losing_the_text(self):
        self.client.post(self.url, {'action': 'withdraw'})
        self.story.refresh_from_db()
        self.assertIsNone(data.pending_review_since(self.story))
        self.assertEqual(self.story.status, 'NotPublished')
        # Снимок остаётся историей, а не исчезает вместе с заявкой.
        chapter = self.story.chapter_set.first()
        self.assertEqual(chapter.revisions.count(), 1)
        self.assertEqual(chapter.revisions.first().state, 'draft')
        self.assertTrue(chapter.body)
        # И подать снова можно сразу.
        self.assertTrue(data.can_submit_for_review(self.story))

    def test_a_withdrawn_work_is_out_of_the_moderator_queue(self):
        self.client.post(self.url, {'action': 'withdraw'})
        self.story.refresh_from_db()
        with self.assertRaises(ValueError):
            self.story.apply_moderation('approved')


class TheRefusalNamesWhatIsMissing(TestCase):
    """BR-81 (S3). Сообщение перечисляло причины на память — «аннотация
    мен жас белгісі», — и врало всякий раз, когда не хватало текста."""

    def setUp(self):
        super().setUp()
        self.author = login_as_newcomer(self.client, 'refusal_author')

    def test_it_names_the_missing_items_in_words(self):
        bare = factories.story(author=self.author, chapters=0,
                               format='serial', published=False,
                               annotation='', audience='', slug='bare-work')
        response = self.client.post(
            reverse('core:manage_story', kwargs={'slug': bare.slug}),
            follow=True)
        text = ' '.join(m.message for m in response.context['messages'])
        self.assertIn('Алғашқы бөлімді жаз', text)
        self.assertIn('Аннотация жаз', text)
        self.assertIn('Жас белгісін қой', text)

    def test_the_panel_and_the_message_speak_the_same_words(self):
        """Один список подписей: разойдясь, они снова стали бы врать."""
        bare = factories.story(author=self.author, chapters=0,
                               format='single', published=False,
                               annotation='', audience='', slug='bare-single')
        panel = self.client.get(
            reverse('core:manage_story', kwargs={'slug': bare.slug}))
        for label in data.missing_labels(bare):
            with self.subTest(label=label):
                self.assertContains(panel, label)
        # У одночастной работы «бөлім» не предлагают — их у неё нет.
        self.assertIn('Мәтін жаз', data.missing_labels(bare))


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
        # вошедшего это настоящий 404 (BR-89), а auth_gate остаётся у гостя.
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
        """S5/BR-83: адрес кабинета — `pk`, но `pk` чужой главы своей
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


class ChapterAddressIsAStableIdNotItsNumber(TestCase):
    """S5 (AUDIT-WRITE-FLOW.md): кабинет адресует главу `pk` (BR-83).
    Раньше GET на несуществующий номер рисовал пустой «новый» редактор, а
    POST по тому же адресу заводил главу с этим самым номером — дыру в
    нумерации."""

    def setUp(self):
        self.author = login_as_newcomer(self.client, 'stable_id_author')
        self.story = factories.story(author=self.author, chapters=1,
                                     format='serial', published=False,
                                     slug='stable-id-work')

    def test_an_unknown_chapter_id_is_not_found(self):
        missing_id = Chapter.objects.order_by('-pk').first().pk + 1000
        r = self.client.get(reverse(
            'core:chapter_edit', kwargs={'slug': self.story.slug, 'chapter': missing_id}))
        self.assertEqual(r.status_code, 404)

    def test_posting_to_an_unknown_chapter_id_does_not_create_one(self):
        missing_id = Chapter.objects.order_by('-pk').first().pk + 1000
        before = self.story.chapter_set.count()
        self.client.post(
            reverse('core:chapter_edit',
                    kwargs={'slug': self.story.slug, 'chapter': missing_id}),
            {'title': 'Аты', 'body': 'Мәтіні осында', 'action': 'draft'})
        self.assertEqual(self.story.chapter_set.count(), before)


class SingleFormatCapsAtOneChapter(TestCase):
    """S6 (AUDIT-WRITE-FLOW.md, BR-85): обратный переход формата запрещала
    только форма настроек — прямой `/chapter/new/` был открыт всегда и
    заводил `single`-работе вторую главу в обход интерфейса."""

    def setUp(self):
        self.author = login_as_newcomer(self.client, 'single_cap_author')
        self.story = factories.story(author=self.author, chapters=1,
                                     format='single', published=False,
                                     slug='single-cap-work')

    def test_a_direct_get_redirects_to_the_existing_chapter(self):
        r = self.client.get(
            reverse('core:chapter_new', kwargs={'slug': self.story.slug}))
        self.assertRedirects(r, reverse(
            'core:chapter_edit',
            kwargs={'slug': self.story.slug, 'chapter': self.story.text_chapter}))

    def test_a_direct_post_does_not_create_a_second_chapter(self):
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.story.slug}),
            {'title': 'Екінші мәтін', 'body': 'Мәтін.', 'action': 'draft'})
        self.assertEqual(self.story.chapter_set.count(), 1)

    def test_autosave_writes_into_the_existing_chapter_too(self):
        self.client.post(
            reverse('core:chapter_autosave_new', kwargs={'slug': self.story.slug}),
            {'title': '', 'body': 'Жаңа нұсқа'})
        self.assertEqual(self.story.chapter_set.count(), 1)
        self.assertEqual(self.story.chapter_set.get().body, 'Жаңа нұсқа')


class ChaptersCanBeDeletedAndReordered(TestCase):
    """M3 (AUDIT-WRITE-FLOW.md, BR-84): ни удаления, ни перестановки не
    было вовсе — таких маршрутов в `urls.py` не было."""

    def setUp(self):
        self.author = login_as_newcomer(self.client, 'reorder_author')
        self.story = factories.story(author=self.author, chapters=3,
                                     format='serial', published=False,
                                     slug='reorder-work')
        self.chapters = list(self.story.chapter_set.order_by('number'))

    def test_deleting_a_chapter_closes_the_gap_in_numbering(self):
        middle = self.chapters[1]
        r = self.client.post(reverse(
            'core:chapter_delete',
            kwargs={'slug': self.story.slug, 'chapter': middle.pk}))
        self.assertRedirects(r, reverse(
            'core:manage_story', kwargs={'slug': self.story.slug}))
        self.assertEqual(self.story.chapter_set.count(), 2)
        remaining = list(self.story.chapter_set.order_by('position'))
        self.assertEqual([c.number for c in remaining], [1, 2])
        self.assertEqual([c.pk for c in remaining],
                         [self.chapters[0].pk, self.chapters[2].pk])

    def test_deleting_the_last_chapter_returns_the_work_to_draft(self):
        for c in self.chapters:
            self.client.post(reverse(
                'core:chapter_delete', kwargs={'slug': self.story.slug, 'chapter': c.pk}))
        self.story.refresh_from_db()
        self.assertEqual(self.story.chapter_set.count(), 0)
        self.assertEqual(self.story.status, 'NotPublished')

    def test_moving_a_chapter_down_swaps_it_with_its_neighbor(self):
        first = self.chapters[0]
        self.client.post(
            reverse('core:chapter_move',
                    kwargs={'slug': self.story.slug, 'chapter': first.pk}),
            {'direction': 'down'})
        ordered = list(self.story.chapter_set.order_by('position'))
        self.assertEqual([c.pk for c in ordered],
                         [self.chapters[1].pk, self.chapters[0].pk, self.chapters[2].pk])
        self.assertEqual([c.number for c in ordered], [1, 2, 3])

    def test_moving_the_first_chapter_up_is_a_no_op(self):
        first = self.chapters[0]
        r = self.client.post(
            reverse('core:chapter_move',
                    kwargs={'slug': self.story.slug, 'chapter': first.pk}),
            {'direction': 'up'})
        self.assertEqual(r.status_code, 302)
        ordered = list(self.story.chapter_set.order_by('position'))
        self.assertEqual([c.pk for c in ordered], [c.pk for c in self.chapters])

    def test_a_guest_cannot_delete_or_move(self):
        guest = Client()
        chapter = self.chapters[0]
        for name in ('core:chapter_delete', 'core:chapter_move'):
            r = guest.post(reverse(
                name, kwargs={'slug': self.story.slug, 'chapter': chapter.pk}))
            self.assertEqual(r.status_code, 302)
            self.assertIn('/auth/login/', r['Location'])
        self.assertEqual(self.story.chapter_set.count(), 3)

    def test_deleting_a_chapter_detaches_its_comments_instead_of_relabeling(self):
        """Комментарий швартуется к номеру (`StoryComment.chapter_number`),
        не к `pk` главы. Без пересчёта удаление второй из трёх глав отдало
        бы её номер прежней третьей — и комментарий про удалённый текст
        читался бы как комментарий про чужой, занявший освободившийся
        номер."""
        about_first = factories.comment(self.story, chapter_number=1)
        about_deleted = factories.comment(self.story, chapter_number=2)
        about_last = factories.comment(self.story, chapter_number=3)
        middle = self.chapters[1]

        self.client.post(reverse(
            'core:chapter_delete',
            kwargs={'slug': self.story.slug, 'chapter': middle.pk}))

        about_first.refresh_from_db()
        about_deleted.refresh_from_db()
        about_last.refresh_from_db()
        self.assertEqual(about_first.chapter_number, 1)
        self.assertIsNone(about_deleted.chapter_number)
        self.assertEqual(about_last.chapter_number, 2)

    def test_moving_a_chapter_carries_its_comments_along(self):
        """Перестановка меняет номера местами — комментарий обязан
        переехать вместе со своей главой, а не остаться на номере."""
        about_first = factories.comment(self.story, chapter_number=1)
        about_second = factories.comment(self.story, chapter_number=2)
        first = self.chapters[0]

        self.client.post(
            reverse('core:chapter_move',
                    kwargs={'slug': self.story.slug, 'chapter': first.pk}),
            {'direction': 'down'})

        about_first.refresh_from_db()
        about_second.refresh_from_db()
        self.assertEqual(about_first.chapter_number, 2)
        self.assertEqual(about_second.chapter_number, 1)
