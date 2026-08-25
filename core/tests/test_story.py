"""STORY-модуль: detail с inline-чтением глав.

Покрываем:
 - валидный/невалидный slug;
 - inline-чтение главы на странице detail (?chapter=N), тизер для гл.1;
 - prev/next ссылки через ?chapter=N±1 в граничных случаях;
 - per-chapter комментарии под текстом главы;
 - gate для комментариев у гостя, форма для авторизованного;
 - ReportModal-триггер только для авторизованного;
 - прогресс чтения отображается только если slug совпадает с SAMPLE_PROGRESS.
"""

from core.tests.base import TestCase, login_as
from django.urls import reverse

from core import data


STORY_SLUG = 'dalney-berega'   # есть в STORIES_BY_SLUG и в CHAPTERS_BY_STORY


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
        story = data.story_by_slug(STORY_SLUG)
        self.assertContains(self.response, story.title)
        self.assertContains(self.response, story.author.public_name)

    def test_annotation_section_present(self):
        self.assertContains(self.response, 'Аннотация')

    def test_first_chapter_shown_inline(self):
        """Под аннотацией — первая глава с её заголовком."""
        ch1 = data.chapter_of(STORY_SLUG, 1)
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
        # Старого пути /read/ нигде в шаблоне быть не должно
        self.assertNotContains(self.response, f'/story/{STORY_SLUG}/read/')

    def test_right_rail_chapter_links_use_query(self):
        """Список глав в рейле ведёт на ?chapter=N (а не на /read/N/)."""
        for c in data.chapters_of(STORY_SLUG):
            with self.subTest(chapter=c.number):
                self.assertContains(self.response, f'?chapter={c.number}')

    def test_mobile_chapter_selector_present(self):
        """На mobile список глав доступен в основном контенте, потому что right rail скрыт."""
        self.assertContains(self.response, 'aria-label="Мобильді бөлімдер"')
        self.assertContains(self.response, '<summary', html=False)

    def test_next_chapter_link_present(self):
        """На гл.1 есть ссылка «Келесі бөлім» через ?chapter=2."""
        self.assertContains(self.response, 'Келесі бөлім')
        self.assertContains(self.response, '?chapter=2')

    def test_no_prev_link_on_first_chapter(self):
        self.assertNotContains(self.response, 'Алдыңғы бөлім')

    def test_genres_chips_rendered(self):
        story = data.story_by_slug(STORY_SLUG)
        for g in story.genres_resolved:
            with self.subTest(genre=g.slug):
                self.assertContains(self.response, g.name)


class StoryDetailChapterParam(TestCase):
    """?chapter=N показывает конкретную главу полностью (без тизера)."""

    def test_chapter_2_renders_full_text(self):
        ch2 = data.chapter_of(STORY_SLUG, 2)
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
        last = len(data.chapters_of(STORY_SLUG))
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
        ch1 = data.chapter_of(STORY_SLUG, 1)
        self.assertContains(r, ch1.title)

    def test_garbage_chapter_param_falls_back(self):
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + '?chapter=abc'
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)


class StoryDetailSingleWork(TestCase):
    SLUG = 'sila-imperii'

    def setUp(self):
        self.response = self.client.get(reverse('core:story_detail', kwargs={'slug': self.SLUG}))

    def test_single_work_uses_full_text_label(self):
        self.assertContains(self.response, 'Толық мәтін')
        self.assertContains(self.response, 'Бір оқылым')

    def test_single_work_hides_chapter_navigation(self):
        self.assertNotContains(self.response, 'aria-label="Мобильді бөлімдер"')
        self.assertNotContains(self.response, 'Келесі бөлім')


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
        login_as(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertNotContains(r, 'Пікір қалдыру үшін')
        self.assertContains(r, '<textarea')

    def test_report_trigger_only_for_authed(self):
        r_guest = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertNotContains(r_guest, "open-report")

        login_as(self.client)
        r_auth = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r_auth, "open-report")


