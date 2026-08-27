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

from core.tests import factories as make
from core.tests.base import TestCase, login_as, login_as_newcomer
from django.urls import reverse

from core import data
from core.models import (
    ChapterReactionVote,
    LibraryEntry,
    PollVote,
    ReadingProgress,
    Story,
    StoryComment,
)
from django.utils import timezone


STORY_SLUG = 'dalney-berega'   # есть в STORIES_BY_SLUG и в CHAPTERS_BY_STORY


class StoryPageAnswersTheQuestionShouldIRead(TestCase):
    """Шапка, аннотация, теги и первая глава — всё, из чего складывается
    решение читать. Один запрос на класс: сценарий «гость открыл
    произведение» один, и вопросов к нему полтора десятка."""

    def setUp(self):
        self.response = self.client.get(
            reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.story = data.story_by_slug(STORY_SLUG)

    def test_it_names_the_work_its_author_and_its_genres(self):
        self.assertContains(self.response, self.story.title)
        self.assertContains(self.response, self.story.author.public_name)
        for genre in self.story.genres_resolved:
            with self.subTest(genre=genre.slug):
                self.assertContains(self.response, genre.name)

    def test_the_annotation_comes_from_the_work_not_from_the_template(self):
        """Три месяца в шаблоне лежал захардкоженный абзац — один и тот же
        на всех произведениях, при заполненном `Story.annotation`.
        Аннотация и есть главный аргумент «читать или нет»."""
        self.assertContains(self.response, 'Аннотация')
        self.assertContains(self.response, self.story.annotation)
        self.assertNotContains(self.response, 'Авторлар әлемі')

    def test_the_first_chapter_opens_as_a_teaser_with_a_way_onward(self):
        """Чтение идёт inline: отдельного маршрута `/read/` нет (DEC-30),
        и старого scrollspy-блока тоже."""
        self.assertContains(self.response, data.chapter_of(STORY_SLUG, 1).title)
        self.assertContains(self.response, '1-бөлім')
        self.assertContains(self.response, 'Жалғастыру')
        self.assertContains(self.response, 'Келесі бөлім')
        self.assertNotContains(self.response, 'Алдыңғы бөлім')
        self.assertNotContains(self.response, f'/story/{STORY_SLUG}/read/')
        self.assertNotContains(self.response, 'href="#anon"')

    def test_every_chapter_is_reachable_from_the_list(self):
        """Список глав есть и в рейле, и в контенте: рейл начинается с xl."""
        for chapter in data.chapters_of(STORY_SLUG):
            with self.subTest(chapter=chapter.number):
                self.assertContains(self.response, f'?chapter={chapter.number}')
        self.assertContains(self.response, 'aria-label="Мобильді бөлімдер"')

    def test_the_author_card_survives_the_phone(self):
        """Рейл начинается с xl, поэтому на телефоне от автора оставалась
        строка с 24px-аватаром — на платформе, чья ценность в живых
        молодых авторах."""
        self.assertContains(self.response, self.story.author.bio, count=2)
        self.assertContains(self.response, 'Жазылу')

    def test_an_unknown_slug_says_so_without_the_furniture(self):
        response = self.client.get(
            reverse('core:story_detail', kwargs={'slug': 'no-such-story'}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Шығарма табылмады')
        self.assertNotContains(response, 'Аннотация')
        self.assertNotContains(response, 'Оқу панелі')


class ChapterNavigationIsForgiving(TestCase):
    """`?chapter=N` — единственный способ открыть главу. Мусор в параметре
    это старая ссылка или опечатка, а не повод отдать 404."""

    def test_a_middle_chapter_has_both_directions(self):
        response = self.client.get(
            reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + '?chapter=4')
        self.assertContains(response, data.chapter_of(STORY_SLUG, 4).title)
        self.assertContains(response, 'Алдыңғы бөлім')
        self.assertContains(response, 'Келесі бөлім')
        self.assertContains(response, '?chapter=3')
        self.assertContains(response, '?chapter=5')
        # Явный выбор главы отменяет тизер.
        self.assertNotContains(response, 'Жалғастыру')

    def test_the_last_chapter_offers_nothing_further(self):
        last = len(data.chapters_of(STORY_SLUG))
        response = self.client.get(
            reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + f'?chapter={last}')
        self.assertContains(response, 'соңғы бөлім')
        self.assertNotContains(response, f'?chapter={last + 1}')

    def test_junk_falls_back_to_the_first_chapter(self):
        for junk in ('999', 'abc', '0', '-2'):
            with self.subTest(chapter=junk):
                response = self.client.get(
                    reverse('core:story_detail', kwargs={'slug': STORY_SLUG})
                    + f'?chapter={junk}')
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, data.chapter_of(STORY_SLUG, 1).title)

    def test_a_single_work_has_no_chapter_navigation_at_all(self):
        """У цельного текста «начать» нечего — там просто «Оқу»."""
        response = self.client.get(
            reverse('core:story_detail', kwargs={'slug': 'tunge-deiin'}))
        self.assertContains(response, 'Толық мәтін')
        self.assertContains(response, 'Бір оқылым')
        self.assertContains(response, '<span>Оқу</span>')
        self.assertNotContains(response, 'Оқуды бастау')
        self.assertNotContains(response, 'aria-label="Мобильді бөлімдер"')
        self.assertNotContains(response, 'Келесі бөлім')
        self.assertNotContains(response, 'Бөлімдер тізімі')


class CommentsAreAnchoredToTheirChapter(TestCase):
    """Комментарий швартуется к главе; `chapter_number=None` означает
    разговор о работе целиком и виден под любой главой."""

    def _url(self, chapter=None):
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG})
        return f'{url}?chapter={chapter}' if chapter else url

    def test_a_chapter_shows_its_own_comments_and_the_general_ones(self):
        third = self.client.get(self._url(3))
        self.assertContains(third, '3-бөлім пікірлері')
        self.assertContains(third, 'үшінші бөлімдегі қарттың сұрағы')
        self.assertNotContains(self.client.get(self._url(1)),
                               'үшінші бөлімдегі қарттың сұрағы')
        for number in (1, 2, 3):
            with self.subTest(chapter=number):
                self.assertContains(self.client.get(self._url(number)),
                                    'Келесі бөлім жұма күні шығады')

    def test_a_guest_gets_the_gate_and_an_author_gets_the_form(self):
        guest = self.client.get(self._url())
        self.assertContains(guest, 'Пікір қалдыру үшін')
        self.assertNotContains(guest, '<textarea')
        self.assertNotContains(guest, 'open-report')

        login_as(self.client)
        signed_in = self.client.get(self._url())
        self.assertNotContains(signed_in, 'Пікір қалдыру үшін')
        self.assertContains(signed_in, '<textarea')
        self.assertContains(signed_in, 'open-report')


