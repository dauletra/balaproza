"""STORY-модуль: detail и reading.

Покрываем:
 - валидный/невалидный slug;
 - inline-чтение главы на странице detail (?chapter=N), тизер для гл.1;
 - prev/next ссылки через ?chapter=N±1 в граничных случаях;
 - per-chapter комментарии под текстом главы;
 - gate для комментариев у гостя, форма для авторизованного;
 - ReportModal-триггер только для авторизованного;
 - прогресс чтения отображается только если slug совпадает с SAMPLE_PROGRESS;
 - reading (fullscreen): prev/next ссылки и попавер настроек.
"""

from django.test import TestCase
from django.urls import reverse

from core import stub_data


STORY_SLUG = 'dalney-berega'   # есть в STORIES_BY_SLUG и в CHAPTERS_BY_STORY


def _login(client):
    s = client.session
    s['signed_in'] = True
    s['user_name'] = 'Айдана'
    s['user_username'] = 'aidana'
    s.save()


class StoryDetailUnknownSlug(TestCase):
    """Неизвестный slug → 200 + сообщение «Шығарма табылмады»."""

    def test_unknown_slug_renders_not_found_message(self):
        response = self.client.get(reverse('core:story_detail', kwargs={'slug': 'no-such-story'}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Шығарма табылмады')
        # И никаких артефактов главы
        self.assertNotContains(response, 'Аннотация')


class StoryDetailValidSlug(TestCase):
    """Гость заходит на /story/<slug>/ — видит главную карточку, аннотацию и тизер гл.1."""

    def setUp(self):
        self.url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG})
        self.response = self.client.get(self.url)

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_title_includes_story_and_author(self):
        story = stub_data.STORIES_BY_SLUG[STORY_SLUG]
        self.assertContains(self.response, story.title)
        self.assertContains(self.response, story.author.name)

    def test_annotation_section_present(self):
        self.assertContains(self.response, 'Аннотация')

    def test_first_chapter_shown_inline(self):
        """Под аннотацией — первая глава с её заголовком."""
        ch1 = stub_data.chapter_of(STORY_SLUG, 1)
        self.assertContains(self.response, ch1.title)
        self.assertContains(self.response, '1-бөлім')

    def test_first_chapter_renders_as_teaser_for_guest(self):
        """Гость на голом URL без ?chapter — видит «Жалғастыру» (тизер)."""
        self.assertContains(self.response, 'Жалғастыру')

    def test_no_old_scrollspy_anchors(self):
        """Старый scrollspy-блок удалён."""
        # Якорь #anon/#comments в pill-nav больше не нужны
        self.assertNotContains(self.response, 'href="#anon"')
        self.assertNotContains(self.response, 'href="#comments"')

    def test_no_read_button(self):
        """Кнопка «Оқу» удалена — чтение происходит inline."""
        # На detail-странице не должно быть ссылки на fullscreen-читалку
        read_url = reverse('core:story_read', kwargs={'slug': STORY_SLUG})
        self.assertNotContains(self.response, f'href="{read_url}"')

    def test_right_rail_chapter_links_use_query(self):
        """Список глав в рейле ведёт на ?chapter=N (а не на /read/N/)."""
        for c in stub_data.chapters_of(STORY_SLUG):
            with self.subTest(chapter=c.number):
                self.assertContains(self.response, f'?chapter={c.number}')

    def test_next_chapter_link_present(self):
        """На гл.1 есть ссылка «Келесі бөлім» через ?chapter=2."""
        self.assertContains(self.response, 'Келесі бөлім')
        self.assertContains(self.response, '?chapter=2')

    def test_no_prev_link_on_first_chapter(self):
        self.assertNotContains(self.response, 'Алдыңғы бөлім')

    def test_genres_chips_rendered(self):
        story = stub_data.STORIES_BY_SLUG[STORY_SLUG]
        for g in story.genres_resolved:
            with self.subTest(genre=g.slug):
                self.assertContains(self.response, g.name)


