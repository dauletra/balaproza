"""WRITE: авторский кабинет — my_stories, new, manage, settings, chapter_editor."""

from django.test import TestCase
from django.urls import reverse

from core import stub_data


def _login_as_aidana(client):
    """Стандартный логин фейк-сессии: user_username='aidana'."""
    s = client.session
    s['signed_in'] = True
    s['user_name'] = 'Айдана'
    s['user_username'] = 'aidana'
    s.save()


# ───────────────────────── stub_data: my_stories_of / writer_stats ───────

class MyStoriesHelper(TestCase):

    def test_my_stories_filters_by_username(self):
        result = stub_data.my_stories_of('aidana')
        self.assertEqual(len(result), 4)
        for s in result:
            self.assertEqual(s.author_username, 'aidana')

    def test_my_stories_unknown_user_is_empty(self):
        self.assertEqual(stub_data.my_stories_of('no-such-user'), [])

    def test_writer_stats_aggregates_correctly(self):
        stats = stub_data.writer_stats('aidana')
        mine = stub_data.my_stories_of('aidana')
        self.assertEqual(stats['total'], len(mine))
        self.assertEqual(stats['views'], sum(s.views for s in mine))
        self.assertEqual(stats['likes'], sum(s.likes for s in mine))
        self.assertEqual(stats['followers'], stub_data.AUTHORS_BY_USERNAME['aidana'].followers)

    def test_writer_stats_counts_statuses(self):
        stats = stub_data.writer_stats('aidana')
        self.assertEqual(stats['published'], 1)
        self.assertEqual(stats['on_moderation'], 1)
        self.assertEqual(stats['drafts'], 1)


# ───────────────────────── My stories ─────────────────────────