class PendingTagsAreVisibleOnlyToTheirAuthor(TestCase):
    """BR-TAG-07: тег ещё не прошёл модератора. Автор обязан видеть свой —
    иначе он решит, что тег не сохранился, и поставит его второй раз."""

    def test_the_accepted_ones_are_public_and_the_pending_one_is_not(self):
        author = make.user()
        story = make.story(author=author, chapters=1)
        accepted, pending = make.tag(), make.tag(status='pending')
        story.tags.add(accepted, pending)
        url = reverse('core:story_detail', kwargs={'slug': story.slug})

        guest = self.client.get(url)
        self.assertContains(guest, accepted.name)
        self.assertNotContains(guest, pending.name)
        self.assertNotContains(guest, 'проверкада')

        login_as_newcomer(self.client, 'passer-by')
        self.assertNotContains(self.client.get(url), pending.name)

        login_as(self.client, author.username)
        owner = self.client.get(url)
        self.assertContains(owner, pending.name)
        self.assertContains(owner, 'проверкада')


class StoryDetailSaveButton(TestCase):
    """«Сақтау» кладёт работу на полку, а не только перекрашивает себя.

    Кнопка три месяца была Alpine-состоянием: тост обещал «Кітапханаға
    сақталды», записи не появлялось, и обещание жило до перезагрузки.
    """

    IN_LIBRARY = 'dalney-berega'      # у Айданы kind='reading'
    NOT_IN_LIBRARY = 'zhuldyz-kartasy'

    def _url(self, slug):
        return reverse('core:story_detail', kwargs={'slug': slug})

    def _toggle(self, slug):
        return self.client.post(reverse('core:library_toggle', kwargs={'slug': slug}))

    def _entry(self, slug, username='aidana'):
        return LibraryEntry.objects.filter(user__username=username,
                                           story__slug=slug).first()

    def test_guest_click_leads_to_login(self):
        r = self.client.get(self._url(self.IN_LIBRARY))
        self.assertContains(r, 'Сақтау')
        self.assertContains(r, reverse('core:login'))

    def test_saved_state_reflects_library(self):
        login_as(self.client)
        r = self.client.get(self._url(self.IN_LIBRARY))
        self.assertContains(r, 'Сақталды')
        self.assertContains(r, reverse('core:library_toggle', kwargs={'slug': self.IN_LIBRARY}))

    def test_unsaved_state_for_story_outside_library(self):
        login_as(self.client)
        r = self.client.get(self._url(self.NOT_IN_LIBRARY))
        self.assertContains(r, 'Сақтау')
        self.assertNotContains(r, 'Сақталды')

    def test_saving_puts_it_on_the_saved_shelf(self):
        login_as(self.client)
        self._toggle(self.NOT_IN_LIBRARY)
        entry = self._entry(self.NOT_IN_LIBRARY)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.kind, 'saved')

    def test_pressing_again_takes_it_off_any_shelf(self):
        """Кнопка отвечает на вопрос присутствия, а не выбирает полку:
        снимает и то, что лежало на «оқу үстінде»."""
        login_as(self.client)
        self.assertEqual(self._entry(self.IN_LIBRARY).kind, 'reading')
        self._toggle(self.IN_LIBRARY)
        self.assertIsNone(self._entry(self.IN_LIBRARY))

    def test_toggle_redirects_back_to_the_story(self):
        login_as(self.client)
        r = self._toggle(self.NOT_IN_LIBRARY)
        self.assertRedirects(r, self._url(self.NOT_IN_LIBRARY))

    def test_a_guest_cannot_write_to_anyones_shelf(self):
        before = LibraryEntry.objects.count()
        self._toggle(self.NOT_IN_LIBRARY)
        self.assertEqual(LibraryEntry.objects.count(), before)

    def test_get_changes_nothing(self):
        login_as(self.client)
        before = LibraryEntry.objects.count()
        self.client.get(reverse('core:library_toggle', kwargs={'slug': self.NOT_IN_LIBRARY}))
        self.assertEqual(LibraryEntry.objects.count(), before)