class StoryDetailChapterParam(TestCase):
    """?chapter=N показывает конкретную главу полностью (без тизера)."""

    def test_chapter_2_renders_full_text(self):
        ch2 = stub_data.chapter_of(STORY_SLUG, 2)
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + '?chapter=2'
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, ch2.title)
        self.assertContains(r, '2-бөлім')
        # Тизер только для гл.1 на голом URL — здесь его быть не должно
        self.assertNotContains(r, 'Жалғастыру')

    def test_prev_and_next_for_middle_chapter(self):
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + '?chapter=4'
        r = self.client.get(url)
        self.assertContains(r, 'Алдыңғы бөлім')
        self.assertContains(r, 'Келесі бөлім')
        self.assertContains(r, '?chapter=3')
        self.assertContains(r, '?chapter=5')

    def test_last_chapter_has_no_next(self):
        last = len(stub_data.chapters_of(STORY_SLUG))
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + f'?chapter={last}'
        r = self.client.get(url)
        # Ссылки на ?chapter=last+1 быть не должно
        self.assertNotContains(r, f'?chapter={last + 1}')
        self.assertContains(r, 'соңғы бөлім')

    def test_out_of_range_falls_back_to_chapter_1(self):
        """Невалидное N (999) — view возвращает гл.1 (без 404)."""
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + '?chapter=999'
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        ch1 = stub_data.chapter_of(STORY_SLUG, 1)
        self.assertContains(r, ch1.title)

    def test_garbage_chapter_param_falls_back(self):
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + '?chapter=abc'
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)


class StoryDetailPerChapterComments(TestCase):
    """Комментарии под текстом — пришвартованные к текущей главе + общие (chapter_number=None)."""

    def test_chapter_3_shows_aygerim_comment(self):
        """У dalney-berega коммент Айгерім привязан к гл.3."""
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + '?chapter=3'
        r = self.client.get(url)
        self.assertContains(r, '3-бөлім пікірлері')
        self.assertContains(r, 'үшінші бөлімдегі қарттың сұрағы')

    def test_chapter_1_does_not_show_chapter_3_comment(self):
        """На гл.1 коммент из гл.3 не должен появиться."""
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertNotContains(r, 'үшінші бөлімдегі қарттың сұрағы')

    def test_general_comment_visible_on_every_chapter(self):
        """Общий коммент (chapter_number=None) виден под любой главой."""
        for n in (1, 2, 3):
            with self.subTest(chapter=n):
                url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + f'?chapter={n}'
                r = self.client.get(url)
                # «Келесі бөлім жұма күні шығады…» — общее объявление автора
                self.assertContains(r, 'Келесі бөлім жұма күні шығады')


class StoryDetailGuestVsAuth(TestCase):

    def test_guest_sees_gate_no_input(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'Пікір қалдыру үшін')
        self.assertNotContains(r, '<textarea')

    def test_authed_sees_input_no_gate(self):
        _login(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertNotContains(r, 'Пікір қалдыру үшін')
        self.assertContains(r, '<textarea')

    def test_report_trigger_only_for_authed(self):
        r_guest = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertNotContains(r_guest, "open-report")

        _login(self.client)
        r_auth = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r_auth, "open-report")


class StoryDetailReadingProgress(TestCase):
    """Прогресс «Оқылды N/M» только если slug совпадает с SAMPLE_PROGRESS.story_slug."""

    def test_authed_with_matching_progress_shows_indicator(self):
        # SAMPLE_PROGRESS привязан к 'dalney-berega'
        self.assertEqual(stub_data.SAMPLE_PROGRESS.story_slug, STORY_SLUG)
        _login(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'Оқылды:')

    def test_authed_other_story_no_progress_indicator(self):
        _login(self.client)
        # Другой slug — даже если у пользователя есть прогресс на dalney-berega,
        # на других страницах он не должен подсвечиваться.
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': 'arhimag'}))
        self.assertNotContains(r, 'Оқылды:')

    def test_guest_no_progress_indicator(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertNotContains(r, 'Оқылды:')


class StoryReadKnownChapter(TestCase):

    def setUp(self):
        self.url = reverse('core:story_read_chapter', kwargs={'slug': STORY_SLUG, 'chapter': 4})
        self.response = self.client.get(self.url)

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_renders_chapter_title_and_some_body(self):
        chapter = stub_data.chapter_of(STORY_SLUG, 4)
        self.assertContains(self.response, chapter.title)
        # тело главы — длинный текст, проверим первое предложение
        self.assertContains(self.response, 'Бірде ерте таңда')

    def test_has_back_to_story_link(self):
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG})
        self.assertContains(self.response, f'href="{url}"')

    def test_has_prev_and_next_links_for_middle_chapter(self):
        prev_url = reverse('core:story_read_chapter', kwargs={'slug': STORY_SLUG, 'chapter': 3})
        next_url = reverse('core:story_read_chapter', kwargs={'slug': STORY_SLUG, 'chapter': 5})
        self.assertContains(self.response, f'href="{prev_url}"')
        self.assertContains(self.response, f'href="{next_url}"')


