"""WRITE — настройки работы: что автор может о ней сказать.

Форма предлагает ровно то, что менять можно: жас белгісі выбирается
автором и не ставится за него, а название непубличной работы двигает
слаг вместе с собой — у публичной адрес уже роздан и не меняется.

Чек-лист ведёт к полю, которого не хватает, а не сообщает о нехватке:
«не готово» без адреса — это тупик.

Отказ по обложке — самая дорогая ошибка страницы: вместе с файлом она
уносила аннотацию, отметку и теги, то есть всё набранное.
"""


import re

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from core import data
from core.models import Chapter, Story, Tag
from core.tests import factories
from core.tests.base import login_as, user


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


class TheSettingsDrawerLoadsViaHtmx(TestCase):
    """11.3 (AUDIT-WRITE-FLOW): баптаулар — выезжающая панель поверх
    рабочего места. `StorySettingsForm`/`update_story_settings` не
    тронуты — меняется только транспорт (HX-Request), не форма."""

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)
        self.genre = data.all_genres()[0]
        self.pk = Story.objects.get(slug=self.SLUG).pk

    def test_the_trigger_link_opens_the_drawer_and_loads_it(self):
        response = self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.SLUG}))
        settings_url = reverse('core:story_settings', kwargs={'slug': self.SLUG})
        self.assertContains(response, "$dispatch('open-settings-drawer')")
        self.assertContains(response, f'hx-get="{settings_url}"')
        self.assertContains(response, 'hx-target="#settings-drawer-body"')

    def test_hx_request_returns_only_the_form_not_the_full_page(self):
        """Полный показ несёт брэдкрамб и `<h1>`; фрагмент — только форму
        (плюс мини-шапка с названием и статусом)."""
        full = self.client.get(
            reverse('core:story_settings', kwargs={'slug': self.SLUG}))
        self.assertContains(full, 'Менің шығармаларым')

        fragment = self.client.get(
            reverse('core:story_settings', kwargs={'slug': self.SLUG}),
            HTTP_HX_REQUEST='true')
        self.assertContains(fragment, 'name="title"')
        self.assertContains(fragment, 'hx-target="#settings-drawer-body"')
        self.assertNotContains(fragment, 'Менің шығармаларым')

    def test_hx_success_closes_the_drawer_with_a_refresh_not_a_redirect(self):
        """Успех отвечает `HX-Refresh`, а не редиректом (BR-77-совместимо):
        htmx перезагружает текущую страницу рабочего места целиком —
        адрес в браузере и не был `/settings/`, панель туда не уводила."""
        r = self.client.post(
            reverse('core:story_settings', kwargs={'slug': self.SLUG}),
            {'title': 'Жаңа атау', 'annotation': 'Жаңа аннотация мәтіні.',
             'format': 'serial', 'genre_primary': self.genre.slug,
             'genre_secondary': '', 'audience': '10+', 'tags': ''},
            HTTP_HX_REQUEST='true')
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r['HX-Refresh'], 'true')
        self.assertEqual(Story.objects.get(pk=self.pk).title, 'Жаңа атау')

    def test_hx_rejected_form_redraws_the_fragment_not_a_redirect(self):
        """Отклонённая форма (BR-77) перерисовывает тот же фрагмент —
        панель остаётся открытой с набранным, а не закрывается и не
        уводит на отдельную страницу."""
        before = Story.objects.get(pk=self.pk).annotation
        r = self.client.post(
            reverse('core:story_settings', kwargs={'slug': self.SLUG}),
            {'title': '', 'annotation': 'Жазылған аннотация.',
             'format': 'serial', 'genre_primary': self.genre.slug,
             'genre_secondary': '', 'audience': '10+', 'tags': ''},
            HTTP_HX_REQUEST='true')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Атауын жаз.')
        self.assertContains(r, 'Жазылған аннотация.')
        self.assertEqual(Story.objects.get(pk=self.pk).annotation, before)


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