class ReadingMovesTheWorkBetweenShelves(TestCase):
    """Автопереходы полки (BR-61, FR-LIB-02).

    Вкладка «Оқу үстіндегі» наполнялась одним сидом: у настоящего читателя
    она оставалась пустой, сколько бы он ни читал.
    """

    SLUG = STORY_SLUG
    READER = 'lonely_reader'

    def setUp(self):
        login_as_newcomer(self.client, self.READER)
        self.last = len(data.chapters_of(self.SLUG))

    def _open(self, chapter):
        self.client.get(reverse('core:story_detail',
                                kwargs={'slug': self.SLUG}) + f'?chapter={chapter}')

    def _kind(self):
        entry = LibraryEntry.objects.filter(user__username=self.READER,
                                            story__slug=self.SLUG).first()
        return entry.kind if entry else None

    def test_starting_to_read_puts_it_on_the_reading_shelf(self):
        self.assertIsNone(self._kind())
        self._open(2)
        self.assertEqual(self._kind(), 'reading')

    def test_reaching_the_last_chapter_marks_it_read(self):
        self._open(2)
        self._open(self.last)
        self.assertEqual(self._kind(), 'done')

    def test_rereading_a_finished_work_puts_it_back(self):
        """Строка `done` предлагает «Қайта оқу», и после нажатия полка
        обязана описывать то, что происходит."""
        self._open(self.last)
        self.assertEqual(self._kind(), 'done')
        self._open(1)
        self.assertEqual(self._kind(), 'reading')

    def test_reading_never_leaves_two_entries(self):
        for chapter in (1, 3, self.last, 2):
            self._open(chapter)
        self.assertEqual(
            LibraryEntry.objects.filter(user__username=self.READER,
                                        story__slug=self.SLUG).count(), 1)

    def test_a_guest_leaves_no_trace(self):
        self.client.logout()
        before = LibraryEntry.objects.count()
        self._open(3)
        self.assertEqual(LibraryEntry.objects.count(), before)


class TheReadingSurfaceIsBuiltForAPhone(TestCase):
    """DEC-35 и FR-STORY-07. На 375px контейнер `px-4` и карточка `p-6`
    оставляли тексту 295px — около 35 знаков при комфортных 45-75. Причём
    все три настройки работали против читателя: ось ширины на телефоне не
    делала ничего, крупный кегль сужал меру, а тёплый и ночной фон
    добавляли свой padding."""

    def setUp(self):
        self.response = self.client.get(
            reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.html = self.response.content.decode()

    def test_the_measure_is_pinned_in_ch_and_the_card_goes_full_bleed(self):
        self.assertContains(self.response, 'max-width: 68ch')
        self.assertContains(self.response, '-mx-4')       # гасит px-4 контейнера
        self.assertContains(self.response, 'sm:mx-0')
        self.assertContains(self.response, 'margin-inline: -1rem')   # подложка темы
        self.assertContains(self.response, 'overflow-wrap: break-word')

    def test_size_and_leading_are_separate_properties(self):
        """Раньше обе оси трогали `line-height`, и порядок правил в файле
        решал, чья возьмёт."""
        self.assertIn('.reader-size-base  { font-size: 17px; }', self.html)
        self.assertIn('.reader-lead-tight { line-height: 1.6; }', self.html)

    def test_the_settings_hide_behind_a_trigger_and_outlive_the_chapter(self):
        """Развёрнутый ряд из трёх групп 32px-кнопок стоял перед текстом —
        три решения до первой прочитанной строки. Навигация по главам это
        full reload, поэтому выбор лежит в localStorage."""
        self.assertContains(self.response, 'Оқу параметрлері')
        self.assertContains(self.response, 'settingsOpen')
        for value in ('reader-size-large', 'reader-lead-tight', 'reader-theme-night'):
            with self.subTest(value=value):
                self.assertContains(self.response, value)
        for key in ('bp-reader-size', 'bp-reader-lead', 'bp-reader-theme'):
            with self.subTest(key=key):
                self.assertContains(self.response, key)

    def test_the_reading_panel_replaces_the_mobile_nav(self):
        """Две плавающие пилюли на 375px наехали бы друг на друга
        (docs/07 §7.6)."""
        self.assertContains(self.response, 'Оқу панелі')
        self.assertContains(self.response, 'Бөлімдер тізімі')
        self.assertContains(self.response, 'chaptersOpen')
        self.assertContains(self.response, 'reading-mode')

    def test_the_text_is_long_enough_for_any_of_this_to_show(self):
        """На тексте в три абзаца ни мера, ни прогресс, ни панель не
        проявляются."""
        self.assertGreater(len(data.chapter_of(STORY_SLUG, 3).body), 2000)


class TheMainButtonSaysWhatWillHappen(TestCase):

    def test_start_for_a_newcomer_and_resume_for_a_reader(self):
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG})
        self.assertContains(self.client.get(url), 'Оқуды бастау')

        login_as(self.client)
        returning = self.client.get(url)
        self.assertContains(returning, 'Жалғастыру · ')
        self.assertNotContains(returning, 'Оқуды бастау')

    def test_progress_is_shown_only_on_the_work_it_belongs_to(self):
        """И только один раз: счётчик «N / M» в шапке главы и в панели
        чтения — одно и то же число."""
        self.assertNotContains(
            self.client.get(reverse('core:story_detail',
                                    kwargs={'slug': STORY_SLUG})), 'Оқылды:')
        login_as(self.client)
        self.assertEqual(data.reading_progress_of('aidana').story.slug, STORY_SLUG)
        mine = self.client.get(reverse('core:story_detail',
                                       kwargs={'slug': STORY_SLUG}) + '?chapter=4')
        html = mine.content.decode()
        self.assertContains(mine, 'Оқылды:')
        self.assertIn('sm:block', html[html.index('Оқылды:') - 200:html.index('Оқылды:')])
        self.assertNotContains(
            self.client.get(reverse('core:story_detail', kwargs={'slug': 'arhimag'})),
            'Оқылды:')

    def test_a_complaint_lives_below_the_recommendations(self):
        """Жалоба — в подвале, а не в ряду действий рядом с кнопкой чтения."""
        login_as(self.client)
        html = self.client.get(reverse('core:story_detail',
                                       kwargs={'slug': STORY_SLUG})).content.decode()
        self.assertLess(html.index('Басқа шығармалар'), html.index("target: 'story:"))