class StoryDetailReadingProgress(TestCase):
    """Прогресс «Оқылды N/M» только если slug совпадает с SAMPLE_PROGRESS.story_slug."""

    def test_authed_with_matching_progress_shows_indicator(self):
        # SAMPLE_PROGRESS привязан к 'dalney-berega'
        self.assertEqual(data.reading_progress_of('aidana').story.slug, STORY_SLUG)
        login_as(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'Оқылды:')

    def test_authed_other_story_no_progress_indicator(self):
        login_as(self.client)
        # Другой slug — даже если у пользователя есть прогресс на dalney-berega,
        # на других страницах он не должен подсвечиваться.
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': 'arhimag'}))
        self.assertNotContains(r, 'Оқылды:')

    def test_guest_no_progress_indicator(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertNotContains(r, 'Оқылды:')


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
        login_as(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': self.HAS_PENDING_SLUG}))
        self.assertNotContains(r, 'басқа әлем')
        self.assertNotContains(r, 'проверкада')

    def test_author_sees_own_pending_tag_with_badge(self):
        # aidana заходит на своё произведение → видит pending-тег с бейджем
        login_as(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': self.OWN_PENDING_SLUG}))
        self.assertContains(r, 'эксперимент')   # pending-тег
        self.assertContains(r, 'проверкада')    # бейдж модерации


class StoryDetailAnnotation(TestCase):
    """Аннотация приходит из данных, а не из шаблона.

    Три месяца в шаблоне лежал захардкоженный абзац — один и тот же на всех
    22 произведениях, при заполненном `Story.annotation`. Аннотация и есть
    главный аргумент «читать или нет», так что подмена била в самое ценное.
    """

    def test_annotation_comes_from_the_story(self):
        for slug in ('dalney-berega', 'tunge-deiin'):
            with self.subTest(story=slug):
                story = data.story_by_slug(slug)
                r = self.client.get(reverse('core:story_detail', kwargs={'slug': slug}))
                self.assertContains(r, story.annotation)

    def test_hardcoded_placeholder_is_gone(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertNotContains(r, 'Авторлар әлемі')


class StoryDetailSaveButton(TestCase):
    """«Сақтау» — живая кнопка: состояние из библиотеки, гость идёт на логин."""

    IN_LIBRARY = 'dalney-berega'      # у Айданы kind='reading'
    NOT_IN_LIBRARY = 'zhuldyz-kartasy'

    def test_guest_click_leads_to_login(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': self.IN_LIBRARY}))
        self.assertContains(r, 'Сақтау')
        self.assertContains(r, reverse('core:login'))

    def test_saved_state_reflects_library(self):
        login_as(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': self.IN_LIBRARY}))
        self.assertContains(r, 'saved: true')

    def test_unsaved_state_for_story_outside_library(self):
        login_as(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': self.NOT_IN_LIBRARY}))
        self.assertContains(r, 'saved: false')


class StoryDetailReadCta(TestCase):
    """Подпись главной кнопки говорит, что произойдёт: начать или продолжить."""

    def test_guest_sees_start_label(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'Оқуды бастау')

    def test_reader_with_progress_sees_resume_label(self):
        login_as(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'Жалғастыру · ')
        self.assertNotContains(r, 'Оқуды бастау')

    def test_single_work_says_simply_read(self):
        """У однобөлімного «начать» нечего — там просто «Оқу»."""
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': 'tunge-deiin'}))
        self.assertContains(r, '<span>Оқу</span>', html=False)
        self.assertNotContains(r, 'Оқуды бастау')


class StoryDetailAuthorOnMobile(TestCase):
    """Карточка автора рендерится дважды: в рейле (xl+) и в контенте (xl:hidden).

    Рейл начинается с xl, поэтому на телефоне от автора оставалась строка
    с 24px-аватаром — на платформе, чья ценность в живых молодых авторах.
    """

    def test_author_card_rendered_twice(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        story = data.story_by_slug(STORY_SLUG)
        self.assertContains(r, story.author.bio, count=2)

    def test_follow_action_present_for_guest(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'Жазылу')


class StoryDetailReportPlacement(TestCase):
    """Жалоба — в подвале, а не в ряду действий рядом с кнопкой чтения."""

    def test_report_button_stands_below_recommendations(self):
        login_as(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        html = r.content.decode()
        # Ищем именно жалобу на произведение: `open-report` теперь есть ещё и
        # в меню каждого комментария, с целью `comment:<id>` (BR-33).
        self.assertLess(html.index('Басқа шығармалар'), html.index("target: 'story:"))


class StoryReaderSettings(TestCase):
    """FR-STORY-07: настройки чтения открываются панелью, а не стоят рядом.

    Развёрнутый ряд из трёх групп 32px-кнопок стоял перед текстом и на 375px
    переносился в две строки — три решения до первой прочитанной строки.
    """

    def setUp(self):
        self.response = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))

    def test_settings_hide_behind_a_trigger(self):
        self.assertContains(self.response, 'Оқу параметрлері')
        self.assertContains(self.response, 'settingsOpen')

    def test_all_three_axes_still_available(self):
        for value in ('reader-size-large', 'reader-lead-tight', 'reader-theme-night'):
            with self.subTest(value=value):
                self.assertContains(self.response, value)

    def test_choice_survives_the_jump_to_the_next_chapter(self):
        """Навигация по главам — full reload, поэтому выбор лежит в localStorage."""
        for key in ('bp-reader-size', 'bp-reader-lead', 'bp-reader-theme'):
            with self.subTest(key=key):
                self.assertContains(self.response, key)


class ChapterTextMeasure(TestCase):
    """DEC-35: длина строки задана явно, а не остатком от отступов.

    На 375px контейнер px-4 и карточка p-6 оставляли тексту 295px — около
    35 знаков при комфортных 45-75. Причём все три настройки работали
    против читателя: ось ширины на телефоне не делала ничего, крупный кегль
    сужал меру, а тёплый и ночной фон добавляли свой padding.
    """

    def setUp(self):
        self.response = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))

    def test_measure_is_pinned_in_ch(self):
        """68ch привязано к кеглю: мера не плывёт при увеличении шрифта."""
        self.assertContains(self.response, 'max-width: 68ch')

    def test_card_goes_full_bleed_on_mobile(self):
        """-mx-4 гасит px-4 контейнера: тексту 343px вместо 295."""
        self.assertContains(self.response, '-mx-4')
        self.assertContains(self.response, 'sm:mx-0')

    def test_theme_no_longer_narrows_the_line(self):
        """Отрицательное поле гасит горизонтальный padding подложки."""
        self.assertContains(self.response, 'margin-inline: -1rem')

    def test_size_and_lead_are_separate_properties(self):
        """Раньше обе оси трогали line-height, и порядок правил решал, чья возьмёт."""
        html = self.response.content.decode()
        self.assertIn('.reader-size-base  { font-size: 17px; }', html)
        self.assertIn('.reader-lead-tight { line-height: 1.6; }', html)

    def test_long_word_cannot_break_the_column(self):
        self.assertContains(self.response, 'overflow-wrap: break-word')

    def test_chapter_text_is_long_enough_to_show_the_problem(self):
        """На тексте в три абзаца ни мера, ни прогресс, ни панель не проявляются."""
        body = data.chapter_of(STORY_SLUG, 3).body
        self.assertGreater(len(body), 2000, 'нужна длинная глава для проверки чтения')


class ChapterProgressNotDuplicated(TestCase):
    """Счётчик «N / M» в шапке главы и в панели чтения — один и тот же."""

    def test_header_progress_hidden_on_mobile(self):
        login_as(self.client)
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + '?chapter=4'
        html = self.client.get(url).content.decode()
        idx = html.index('Оқылды:')
        self.assertIn('sm:block', html[idx - 200:idx])


class StoryReadingPanel(TestCase):
    """Панель чтения на мобильном: прогресс, оглавление, следующая глава."""

    def test_panel_present_while_a_chapter_is_open(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'Оқу панелі')

    def test_panel_absent_without_a_chapter(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': 'no-such-story'}))
        self.assertNotContains(r, 'Оқу панелі')

    def test_panel_opens_the_chapter_sheet(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'Бөлімдер тізімі')
        self.assertContains(r, 'chaptersOpen')

    def test_single_work_has_no_chapter_sheet(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': 'tunge-deiin'}))
        self.assertNotContains(r, 'Бөлімдер тізімі')

    def test_mobile_nav_yields_its_place_to_the_panel(self):
        """Две плавающие пилюли на 375px наехали бы друг на друга (docs/07 §7.6)."""
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'reading-mode')


class ChapterListShowsLikes(TestCase):
    """FR-STORY-12: в списке глав счётчик реакций read-only — реакция ставится в главе."""

    def test_chapter_like_counts_rendered(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        first = data.chapter_of(STORY_SLUG, 1)
        self.assertTrue(first.likes, 'нужна глава с реакциями для проверки')
        self.assertContains(r, f'{first.likes} реакция')

    def test_no_like_button_in_the_list(self):
        """Ряд реакций живёт только под текстом главы — реакция требует прочтения (BR-REACT-04)."""
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'Авторды қолдау — бір рет басу ғана', count=1)


class ChapterReactions(TestCase):
    """FR-STORY-12 / DEC-32: пять реакций вместо одиночного лайка."""

    def setUp(self):
        self.response = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))

    def test_all_five_reactions_rendered(self):
        for reaction in data.REACTIONS:
            with self.subTest(reaction=reaction.slug):
                self.assertContains(self.response, reaction.label)

    def test_every_reaction_carries_a_word_label(self):
        """Эмодзи запрещены, монохромная иконка 20px без подписи неразличима."""
        for reaction in data.REACTIONS:
            with self.subTest(reaction=reaction.slug):
                self.assertContains(self.response, f'>{reaction.label}<')

    def test_old_single_like_is_gone(self):
        self.assertNotContains(self.response, 'Бұл бөлім ұнады ма?')

    def test_guest_click_leads_to_login(self):
        self.assertContains(self.response, reverse('core:login'))

    def test_zero_count_reactions_still_shown(self):
        """Набор из пяти кнопок одинаков у первой главы и у сотой."""
        items = data.reactions_of(data.chapter_of(STORY_SLUG, 1))
        self.assertEqual(5, len(items))

    def test_story_counter_is_the_sum_of_reactions(self):
        chapter = data.chapter_of(STORY_SLUG, 3)
        self.assertEqual(chapter.likes,
                         sum(r.count for r in chapter.reactions.all()))

    def test_top_reaction_reads_the_chapter(self):
        """«Алғашқы кездесу» собирает Жүрегім, «Депрессия» — Жыладым."""
        self.assertEqual('juregim', data.chapter_of(STORY_SLUG, 3).top_reaction.slug)
        self.assertEqual('jyladym', data.chapter_of(STORY_SLUG, 4).top_reaction.slug)


class ChapterPollStates(TestCase):
    """FR-STORY-13 / DEC-33: необязательный опрос автора под главой."""

    OPEN_CHAPTER = 12    # последняя вышедшая — ответа ещё нет
    CLOSED_CHAPTER = 3   # следующая глава вышла, опрос закрыт

    def _get(self, chapter):
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + f'?chapter={chapter}'
        return self.client.get(url)

    def test_chapter_without_a_poll_shows_no_block(self):
        """Опрос необязателен — его отсутствие не пустое состояние (BR-POLL-01)."""
        self.assertIsNone(data.poll_of(STORY_SLUG, 5))
        self.assertNotContains(self._get(5), 'Автордың сұрағы')

    def test_open_poll_rendered_with_its_question(self):
        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER)
        self.assertFalse(poll.closed)
        self.assertContains(self._get(self.OPEN_CHAPTER), poll.question)

    def test_poll_closes_when_the_next_chapter_ships(self):
        poll = data.poll_of(STORY_SLUG, self.CLOSED_CHAPTER)
        self.assertTrue(poll.closed)
        self.assertEqual(self.CLOSED_CHAPTER + 1, poll.answer_chapter)

    def test_closed_poll_points_at_the_chapter_with_the_answer(self):
        r = self._get(self.CLOSED_CHAPTER)
        self.assertContains(r, 'Сұрақ жабылды')
        self.assertContains(r, f'{self.CLOSED_CHAPTER + 1}-бөлімде')

    def test_guest_sees_the_question_but_votes_through_login(self):
        r = self._get(self.OPEN_CHAPTER)
        self.assertContains(r, 'Жауап беру үшін')
        self.assertContains(r, reverse('core:login'))

    def test_authed_gets_a_real_ballot(self):
        login_as(self.client)
        r = self._get(self.OPEN_CHAPTER)
        self.assertContains(r, 'Дұрыс жауабы жоқ')
        self.assertNotContains(r, 'Жауап беру үшін')

    def test_percentages_sum_to_a_hundred(self):
        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER)
        self.assertEqual(100, sum(r['percent'] for r in poll.results))

    def test_the_decorative_block_is_gone(self):
        """DEC-33: три захардкоженных варианта, одинаковых на всех произведениях."""
        r = self._get(1)
        self.assertNotContains(r, 'Батыл қадам')
        self.assertNotContains(r, 'Кейіпкердің келесі таңдауы')

    def test_single_work_can_have_a_poll_too(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': 'tunge-deiin'}))
        self.assertContains(r, 'Автордың сұрағы')


class WhatsNextPlacement(TestCase):
    """Позиция блока «что дальше» зависит от того, дочитано ли произведение.

    Внизу, за лентой комментариев, до него на телефоне не добирались. Но
    поднимать безусловно нельзя: в середине сериала следующий шаг — следующая
    глава, и подборки с ней конкурируют.
    """

    LAST = 12   # у dalney-berega 12 глав

    def _html(self, chapter):
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + f'?chapter={chapter}'
        return self.client.get(url).content.decode()

    def test_mid_serial_keeps_it_below_comments(self):
        html = self._html(3)
        self.assertLess(html.index('пікірлері'), html.index('Басқа шығармалар'))

    def test_last_chapter_lifts_it_above_comments(self):
        html = self._html(self.LAST)
        self.assertLess(html.index('Басқа шығармалар'), html.index('пікірлері'))

    def test_single_work_lifts_it_above_comments(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': 'tunge-deiin'}))
        html = r.content.decode()
        self.assertLess(html.index('Басқа шығармалар'), html.index('пікірлері'))

    def test_block_is_rendered_exactly_once(self):
        """Два include под разными условиями — легко получить дубль."""
        for chapter in (3, self.LAST):
            with self.subTest(chapter=chapter):
                self.assertEqual(1, self._html(chapter).count('id="related-heading"'))


class CommentMenu(TestCase):
    """Меню трёх точек: набор пунктов зависит от того, чей комментарий.

    Кнопка три месяца висела без обработчика — ни события, ни цели.
    """

    # У dalney-berega гл.3: комментарий aidana (свой для демо-логина)
    # и комментарий aygerim_k (чужой).
    URL_KW = {'slug': STORY_SLUG}

    def _get(self):
        url = reverse('core:story_detail', kwargs=self.URL_KW) + '?chapter=3'
        return self.client.get(url)

    def test_menu_button_is_wired(self):
        r = self._get()
        self.assertContains(r, 'Пікір мәзірі')
        self.assertContains(r, 'Сілтемені көшіру')

    def test_guest_gets_only_the_link_item(self):
        r = self._get()
        self.assertContains(r, 'Сілтемені көшіру')
        self.assertNotContains(r, 'Шағым жіберу')
        self.assertNotContains(r, 'target: \'comment:')

    def test_authed_can_report_someone_elses_comment(self):
        login_as(self.client)
        r = self._get()
        self.assertContains(r, 'Шағым жіберу')
        self.assertContains(r, "target: 'comment:")

    def test_own_comment_offers_delete_not_report(self):
        """На свой комментарий жаловаться некому — его удаляют."""
        login_as(self.client)
        html = self._get().content.decode()
        own = next(c for c in data.comments_of_chapter(STORY_SLUG, 3)
                   if c.belongs_to('aidana'))
        block = html[html.index(f'id="comment-{own.id}"'):]
        block = block[:block.index('</article>')]
        self.assertIn('Жою', block)
        self.assertNotIn('Шағым жіберу', block)

    def test_comment_anchor_is_its_primary_key(self):
        """Скопированная ссылка обязана работать и завтра.

        В стабе якорь считался из текста crc32-суммой — потому что ключа
        не было, а `hash()` рандомизируется от запуска к запуску. Теперь
        якорь и есть первичный ключ строки: устойчивее не бывает.
        """
        c = data.comments_of_chapter(STORY_SLUG, 3)[0]
        self.assertIsInstance(c.id, int)
        self.assertContains(self._get(), f'id="comment-{c.id}"')


class ReportUsesItsOwnIcon(TestCase):
    """Три точки — иконка контейнера («ещё варианты»), а не действия.

    На «Шағым жіберу» они стояли в двух местах сразу, и в меню комментария
    получалось «ещё варианты → ещё варианты». Жалоба помечена флажком —
    конвенцией YouTube, Instagram и Reddit.
    """

    def _html(self):
        login_as(self.client)
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + '?chapter=3'
        return self.client.get(url).content.decode()

    def test_report_actions_use_the_flag(self):
        html = self._html()
        self.assertIn('#icon-flag', html)

    def test_dots_left_only_on_the_menu_trigger(self):
        """Единственное законное место точек — кнопка, открывающая меню."""
        html = self._html()
        self.assertNotIn('#icon-dots-vertical', html)
        trigger_at = html.index('aria-label="Пікір мәзірі"')
        self.assertIn('#icon-dots-horizontal', html[trigger_at:trigger_at + 400])

    def test_moderation_notice_uses_a_shield_not_a_checkmark(self):
        """Галочка говорит «готово», а фраза — «защищено правилами»."""
        html = self._html()
        notice_at = html.index('модерация ережелерімен')
        self.assertIn('#icon-shield', html[notice_at - 500:notice_at])


class CommentLike(TestCase):
    """BR-31: лайк комментария переключается, гость уходит на логин."""

    def test_like_is_interactive(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'aria-label="Ұнату"')
        self.assertContains(r, 'toggle()')

    def test_guest_is_gated_to_login(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, reverse('core:login'))


class CommentReplies(TestCase):
    """BR-30: один уровень ответов — на ответ ответить нельзя."""

    def test_authed_gets_a_reply_form(self):
        login_as(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'Жауап беру')
        self.assertContains(r, 'пікіріне жауап жаз')

    def test_guest_reply_leads_to_login(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'Жауап беру')
        self.assertNotContains(r, 'пікіріне жауап жаз')

    def test_reply_itself_has_no_reply_button(self):
        """Инвариант вложенности держит компонент, а не сторона вызова."""
        login_as(self.client)
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + '?chapter=2'
        html = self.client.get(url).content.decode()
        reply = data.comments_of_chapter(STORY_SLUG, 2)[-1].replies[0]
        block = html[html.index(f'id="comment-{reply.id}"'):]
        block = block[:block.index('</article>')]
        self.assertNotIn('Жауап беру', block)


class CommentAuthorLinks(TestCase):
    """Имя и аватар ведут на профиль; аватар красится по username."""

    def test_name_links_to_profile(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        author = data.comments_of_chapter(STORY_SLUG, 1)[0].author
        self.assertContains(r, reverse('core:profile_other',
                                       kwargs={'username': author.username}))

    def test_no_dead_hash_links_left(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertNotContains(r, '<a href="#" class="font-sans text-[13px]')


class StoryLinksBackToItsCollections(TestCase):
    """DEC-31: дочитавший ищет «ещё такого же». Жанр отвечает на это хуже
    всего — две фэнтези бывают совсем разными; подборка собрана по состоянию."""

    def setUp(self):
        self.response = self.client.get(
            reverse('core:story_detail', kwargs={'slug': 'tunge-deiin'}))
        self.html = self.response.content.decode()

    def test_block_lists_every_collection_holding_the_story(self):
        from core import stub_data
        story = data.story_by_slug('tunge-deiin')
        collections = data.collections_of(story)
        self.assertTrue(collections)
        self.assertContains(self.response, 'Мына жинақтарда бар')
        for c in collections:
            with self.subTest(collection=c.slug):
                self.assertContains(self.response, f'/collections/{c.slug}/')

    def test_collections_stand_above_genre_recommendations(self):
        """Редакционная подборка сильнее автоматической выдачи по жанру."""
        self.assertLess(
            self.html.index('Мына жинақтарда бар'),
            self.html.index('Басқа шығармалар'),
        )

    def test_block_absent_when_story_is_in_no_collection(self):
        from core import stub_data
        orphan = next(
            (s for s in data.public_stories() if not data.collections_of(s)), None)
        self.assertIsNotNone(orphan, 'нужен стори вне подборок для проверки пустого случая')
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': orphan.slug}))
        self.assertNotContains(r, 'Мына жинақтарда бар')
