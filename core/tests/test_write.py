"""WRITE: авторский кабинет — my_stories, new, manage, settings, chapter_editor."""

import re

from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.urls import reverse

from core import data
from core.models import Chapter, Story, Tag
from core.tests.base import login_as, login_as_newcomer, user
from core.templatetags.balaproza import spaced


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
        self.assertContains(self.response,
                            data.story_by_slug('aidana-tan').updated_label)

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
            f"{data.story_by_slug('aidana-erteg').updated_days_ago} күн тексеруде")
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
                    self.assertIsNotNone(data.story_by_slug(item['slug']))

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
        self.assertContains(unknown, 'Шығарма табылмады')
        self.assertNotContains(unknown, '<aside')

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
                    + stats['on_moderation'] + stats['draft'],
                    stats['total'])
        buckets = ('Published', 'Completed', 'OnProcess',
                   'OnModeration', 'NotPublished')
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
        self.assertContains(manage, reverse(
            'core:chapter_edit', kwargs={'slug': 'aidana-koshe', 'chapter': 1}))
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
                    kwargs={'slug': self.SLUG, 'chapter': chapter.number}))
        for route in ('core:chapter_new', 'core:story_settings', 'core:story_detail'):
            self.assertContains(response, reverse(route, kwargs={'slug': self.SLUG}))
        self.assertContains(response, 'open-delete-confirm')

    def test_a_work_without_chapters_says_so_and_an_unknown_one_is_not_found(self):
        login_as(self.client)
        self.assertContains(
            self.client.get(reverse('core:manage_story',
                                    kwargs={'slug': 'aidana-erteg'})),
            'Әлі бөлім жоқ')
        self.assertContains(
            self.client.get(reverse('core:manage_story',
                                    kwargs={'slug': 'no-such-story'})),
            'Шығарма табылмады')


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
        for item in data.publish_checklist(data.story_by_slug('aidana-kus')):
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

    def test_it_is_honest_about_the_age_mark_and_about_what_is_optional(self):
        """Обложка и теги улучшают карточку, но не держат публикацию."""
        self.assertEqual(data.story_by_slug('aidana-kus').audience, '')
        self.assertContains(
            self.client.get(reverse('core:manage_story',
                                    kwargs={'slug': 'aidana-kus'})),
            'Жас белгісін қой')
        marked = data.story_by_slug('aidana-tan')
        self.assertContains(
            self.client.get(reverse('core:manage_story',
                                    kwargs={'slug': 'aidana-tan'})),
            f'Жас белгісі: {marked.audience}')
        required = {i['key'] for i in data.publish_checklist(
            data.story_by_slug('aidana-kus')) if i['required']}
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
        draft = data.story_by_slug('aidana-kus')
        self.assertFalse(data.can_submit_for_review(draft))
        self.assertEqual(data.missing_for_review(draft), ['text', 'audience'])
        response = self._get('aidana-kus')
        self.assertFalse(response.context['can_submit'])
        self.assertContains(response, 'disabled')
        self.assertContains(response, 'Модерацияға жіберу')

    def test_a_work_that_already_left_the_drafts_sees_no_button(self):
        for slug in ('aidana-tan', 'aidana-erteg'):
            with self.subTest(story=slug):
                self.assertFalse(
                    data.can_submit_for_review(data.story_by_slug(slug)))
                self.assertNotContains(self._get(slug), 'Модерацияға жіберу')

    def test_readiness_and_status_are_asked_separately(self):
        """Проверяется чек-лист, а не запись: статус меняется в памяти,
        сохранять нечего."""
        ready = data.story_by_slug('aidana-tan')
        ready.status = 'NotPublished'
        self.assertEqual(data.missing_for_review(ready), [])
        self.assertTrue(data.can_submit_for_review(ready))
        ready.status = 'OnModeration'
        self.assertEqual(data.missing_for_review(ready), [])
        self.assertFalse(data.can_submit_for_review(ready))


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
        docs/ui.md отводит ему оттенок экзамена."""
        response = self.client.get(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}))
        body = response.content.decode()
        self.assertContains(response, 'Жаңа бөлім')
        self.assertContains(response, 'name="title"')
        self.assertContains(response, 'name="body"')
        self.assertContains(response, 'Жоба ретінде сақтау')
        self.assertIn('Модерацияға жіберу', body)
        self.assertNotIn('Тексеруге жіберу', body)

    def test_the_counter_counts_typing_and_the_actions_stay_in_view(self):
        """Статичное `{{ current.char_count }}` не двигалось при вводе,
        хотя соседняя аннотация считала живьём — две механики одного и
        того же на одном экране. `bottom-24` разводит панель с плавающей
        пилюлей `mobile_nav` (docs/ui.md)."""
        body = self.client.get(reverse(
            'core:chapter_new', kwargs={'slug': self.SLUG})).content.decode()
        self.assertIn('x-text="count"', body)
        self.assertIn('count = $event.target.value.length', body)
        self.assertIn('sticky bottom-24', body)
        self.assertIn('md:bottom-0', body)

    def test_saved_state_is_server_truth_not_a_timer(self):
        """На новой главе «Жоба сақталды» не должно быть вовсе: сообщать о
        сохранении того, что ни разу не сохранялось, — та же ложь, что
        рисовал прежний фейковый submit."""
        fresh = self.client.get(reverse(
            'core:chapter_new', kwargs={'slug': self.SLUG})).content.decode()
        self.assertIn('dirty: false', fresh)
        self.assertIn('@input="dirty = true"', fresh)
        self.assertIn('Сақталмаған өзгеріс бар', fresh)
        self.assertNotIn('Жоба сақталды', fresh)
        self.assertNotIn('setInterval', fresh)

        existing = self.client.get(reverse(
            'core:chapter_edit', kwargs={'slug': self.SLUG, 'chapter': 1}))
        self.assertContains(existing, 'Жоба сақталды')
        self.assertContains(existing,
                            f'value="{data.chapter_of(self.SLUG, 1).title}"')
        self.assertContains(existing, 'Бірде ерте таңда')

    def test_an_unknown_work_has_no_editor(self):
        self.assertContains(
            self.client.get(reverse('core:chapter_new',
                                    kwargs={'slug': 'no-such-story'})),
            'Шығарма табылмады')


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

    def test_missing_required_field_creates_nothing(self):
        before = Story.objects.count()
        r = self.client.post(reverse('core:new_story'), {
            'title': '', 'format': 'serial', 'genre_primary': self.genre.slug,
        })
        self.assertEqual(Story.objects.count(), before)
        self.assertRedirects(r, reverse('core:new_story'))

    def test_guest_post_creates_nothing(self):
        guest = Client()
        before = Story.objects.count()
        guest.post(reverse('core:new_story'), {
            'title': 'Қонақтың шығармасы', 'format': 'serial',
            'genre_primary': self.genre.slug,
        })
        self.assertEqual(Story.objects.count(), before)


class StorySettingsSavesFields(TestCase):

    SLUG = 'aidana-kus'  # NotPublished, 0 бөлім, audience='' — aidana-нікі

    def setUp(self):
        login_as(self.client)
        self.genre = data.all_genres()[0]

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
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.title, 'Жаңа атау')
        self.assertEqual(story.annotation, 'Жаңа аннотация мәтіні.')
        self.assertEqual(story.audience, '10+')
        self.assertRedirects(
            r, reverse('core:story_settings', kwargs={'slug': self.SLUG}))

    def test_missing_title_saves_nothing(self):
        self._post(title='')
        story = Story.objects.get(slug=self.SLUG)
        self.assertNotEqual(story.title, '')
        self.assertNotEqual(story.audience, '10+')

    def test_cannot_switch_to_single_with_more_than_one_chapter(self):
        story = Story.objects.get(slug=self.SLUG)
        Chapter.objects.create(story=story, number=1, title='1', body='т')
        Chapter.objects.create(story=story, number=2, title='2', body='т')
        self._post(format='single')
        story.refresh_from_db()
        self.assertEqual(story.format, 'serial')

    def test_status_field_outside_the_allowed_set_is_ignored(self):
        # 'aidana-kus' — черновик, радио «Мәртебесі» на этой странице у
        # него вообще не рендерится (BR-10a) — POST в обход формы не
        # должен провести статус мимо модерации.
        self._post(status='Published')
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.status, 'NotPublished')


class StorySettingsCoverUpload(TestCase):
    """Тот же валидатор, что у User.avatar (BR-46) — SVG не проходит.

    `story.cover = cover; story.save()` — прямое присваивание, не
    ModelForm, поэтому `RASTER_ONLY` не срабатывает сам по себе (тот же
    пробел, что был у `avatar` до Ф15 Этапа 6) — закрыто явным вызовом
    во view.
    """

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)
        self.genre = data.all_genres()[0]

    def _post(self, **overrides):
        payload = {
            'title': 'Жаңа атау', 'annotation': 'Жаңа аннотация мәтіні.',
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
        cover = SimpleUploadedFile('мұқаба.png', b'\x89PNG demo',
                                   content_type='image/png')
        self._post(cover=cover)
        story = Story.objects.get(slug=self.SLUG)
        self.assertTrue(story.cover.name.startswith(f'covers/{self.SLUG}'))


class StorySettingsTagResolution(TestCase):

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)
        self.genre = data.all_genres()[0]

    def _post(self, tags):
        return self.client.post(
            reverse('core:story_settings', kwargs={'slug': self.SLUG}),
            {'title': 'Атау', 'annotation': 'Аннотация.', 'format': 'serial',
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
            'core:chapter_edit', kwargs={'slug': self.SLUG, 'chapter': 1}))

    def test_empty_body_saves_nothing(self):
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
            {'title': '1-бөлім', 'body': '  ', 'action': 'draft'})
        story = Story.objects.get(slug=self.SLUG)
        self.assertEqual(story.chapter_set.count(), 0)

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
        self.assertEqual(story.chapters, 3)
        self.assertEqual(story.reading_meta_label, '3 бөлім')

        from_feed = next(s for s in data.my_stories_of(user('aidana'))
                         if s.slug == self.SLUG)
        self.assertEqual(from_feed.chapters, 3)

    def test_editing_an_existing_chapter_does_not_duplicate_it(self):
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}),
            {'title': '1-бөлім', 'body': 'Бастапқы мәтін.', 'action': 'draft'})
        self.client.post(
            reverse('core:chapter_edit', kwargs={'slug': self.SLUG, 'chapter': 1}),
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

    def test_a_single_option_does_not_create_a_poll(self):
        # BR-POLL-02: кемінде екі нұсқа — біреуімен таңдау мағынасыз.
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.SLUG}), {
                'title': '1-бөлім', 'body': 'Мәтін.', 'action': 'draft',
                'poll_question': 'Сұрақ?', 'poll_option': ['Жалғыз нұсқа'],
            })
        chapter = Story.objects.get(slug=self.SLUG).chapter_set.get(number=1)
        self.assertFalse(hasattr(chapter, 'poll'))


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

    def test_manage_story_of_a_foreign_slug_shows_not_found(self):
        r = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.foreign.slug}))
        self.assertContains(r, 'Шығарма табылмады')

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