class ReactionsReplaceTheSingleLike(TestCase):
    """FR-STORY-12 / DEC-32: пять реакций вместо лайка. Каждая обязана
    иметь подпись словом — эмодзи запрещены, а монохромная иконка 20px без
    подписи неразличима."""

    def setUp(self):
        self.response = self.client.get(
            reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))

    def test_all_five_are_offered_with_words(self):
        for reaction in data.REACTIONS:
            with self.subTest(reaction=reaction.slug):
                self.assertContains(self.response, f'>{reaction.label}<')
        self.assertNotContains(self.response, 'Бұл бөлім ұнады ма?')
        self.assertContains(self.response, reverse('core:login'))
        # Набор из пяти кнопок одинаков у первой главы и у сотой.
        self.assertEqual(5, len(data.reactions_of(data.chapter_of(STORY_SLUG, 1))))

    def test_the_chapter_counter_is_their_sum_and_the_top_one_reads_it(self):
        """«Алғашқы кездесу» собирает Жүрегім, «Депрессия» — Жыладым."""
        third = data.chapter_of(STORY_SLUG, 3)
        self.assertEqual(third.likes, sum(r.count for r in third.reactions.all()))
        self.assertEqual('juregim', third.top_reaction.slug)
        self.assertEqual('jyladym', data.chapter_of(STORY_SLUG, 4).top_reaction.slug)

    def test_the_chapter_list_shows_counts_but_offers_no_button(self):
        """Реакция требует прочтения (BR-REACT-04), поэтому ряд живёт
        только под текстом главы."""
        first = data.chapter_of(STORY_SLUG, 1)
        self.assertTrue(first.likes, 'нужна глава с реакциями для проверки')
        self.assertContains(self.response, f'{first.likes} реакция')
        self.assertContains(self.response, 'Авторды қолдау — бір рет басу ғана',
                            count=1)