class StoryReadEdgeChapters(TestCase):

    def test_first_chapter_has_no_prev_link(self):
        r = self.client.get(reverse('core:story_read_chapter', kwargs={'slug': STORY_SLUG, 'chapter': 1}))
        # «Алдыңғы бөлім» не должно быть
        self.assertNotContains(r, 'Алдыңғы бөлім')
        # Зато «Келесі бөлім» есть
        self.assertContains(r, 'Келесі бөлім')

    def test_last_chapter_has_no_next_link(self):
        last = len(stub_data.chapters_of(STORY_SLUG))
        r = self.client.get(reverse('core:story_read_chapter', kwargs={'slug': STORY_SLUG, 'chapter': last}))
        self.assertContains(r, 'Алдыңғы бөлім')
        self.assertNotContains(r, 'Келесі бөлім')


class StoryReadUnknownChapter(TestCase):

    def test_chapter_out_of_range_renders_not_found(self):
        r = self.client.get(reverse('core:story_read_chapter', kwargs={'slug': STORY_SLUG, 'chapter': 999}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Бөлім табылмады')


class StoryReadHasSettingsPopover(TestCase):

    def test_popover_listens_for_reader_settings_event(self):
        r = self.client.get(reverse('core:story_read', kwargs={'slug': STORY_SLUG}))
        # Wrapper читалки реагирует на событие reader-settings
        self.assertContains(r, 'reader-settings')
        # Popover содержит триггерную aria
        self.assertContains(r, 'Оқу баптаулары')


class StoryDetailTags(TestCase):
    """docs/11: UGC-теги. Pending видны только автору (BR-TAG-07)."""

    # У `dalney-berega` теги все accepted → видны всем
    PUBLIC_SLUG = 'dalney-berega'
    # У `temniy-lord` есть pending-тег 'basqa-alem' (басқа әлем)
    HAS_PENDING_SLUG = 'temniy-lord'
    # У `aidana-tan` есть pending 'experimental' (эксперимент), автор — aidana
    OWN_PENDING_SLUG = 'aidana-tan'

    def test_accepted_tag_visible_to_guest(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': self.PUBLIC_SLUG}))
        self.assertContains(r, 'арман')      # accepted-тег
        self.assertContains(r, 'жасөспірім') # accepted-тег

    def test_pending_tag_hidden_from_guest(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': self.HAS_PENDING_SLUG}))
        self.assertContains(r, 'мистика')        # accepted показан
        self.assertNotContains(r, 'басқа әлем')  # pending скрыт от гостя
        self.assertNotContains(r, 'проверкада')

    def test_pending_tag_hidden_from_other_authed_user(self):
        # Логинимся как aidana, смотрим чужое произведение с pending-тегом
        _login(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': self.HAS_PENDING_SLUG}))
        self.assertNotContains(r, 'басқа әлем')
        self.assertNotContains(r, 'проверкада')

    def test_author_sees_own_pending_tag_with_badge(self):
        # aidana заходит на своё произведение → видит pending-тег с бейджем
        _login(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': self.OWN_PENDING_SLUG}))
        self.assertContains(r, 'эксперимент')   # pending-тег
        self.assertContains(r, 'проверкада')    # бейдж модерации