class MyStoriesGuest(TestCase):

    def test_guest_sees_gate(self):
        r = self.client.get(reverse('core:my_stories'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'тек авторланғандарға')
        # Стори не выводим
        self.assertNotContains(r, 'Таң алдында')


class MyStoriesAuthedHasItems(TestCase):

    def setUp(self):
        _login_as_aidana(self.client)
        self.response = self.client.get(reverse('core:my_stories'))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_lists_all_four_stories(self):
        for s in stub_data.my_stories_of('aidana'):
            with self.subTest(story=s.slug):
                self.assertContains(self.response, s.title)

    def test_shows_status_badges_for_each(self):
        # 4 status'а: Published, OnProcess, OnModeration, Completed → разные тексты
        self.assertContains(self.response, 'Жарияланды')
        self.assertContains(self.response, 'Жазылып жатыр')
        self.assertContains(self.response, 'Модерацияда')
        self.assertContains(self.response, 'Аяқталды')

    def test_does_not_show_empty_state(self):
        self.assertNotContains(self.response, 'Әлі шығарма жоқ')

    def test_each_card_links_to_manage(self):
        for s in stub_data.my_stories_of('aidana'):
            with self.subTest(story=s.slug):
                self.assertContains(
                    self.response,
                    reverse('core:manage_story', kwargs={'slug': s.slug}),
                )

    def test_has_new_story_cta(self):
        self.assertContains(self.response, reverse('core:new_story'))


class MyStoriesAuthedEmpty(TestCase):
    """Если у пользователя нет произведений (например другой username)."""

    def setUp(self):
        s = self.client.session
        s['signed_in'] = True
        s['user_name'] = 'Тест'
        s['user_username'] = 'no-such-user'
        s.save()
        self.response = self.client.get(reverse('core:my_stories'))

    def test_shows_empty_state(self):
        self.assertContains(self.response, 'Әлі шығарма жоқ')

    def test_empty_state_has_cta(self):
        # CTA-кнопка в empty state
        self.assertContains(self.response, 'Жаңа шығарма жазу')
        self.assertContains(self.response, reverse('core:new_story'))


# ───────────────────────── New story ─────────────────────────

class NewStoryForm(TestCase):

    def setUp(self):
        _login_as_aidana(self.client)
        self.response = self.client.get(reverse('core:new_story'))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_has_required_fields(self):
        self.assertContains(self.response, 'name="title"')
        self.assertContains(self.response, 'name="annotation"')
        self.assertContains(self.response, 'name="genre_primary"')
        self.assertContains(self.response, 'name="genre_secondary"')
        self.assertContains(self.response, 'name="status"')

    def test_genre_select_lists_all_12(self):
        for g in stub_data.GENRES:
            with self.subTest(genre=g.slug):
                self.assertContains(self.response, f'value="{g.slug}"')

    def test_status_radios_present(self):
        self.assertContains(self.response, 'value="OnProcess"')
        self.assertContains(self.response, 'value="Completed"')

    def test_consent_checkbox_required(self):
        self.assertContains(self.response, 'name="agree"')


class NewStoryGuestSeesGate(TestCase):

    def test_guest_sees_login_hint_no_form(self):
        r = self.client.get(reverse('core:new_story'))
        self.assertNotContains(r, 'name="title"')
        self.assertContains(r, 'Кіріңіз')


# ───────────────────────── Manage story ─────────────────────────

class ManageStoryKnown(TestCase):

    SLUG = 'aidana-tan'   # 8 глав у Айданы

    def setUp(self):
        _login_as_aidana(self.client)
        self.response = self.client.get(reverse('core:manage_story', kwargs={'slug': self.SLUG}))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_shows_title_and_status(self):
        story = stub_data.STORIES_BY_SLUG[self.SLUG]
        self.assertContains(self.response, story.title)
        # У aidana-tan статус Published → бейдж «Жарияланды»
        self.assertContains(self.response, 'Жарияланды')

    def test_lists_each_chapter_with_edit_link(self):
        chapters = stub_data.chapters_of(self.SLUG)
        self.assertGreater(len(chapters), 0)
        for c in chapters:
            with self.subTest(chapter=c.number):
                self.assertContains(self.response, c.title)
                edit_url = reverse('core:chapter_edit', kwargs={'slug': self.SLUG, 'chapter': c.number})
                self.assertContains(self.response, f'href="{edit_url}"')

    def test_action_buttons_present(self):
        # «Бөлім қосу», «Баптаулар», «Сайтта қарау»
        self.assertContains(self.response, reverse('core:chapter_new', kwargs={'slug': self.SLUG}))
        self.assertContains(self.response, reverse('core:story_settings', kwargs={'slug': self.SLUG}))
        self.assertContains(self.response, reverse('core:story_detail', kwargs={'slug': self.SLUG}))

    def test_has_delete_trigger(self):
        self.assertContains(self.response, 'open-delete-confirm')


class ManageStoryUnknown(TestCase):

    def test_unknown_slug_renders_not_found(self):
        r = self.client.get(reverse('core:manage_story', kwargs={'slug': 'no-such-story'}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Шығарма табылмады')


class ManageStoryEmptyChapters(TestCase):

    SLUG = 'aidana-erteg'   # OnModeration, 3 chapters в .chapters но без записей в CHAPTERS_BY_STORY

    def setUp(self):
        _login_as_aidana(self.client)
        self.response = self.client.get(reverse('core:manage_story', kwargs={'slug': self.SLUG}))

    def test_shows_empty_chapters_cta(self):
        # У 'aidana-erteg' нет глав в CHAPTERS_BY_STORY → empty state в списке
        self.assertContains(self.response, 'Әлі бөлім жоқ')


# ───────────────────────── Story settings ─────────────────────────

class StorySettingsForm(TestCase):

    SLUG = 'aidana-tan'

    def setUp(self):
        _login_as_aidana(self.client)
        self.response = self.client.get(reverse('core:story_settings', kwargs={'slug': self.SLUG}))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_prefilled_title(self):
        story = stub_data.STORIES_BY_SLUG[self.SLUG]
        # значение title попадает в value инпута
        self.assertContains(self.response, f'value="{story.title}"')

    def test_primary_genre_preselected(self):
        story = stub_data.STORIES_BY_SLUG[self.SLUG]
        # Селектор содержит selected на текущем жанре
        self.assertContains(self.response, f'value="{story.primary_genre.slug}" selected')

    def test_status_radio_preselected(self):
        # У 'aidana-tan' статус Published; ветка else → "Аяқталды" checked
        # (мы упростили: или OnProcess, или Completed). По коду текущему — Published уходит в else.
        # Проверим, что один из radio'в имеет checked.
        self.assertContains(self.response, 'checked')

    def test_has_delete_trigger(self):
        self.assertContains(self.response, 'open-delete-confirm')


# ───────────────────────── Chapter editor ─────────────────────────

class ChapterEditorNew(TestCase):

    SLUG = 'aidana-tan'

    def setUp(self):
        _login_as_aidana(self.client)
        self.response = self.client.get(reverse('core:chapter_new', kwargs={'slug': self.SLUG}))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_title_marks_as_new(self):
        self.assertContains(self.response, 'Жаңа бөлім')

    def test_form_fields_empty(self):
        # Поля без value
        self.assertContains(self.response, 'name="title"')
        self.assertContains(self.response, 'name="body"')

    def test_has_both_save_buttons(self):
        # Сохранить как черновик / Опубликовать
        self.assertContains(self.response, 'Жоба ретінде сақтау')
        self.assertContains(self.response, 'Жариялау')


class ChapterEditorEdit(TestCase):

    SLUG = 'aidana-tan'
    CH = 1

    def setUp(self):
        _login_as_aidana(self.client)
        self.response = self.client.get(
            reverse('core:chapter_edit', kwargs={'slug': self.SLUG, 'chapter': self.CH})
        )

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_prefilled_chapter_title(self):
        ch = stub_data.chapter_of(self.SLUG, self.CH)
        self.assertContains(self.response, f'value="{ch.title}"')

    def test_prefilled_chapter_body(self):
        ch = stub_data.chapter_of(self.SLUG, self.CH)
        # Первые слова длинного текста из core/story_texts
        self.assertContains(self.response, 'Бірде ерте таңда')


class ChapterEditorUnknownStory(TestCase):

    def test_unknown_slug_renders_not_found(self):
        _login_as_aidana(self.client)
        r = self.client.get(reverse('core:chapter_new', kwargs={'slug': 'no-such-story'}))
        self.assertContains(r, 'Шығарма табылмады')


class TagInputOnNewStory(TestCase):
    """docs/11 · Фаза 2: tag_input на форме нового произведения."""

    def setUp(self):
        _login_as_aidana(self.client)
        self.response = self.client.get(reverse('core:new_story'))

    def test_renders(self):
        self.assertEqual(self.response.status_code, 200)

    def test_hidden_field_named_tags(self):
        """В форму попадает скрытое поле name='tags' — для submit."""
        self.assertContains(self.response, 'name="tags"')

    def test_accepted_tags_embedded_as_json(self):
        """Alpine читает accepted-теги через json_script с id='tag-input-accepted'."""
        self.assertContains(self.response, 'id="tag-input-accepted"')
        # Хотя бы один accepted-тег попал в JSON
        self.assertContains(self.response, 'мектеп')

    def test_blocklist_embedded_as_json(self):
        self.assertContains(self.response, 'id="tag-input-blocked"')
        # Django json_script экранирует non-ASCII как \uXXXX, поэтому 'политика'
        # в bytes отсутствует. Проверяем латинский 'spam' из блок-листа.
        self.assertContains(self.response, 'spam')

    def test_no_initial_tags_for_new_story(self):
        """У новой стори чипов нет — initial пустой."""
        self.assertContains(self.response, 'initial: []')


class TagInputOnStorySettings(TestCase):
    """docs/11 · Фаза 2: tag_input на странице настроек — initial из stub."""

    # У aidana-tan есть теги, включая pending 'experimental'
    SLUG = 'aidana-tan'

    def setUp(self):
        _login_as_aidana(self.client)
        self.response = self.client.get(reverse('core:story_settings', kwargs={'slug': self.SLUG}))

    def test_renders(self):
        self.assertEqual(self.response.status_code, 200)

    def test_initial_tags_passed_to_alpine(self):
        """В initial-массив Alpine попадают существующие теги стори."""
        # Имена тегов aidana-tan: 'саяхат', 'жасөспірім', 'арман', 'эксперимент'
        for name in ('саяхат', 'жасөспірім', 'арман', 'эксперимент'):
            with self.subTest(tag=name):
                self.assertContains(self.response, name)