class ChapterReactionVoting(TestCase):
    """BR-REACT-02/03 (Ф15, Этап 3): реакция ставится, повтор снимает,
    другой вид заменяет; Story.likes — агрегат по числу голосов, а не по
    сумме реакций (BR-14a) — смена вида его не трогает."""

    CHAPTER = 1

    def _url(self):
        return reverse('core:chapter_react',
                       kwargs={'slug': STORY_SLUG, 'chapter': self.CHAPTER})

    def _kind_count(self, kind):
        chapter = data.chapter_of(STORY_SLUG, self.CHAPTER)
        return chapter.reaction_counts.get(kind, 0)

    def _story_likes(self):
        return Story.objects.get(slug=STORY_SLUG).likes

    def test_first_vote_creates_it_and_bumps_story_likes(self):
        login_as(self.client)
        likes_before, kind_before = self._story_likes(), self._kind_count('kuldim')

        self.client.post(self._url(), {'kind': 'kuldim'})

        self.assertEqual(self._kind_count('kuldim'), kind_before + 1)
        self.assertEqual(self._story_likes(), likes_before + 1)
        self.assertTrue(ChapterReactionVote.objects.filter(
            user__username='aidana', chapter__story__slug=STORY_SLUG,
            chapter__number=self.CHAPTER, kind='kuldim').exists())

    def test_repeat_click_removes_the_vote(self):
        login_as(self.client)
        likes_before, kind_before = self._story_likes(), self._kind_count('kuldim')

        self.client.post(self._url(), {'kind': 'kuldim'})
        self.client.post(self._url(), {'kind': 'kuldim'})  # повтор снимает

        self.assertEqual(self._kind_count('kuldim'), kind_before)
        self.assertEqual(self._story_likes(), likes_before)
        self.assertFalse(ChapterReactionVote.objects.filter(
            user__username='aidana', chapter__story__slug=STORY_SLUG,
            chapter__number=self.CHAPTER).exists())

    def test_different_kind_replaces_without_changing_story_likes(self):
        login_as(self.client)
        likes_before = self._story_likes()
        kuldim_before, jyladym_before = self._kind_count('kuldim'), self._kind_count('jyladym')

        self.client.post(self._url(), {'kind': 'kuldim'})
        self.client.post(self._url(), {'kind': 'jyladym'})  # другой вид — замена

        self.assertEqual(self._kind_count('kuldim'), kuldim_before)
        self.assertEqual(self._kind_count('jyladym'), jyladym_before + 1)
        self.assertEqual(self._story_likes(), likes_before + 1)  # один голос, не два
        vote = ChapterReactionVote.objects.get(
            user__username='aidana', chapter__story__slug=STORY_SLUG,
            chapter__number=self.CHAPTER)
        self.assertEqual(vote.kind, 'jyladym')

    def test_guest_post_does_not_vote(self):
        likes_before = self._story_likes()
        self.client.post(self._url(), {'kind': 'kuldim'})
        self.assertEqual(self._story_likes(), likes_before)
        self.assertFalse(ChapterReactionVote.objects.exists())

    def test_invalid_kind_is_rejected(self):
        login_as(self.client)
        self.client.post(self._url(), {'kind': 'not-a-real-reaction'})
        self.assertFalse(ChapterReactionVote.objects.exists())

    def test_reactions_of_reports_the_picked_kind(self):
        """`Chapter.my_reaction` и `mine` в `reactions_of` отражают голос
        именно вошедшего — не жёсткий `False`, как до записи."""
        login_as(self.client)
        self.client.post(self._url(), {'kind': 'shabyt'})

        chapter = data.chapter_of(STORY_SLUG, self.CHAPTER, 'aidana')
        self.assertEqual(chapter.my_reaction, 'shabyt')
        picked = [i['reaction'].slug for i in data.reactions_of(chapter) if i['mine']]
        self.assertEqual(picked, ['shabyt'])

    def test_picked_reaction_shows_the_seen_message(self):
        login_as(self.client)
        self.client.post(self._url(), {'kind': 'shabyt'})
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + f'?chapter={self.CHAPTER}'
        self.assertContains(self.client.get(url), 'Автор сенің реакцияңды көреді.')


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


class ChapterPollVoting(TestCase):
    """Ф15 Этап 4: голос в открытом опросе — один на опрос, не меняется
    (docs/20 §20.2); закрытый опрос голос не принимает (BR-POLL-05)."""

    OPEN_CHAPTER = 12    # последняя вышедшая — ответа ещё нет
    CLOSED_CHAPTER = 3   # следующая глава вышла, опрос закрыт

    def _url(self, chapter):
        return reverse('core:poll_vote', kwargs={'slug': STORY_SLUG, 'chapter': chapter})

    def test_first_vote_is_recorded_and_bumps_the_option(self):
        login_as(self.client)
        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER)
        option = poll.options[0]
        before = option.votes

        self.client.post(self._url(self.OPEN_CHAPTER), {'option': option.slug})

        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER, 'aidana')
        self.assertEqual(poll.my_vote, option.slug)
        self.assertEqual(poll.option_set.get(slug=option.slug).votes, before + 1)
        self.assertTrue(PollVote.objects.filter(
            user__username='aidana', poll=poll, option__slug=option.slug).exists())

    def test_second_vote_does_not_change_the_first(self):
        login_as(self.client)
        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER)
        first, second = poll.options[0], poll.options[1]
        second_before = second.votes

        self.client.post(self._url(self.OPEN_CHAPTER), {'option': first.slug})
        self.client.post(self._url(self.OPEN_CHAPTER), {'option': second.slug})

        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER, 'aidana')
        self.assertEqual(poll.my_vote, first.slug)
        self.assertEqual(poll.option_set.get(slug=second.slug).votes, second_before)
        self.assertEqual(
            PollVote.objects.filter(user__username='aidana', poll=poll).count(), 1)

    def test_guest_post_does_not_vote(self):
        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER)
        self.client.post(self._url(self.OPEN_CHAPTER), {'option': poll.options[0].slug})
        self.assertFalse(PollVote.objects.exists())

    def test_closed_poll_rejects_the_vote(self):
        login_as(self.client)
        poll = data.poll_of(STORY_SLUG, self.CLOSED_CHAPTER)
        self.assertTrue(poll.closed)
        option = poll.options[0]
        before = option.votes

        self.client.post(self._url(self.CLOSED_CHAPTER), {'option': option.slug})

        self.assertFalse(PollVote.objects.exists())
        self.assertEqual(poll.option_set.get(slug=option.slug).votes, before)

    def test_invalid_option_is_rejected(self):
        login_as(self.client)
        self.client.post(self._url(self.OPEN_CHAPTER), {'option': 'not-a-real-option'})
        self.assertFalse(PollVote.objects.exists())

    def test_voted_ballot_shows_results_instead_of_the_form(self):
        login_as(self.client)
        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER)
        self.client.post(self._url(self.OPEN_CHAPTER), {'option': poll.options[0].slug})

        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + f'?chapter={self.OPEN_CHAPTER}'
        r = self.client.get(url)
        self.assertContains(r, 'сенің жауабың')
        self.assertNotContains(r, 'Дұрыс жауабы жоқ — тек сенің болжамың.')


