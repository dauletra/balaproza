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
        self.assertContains(self.response, story.author.public_name)

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
        # Старого пути /read/ нигде в шаблоне быть не должно
        self.assertNotContains(self.response, f'/story/{STORY_SLUG}/read/')

    def test_right_rail_chapter_links_use_query(self):
        """Список глав в рейле ведёт на ?chapter=N (а не на /read/N/)."""
        for c in stub_data.chapters_of(STORY_SLUG):
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


class StoryDetailAnnotation(TestCase):
    """Аннотация приходит из данных, а не из шаблона.

    Три месяца в шаблоне лежал захардкоженный абзац — один и тот же на всех
    22 произведениях, при заполненном `Story.annotation`. Аннотация и есть
    главный аргумент «читать или нет», так что подмена била в самое ценное.
    """

    def test_annotation_comes_from_the_story(self):
        for slug in ('dalney-berega', 'tunge-deiin'):
            with self.subTest(story=slug):
                story = stub_data.STORIES_BY_SLUG[slug]
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
        _login(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': self.IN_LIBRARY}))
        self.assertContains(r, 'saved: true')

    def test_unsaved_state_for_story_outside_library(self):
        _login(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': self.NOT_IN_LIBRARY}))
        self.assertContains(r, 'saved: false')


class StoryDetailReadCta(TestCase):
    """Подпись главной кнопки говорит, что произойдёт: начать или продолжить."""

    def test_guest_sees_start_label(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'Оқуды бастау')

    def test_reader_with_progress_sees_resume_label(self):
        _login(self.client)
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
        story = stub_data.STORIES_BY_SLUG[STORY_SLUG]
        self.assertContains(r, story.author.bio, count=2)

    def test_follow_action_present_for_guest(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'Жазылу')


class StoryDetailReportPlacement(TestCase):
    """Жалоба — в подвале, а не в ряду действий рядом с кнопкой чтения."""

    def test_report_button_stands_below_recommendations(self):
        _login(self.client)
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        html = r.content.decode()
        self.assertLess(html.index('Басқа шығармалар'), html.index('open-report'))


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
        for value in ('reader-size-large', 'reader-width-narrow', 'reader-theme-night'):
            with self.subTest(value=value):
                self.assertContains(self.response, value)

    def test_choice_survives_the_jump_to_the_next_chapter(self):
        """Навигация по главам — full reload, поэтому выбор лежит в localStorage."""
        for key in ('bp-reader-size', 'bp-reader-width', 'bp-reader-theme'):
            with self.subTest(key=key):
                self.assertContains(self.response, key)


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
        first = stub_data.chapter_of(STORY_SLUG, 1)
        self.assertTrue(first.likes, 'нужна глава с реакциями для проверки')
        self.assertContains(r, f'{first.likes} ұнату')

    def test_no_like_button_in_the_list(self):
        """Ряд реакций живёт только под текстом главы — реакция требует прочтения (BR-REACT-04)."""
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'Авторды қолдау — бір рет басу ғана', count=1)


class ChapterReactions(TestCase):
    """FR-STORY-12 / DEC-32: пять реакций вместо одиночного лайка."""

    def setUp(self):
        self.response = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))

    def test_all_five_reactions_rendered(self):
        for reaction in stub_data.REACTIONS:
            with self.subTest(reaction=reaction.slug):
                self.assertContains(self.response, reaction.label)

    def test_every_reaction_carries_a_word_label(self):
        """Эмодзи запрещены, монохромная иконка 20px без подписи неразличима."""
        for reaction in stub_data.REACTIONS:
            with self.subTest(reaction=reaction.slug):
                self.assertContains(self.response, f'>{reaction.label}<')

    def test_old_single_like_is_gone(self):
        self.assertNotContains(self.response, 'Бұл бөлім ұнады ма?')

    def test_guest_click_leads_to_login(self):
        self.assertContains(self.response, reverse('core:login'))

    def test_zero_count_reactions_still_shown(self):
        """Набор из пяти кнопок одинаков у первой главы и у сотой."""
        items = stub_data.reactions_of(stub_data.chapter_of(STORY_SLUG, 1))
        self.assertEqual(5, len(items))

    def test_story_counter_is_the_sum_of_reactions(self):
        chapter = stub_data.chapter_of(STORY_SLUG, 3)
        self.assertEqual(chapter.likes, sum(c for _, c in chapter.reactions))

    def test_top_reaction_reads_the_chapter(self):
        """«Алғашқы кездесу» собирает Жүрегім, «Депрессия» — Жыладым."""
        self.assertEqual('juregim', stub_data.chapter_of(STORY_SLUG, 3).top_reaction.slug)
        self.assertEqual('jyladym', stub_data.chapter_of(STORY_SLUG, 4).top_reaction.slug)


class ChapterPollStates(TestCase):
    """FR-STORY-13 / DEC-33: необязательный опрос автора под главой."""

    OPEN_CHAPTER = 12    # последняя вышедшая — ответа ещё нет
    CLOSED_CHAPTER = 3   # следующая глава вышла, опрос закрыт

    def _get(self, chapter):
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + f'?chapter={chapter}'
        return self.client.get(url)

    def test_chapter_without_a_poll_shows_no_block(self):
        """Опрос необязателен — его отсутствие не пустое состояние (BR-POLL-01)."""
        self.assertIsNone(stub_data.poll_of(STORY_SLUG, 5))
        self.assertNotContains(self._get(5), 'Автордың сұрағы')

    def test_open_poll_rendered_with_its_question(self):
        poll = stub_data.poll_of(STORY_SLUG, self.OPEN_CHAPTER)
        self.assertFalse(poll.closed)
        self.assertContains(self._get(self.OPEN_CHAPTER), poll.question)

    def test_poll_closes_when_the_next_chapter_ships(self):
        poll = stub_data.poll_of(STORY_SLUG, self.CLOSED_CHAPTER)
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
        _login(self.client)
        r = self._get(self.OPEN_CHAPTER)
        self.assertContains(r, 'Дұрыс жауабы жоқ')
        self.assertNotContains(r, 'Жауап беру үшін')

    def test_percentages_sum_to_a_hundred(self):
        poll = stub_data.poll_of(STORY_SLUG, self.OPEN_CHAPTER)
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


class StoryLinksBackToItsCollections(TestCase):
    """DEC-31: дочитавший ищет «ещё такого же». Жанр отвечает на это хуже
    всего — две фэнтези бывают совсем разными; подборка собрана по состоянию."""

    def setUp(self):
        self.response = self.client.get(
            reverse('core:story_detail', kwargs={'slug': 'tunge-deiin'}))
        self.html = self.response.content.decode()

    def test_block_lists_every_collection_holding_the_story(self):
        from core import stub_data
        story = stub_data.STORIES_BY_SLUG['tunge-deiin']
        collections = stub_data.collections_of(story)
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
            (s for s in stub_data.STORIES if not stub_data.collections_of(s)), None)
        self.assertIsNotNone(orphan, 'нужен стори вне подборок для проверки пустого случая')
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': orphan.slug}))
        self.assertNotContains(r, 'Мына жинақтарда бар')