class RelatedStoriesCoverAllPublicStatuses(TestCase):
    """«Басқа шығармалар» не должен состоять из одних `Published`.

    Блок сужался литералом `status='Published'` поверх уже публичной
    выдачи, и после DEC-37 это выкидывало из рекомендаций **все** сериалы —
    почти половину публичного корпуса. Тест смотрит на весь корпус, а не на
    один слаг: сужение возвращается незаметно и не в одной работе.
    """

    def test_recommendations_are_public_foreign_and_include_serials(self):
        seen_statuses = set()
        for source in Story.objects.filter(status__in=data.PUBLIC_STATUSES):
            related = data.related_stories(source.slug)
            with self.subTest(story=source.slug):
                for other in related:
                    self.assertIn(other.status, data.PUBLIC_STATUSES)
                    self.assertNotEqual(other.slug, source.slug)
                    self.assertNotEqual(other.author_id, source.author_id)
            seen_statuses.update(s.status for s in related)

        self.assertTrue(
            seen_statuses - {'Published'},
            'в рекомендациях по всему корпусу нет ни одного сериала — '
            'выдача снова сужена до литерала Published (DEC-37)',
        )


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
    """BR-31: лайк комментария переключается (Ф15, POST), гость уходит на логин."""

    def test_like_is_interactive(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, 'aria-label="Ұнату"')

    def test_guest_is_gated_to_login(self):
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(r, reverse('core:login'))

    def test_post_toggles_the_like_and_the_count(self):
        # `likes` — пересчёт по настоящим CommentLike (не +1 к сид-числу):
        # у демо-комментария «87 ұнату» ни разу не было настоящей строки
        # голоса, и первый реальный лайк отвечает правде, а не сумме с
        # выдуманной историей.
        login_as(self.client, 'aidana')
        comment = data.comments_of_chapter(STORY_SLUG, 1)[0]  # sayyn, не aidana
        url = reverse('core:comment_like',
                      kwargs={'slug': STORY_SLUG, 'comment_id': comment.pk})

        self.client.post(url)
        comment.refresh_from_db()
        self.assertEqual(comment.likes, 1)
        self.assertTrue(comment.like_set.filter(user__username='aidana').exists())

        self.client.post(url)  # повторный клик снимает
        comment.refresh_from_db()
        self.assertEqual(comment.likes, 0)
        self.assertFalse(comment.like_set.filter(user__username='aidana').exists())

    def test_guest_post_does_not_like(self):
        comment = data.comments_of_chapter(STORY_SLUG, 1)[0]
        before = comment.likes
        url = reverse('core:comment_like',
                      kwargs={'slug': STORY_SLUG, 'comment_id': comment.pk})
        self.client.post(url)
        comment.refresh_from_db()
        self.assertEqual(comment.likes, before)


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
        orphan = next(
            (s for s in data.public_stories() if not data.collections_of(s)), None)
        self.assertIsNotNone(orphan, 'нужен стори вне подборок для проверки пустого случая')
        r = self.client.get(reverse('core:story_detail', kwargs={'slug': orphan.slug}))
        self.assertNotContains(r, 'Мына жинақтарда бар')


# ═════════════════════ Ф15, Этап 2: комментарии (POST) ═════════════════════

class CommentCreatePersists(TestCase):

    SLUG = 'dalney-berega'

    def setUp(self):
        login_as(self.client, 'aidana')

    def test_top_level_comment_is_saved_and_bumps_the_story_counter(self):
        story = Story.objects.get(slug=self.SLUG)
        before = story.comments
        r = self.client.post(
            reverse('core:comment_create', kwargs={'slug': self.SLUG}),
            {'text': 'Керемет оқылды!', 'chapter': '3'})
        comment = StoryComment.objects.get(story=story, text='Керемет оқылды!')
        self.assertEqual(comment.author.username, 'aidana')
        self.assertEqual(comment.chapter_number, 3)
        self.assertIsNone(comment.parent)
        story.refresh_from_db()
        self.assertEqual(story.comments, before + 1)
        self.assertRedirects(
            r, reverse('core:story_detail', kwargs={'slug': self.SLUG})
            + f'?chapter=3#comment-{comment.pk}')

    def test_reply_to_a_top_level_comment_is_saved(self):
        top = next(c for c in data.comments_of_chapter(self.SLUG, 3) if c.replies)
        self.client.post(
            reverse('core:comment_create', kwargs={'slug': self.SLUG}),
            {'text': 'Келісемін.', 'chapter': '3', 'parent': str(top.pk)})
        reply = StoryComment.objects.get(text='Келісемін.')
        self.assertEqual(reply.parent_id, top.pk)

    def test_reply_to_a_reply_is_rejected(self):
        # BR-30: ответ сам уже на верхнем уровне не лежит, одна вложенность.
        existing_reply = next(
            c.replies[0] for c in data.comments_of_chapter(self.SLUG, 3) if c.replies)
        before = StoryComment.objects.count()
        self.client.post(
            reverse('core:comment_create', kwargs={'slug': self.SLUG}),
            {'text': 'Жауапқа жауап.', 'chapter': '3', 'parent': str(existing_reply.pk)})
        self.assertEqual(StoryComment.objects.count(), before)

    def test_parent_from_another_story_is_rejected(self):
        # 'kronchessii' — басқа шығарма; сырттан parent id жіберу арқылы
        # бөтен ағашқа жауап жабыстыруға болмайды.
        foreign_parent = StoryComment.objects.filter(
            story__slug='kronchessii', parent__isnull=True).first()
        before = StoryComment.objects.count()
        self.client.post(
            reverse('core:comment_create', kwargs={'slug': self.SLUG}),
            {'text': 'Бөтен ағашқа.', 'chapter': '3', 'parent': str(foreign_parent.pk)})
        self.assertEqual(StoryComment.objects.count(), before)

    def test_empty_text_saves_nothing(self):
        before = StoryComment.objects.count()
        self.client.post(
            reverse('core:comment_create', kwargs={'slug': self.SLUG}),
            {'text': '   ', 'chapter': '3'})
        self.assertEqual(StoryComment.objects.count(), before)

    def test_guest_post_saves_nothing(self):
        from django.test import Client
        guest = Client()
        before = StoryComment.objects.count()
        guest.post(
            reverse('core:comment_create', kwargs={'slug': self.SLUG}),
            {'text': 'Қонақтың пікірі.', 'chapter': '3'})
        self.assertEqual(StoryComment.objects.count(), before)


class CommentDeleteRemovesIt(TestCase):

    SLUG = 'dalney-berega'

    def test_owner_can_delete_their_own_top_level_comment_and_its_replies(self):
        # Верхнеуровневый комментарий с ответами — удаление каскадное,
        # счётчик работы обязан упасть на число всех удалённых строк, не
        # только на одну.
        top = next(c for c in data.comments_of_chapter(self.SLUG, 3) if c.replies)
        removed_ids = [top.pk] + [r.pk for r in top.replies]
        login_as(self.client, top.author.username)
        story = Story.objects.get(slug=self.SLUG)
        before = story.comments

        r = self.client.post(reverse(
            'core:comment_delete', kwargs={'slug': self.SLUG, 'comment_id': top.pk}))

        self.assertFalse(StoryComment.objects.filter(pk__in=removed_ids).exists())
        story.refresh_from_db()
        self.assertEqual(story.comments, before - len(removed_ids))
        self.assertRedirects(
            r, reverse('core:story_detail', kwargs={'slug': self.SLUG}) + '?chapter=3')

    def test_get_does_not_delete(self):
        own = next(c for c in data.comments_of_chapter(self.SLUG, 3) if not c.replies)
        login_as(self.client, own.author.username)
        self.client.get(reverse(
            'core:comment_delete', kwargs={'slug': self.SLUG, 'comment_id': own.pk}))
        self.assertTrue(StoryComment.objects.filter(pk=own.pk).exists())

    def test_cannot_delete_someone_elses_comment(self):
        target = next(c for c in data.comments_of_chapter(self.SLUG, 3) if not c.replies)
        other = next(a.username for a in data.all_authors()
                    if a.username != target.author.username)
        login_as(self.client, other)
        self.client.post(reverse(
            'core:comment_delete', kwargs={'slug': self.SLUG, 'comment_id': target.pk}))
        self.assertTrue(StoryComment.objects.filter(pk=target.pk).exists())

    def test_guest_cannot_delete(self):
        target = data.comments_of_chapter(self.SLUG, 3)[0]
        self.client.post(reverse(
            'core:comment_delete', kwargs={'slug': self.SLUG, 'comment_id': target.pk}))
        self.assertTrue(StoryComment.objects.filter(pk=target.pk).exists())


class ReadingCountsAsAView(TestCase):
    """Оқылым засчитывается при открытии работы (FR-STORY-01, DEC-36).

    До этого счётчик в базу клал только сид: `views` и `recent_views` не
    росли ни от одного захода. То есть «Қазір танымал» — дефолтная
    сортировка каталога — навсегда показывала порядок демо-данных, а
    автору портал сообщал число, к которому его читатели не имели
    отношения.
    """

    SLUG = STORY_SLUG

    def _url(self, **params):
        url = reverse('core:story_detail', kwargs={'slug': self.SLUG})
        return url + ('?' + '&'.join(f'{k}={v}' for k, v in params.items())
                      if params else '')

    def _counters(self):
        s = Story.objects.get(slug=self.SLUG)
        return s.views, s.recent_views

    def test_first_visit_moves_both_counters(self):
        before = self._counters()
        self.client.get(self._url())
        views, recent = self._counters()
        self.assertEqual(views, before[0] + 1)
        self.assertEqual(recent, before[1] + 1)

    def test_the_page_shows_the_visit_it_just_counted(self):
        """Цифра, отставшая на один заход, читается как «меня не засчитали»."""
        before = self._counters()[0]
        r = self.client.get(self._url())
        self.assertEqual(r.context['story'].views, before + 1)

    def test_reload_and_chapter_hopping_count_once(self):
        before = self._counters()[0]
        self.client.get(self._url())
        self.client.get(self._url())
        self.client.get(self._url(chapter=3))
        self.client.get(self._url(chapter=7))
        self.assertEqual(self._counters()[0], before + 1)

    def test_another_reader_counts_again(self):
        from django.test import Client

        before = self._counters()[0]
        self.client.get(self._url())
        Client().get(self._url())
        self.assertEqual(self._counters()[0], before + 2)

    def test_the_author_does_not_read_themselves_into_the_numbers(self):
        story = Story.objects.get(slug=self.SLUG)
        login_as(self.client, story.author.username)
        before = self._counters()
        self.client.get(self._url())
        self.assertEqual(self._counters(), before)

    def test_reading_does_not_pass_for_editing(self):
        """`updated_at` двигает автор, а не читатель: «өзгертілген бүгін»
        после чужого захода — неправда, и она уезжает в сортировку."""
        before = Story.objects.get(slug=self.SLUG).updated_at
        self.client.get(self._url())
        self.assertEqual(Story.objects.get(slug=self.SLUG).updated_at, before)

    def test_unknown_story_counts_nothing(self):
        r = self.client.get(reverse('core:story_detail',
                                    kwargs={'slug': 'no-such-story'}))
        self.assertEqual(r.status_code, 200)


class ReadingRemembersWhereYouStopped(TestCase):
    """Закладка двигается по мере чтения (FR-HOME-02).

    `ReadingProgress` до этого создавал только сид: «Оқуды жалғастыру» на
    главной всегда указывало в одно и то же место, сколько бы читатель ни
    читал. Закладка — вещь личная, поэтому у гостя её нет вовсе.
    """

    SLUG = STORY_SLUG
    READER = 'lonely_reader'

    def setUp(self):
        login_as_newcomer(self.client, self.READER)

    def _url(self, chapter=None):
        url = reverse('core:story_detail', kwargs={'slug': self.SLUG})
        return f'{url}?chapter={chapter}' if chapter else url

    def _progress(self):
        return ReadingProgress.objects.filter(
            user__username=self.READER, story__slug=self.SLUG).first()

    def test_opening_a_chapter_leaves_a_bookmark(self):
        self.assertIsNone(self._progress())
        self.client.get(self._url(5))
        progress = self._progress()
        self.assertIsNotNone(progress)
        self.assertEqual(progress.current_chapter, 5)
        self.assertEqual(progress.last_read_on, timezone.localdate())

    def test_the_bookmark_moves_and_does_not_multiply(self):
        for chapter in (2, 5, 9):
            self.client.get(self._url(chapter))
        self.assertEqual(self._progress().current_chapter, 9)
        self.assertEqual(
            ReadingProgress.objects.filter(user__username=self.READER).count(), 1)

    def test_time_left_counts_the_chapters_still_ahead(self):
        chapters = data.chapters_of(self.SLUG)
        self.client.get(self._url(3))
        expected = sum(c.char_count for c in chapters if c.number > 3)
        self.assertEqual(self._progress().minutes_left, -(-expected // 900))

    def test_the_last_chapter_leaves_nothing_ahead(self):
        self.client.get(self._url(len(data.chapters_of(self.SLUG))))
        self.assertEqual(self._progress().minutes_left, 0)

    def test_the_first_visit_is_not_a_return(self):
        """Закладка пишется после резолва главы, а не до него: иначе первое
        знакомство с работой выглядело бы возвращением к ней, и тизер
        первой главы не показывался бы ни разу."""
        r = self.client.get(self._url())
        self.assertContains(r, 'Жалғастыру')
        self.assertFalse(r.context['has_progress'])

    def test_the_next_visit_opens_where_it_stopped(self):
        self.client.get(self._url(6))
        r = self.client.get(self._url())
        self.assertEqual(r.context['chapter_number'], 6)
        self.assertTrue(r.context['has_progress'])

    def test_a_guest_gets_no_bookmark(self):
        self.client.logout()
        self.client.get(self._url(4))
        self.assertFalse(ReadingProgress.objects.filter(story__slug=self.SLUG,
                                                        user__username=self.READER).exists())
