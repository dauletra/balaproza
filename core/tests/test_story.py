"""STORY — страница произведения: чтение, отклик, разговор.

Отдельного маршрута `/read/` нет (DEC-30): глава открывается на той же
странице через `?chapter=N`, и потому здесь же живут все следы чтения —
счётчик оқылым, закладка, полка библиотеки, реакции, опрос и
комментарии. Все пять до Ф15 писались только сидом.
"""

from pathlib import Path

from core.tests import factories as make
from core.tests.base import TestCase, login_as, login_as_newcomer, user
from django.test import Client
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

    def test_an_unknown_slug_is_not_a_page(self):
        """404, а не 200 с карточкой «табылмады»: выдуманный slug — не
        страница, и поисковику незачем считать его живой."""
        response = self.client.get(
            reverse('core:story_detail', kwargs={'slug': 'no-such-story'}))
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, 'Аннотация', status_code=404)


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

    def test_the_button_states_what_the_shelf_says(self):
        guest = self.client.get(self._url(self.IN_LIBRARY))
        self.assertContains(guest, 'Сақтау')
        self.assertContains(guest, reverse('core:login'))

        login_as(self.client)
        saved = self.client.get(self._url(self.IN_LIBRARY))
        self.assertContains(saved, 'Сақталды')
        self.assertContains(saved, reverse('core:library_toggle',
                                           kwargs={'slug': self.IN_LIBRARY}))
        unsaved = self.client.get(self._url(self.NOT_IN_LIBRARY))
        self.assertContains(unsaved, 'Сақтау')
        self.assertNotContains(unsaved, 'Сақталды')

    def test_it_answers_presence_and_does_not_pick_a_shelf(self):
        """Повторное нажатие снимает и то, что лежало на «оқу үстінде»."""
        login_as(self.client)
        self.assertRedirects(self._toggle(self.NOT_IN_LIBRARY),
                             self._url(self.NOT_IN_LIBRARY))
        self.assertEqual(self._entry(self.NOT_IN_LIBRARY).kind, 'saved')
        self._toggle(self.NOT_IN_LIBRARY)
        self.assertIsNone(self._entry(self.NOT_IN_LIBRARY))

        self.assertEqual(self._entry(self.IN_LIBRARY).kind, 'reading')
        self._toggle(self.IN_LIBRARY)
        self.assertIsNone(self._entry(self.IN_LIBRARY))

    def test_neither_a_guest_nor_a_get_writes_to_a_shelf(self):
        before = LibraryEntry.objects.count()
        self._toggle(self.NOT_IN_LIBRARY)
        self.assertEqual(LibraryEntry.objects.count(), before)
        login_as(self.client)
        self.client.get(reverse('core:library_toggle',
                                kwargs={'slug': self.NOT_IN_LIBRARY}))
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

    def test_reading_moves_the_work_from_shelf_to_shelf(self):
        """Строка `done` предлагает «Қайта оқу», и после нажатия полка
        обязана описывать то, что происходит."""
        self.assertIsNone(self._kind())
        self._open(2)
        self.assertEqual(self._kind(), 'reading')
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
    добавляли свой padding.

    Правила и компонент живут в статике, а не в разметке страницы, поэтому
    проверяются по своим файлам; на странице проверяется, что она их
    подключает и ставит нужные классы."""

    ROOT = Path(__file__).resolve().parent.parent.parent
    CSS = (ROOT / 'static_src' / 'input.css').read_text(encoding='utf-8')
    JS = (ROOT / 'static' / 'js' / 'reader.js').read_text(encoding='utf-8')

    def setUp(self):
        self.response = self.client.get(
            reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.html = self.response.content.decode()

    def test_the_measure_is_pinned_in_ch_and_the_card_goes_full_bleed(self):
        self.assertIn('max-width: 68ch', self.CSS)
        self.assertContains(self.response, '-mx-4')       # гасит px-4 контейнера
        self.assertContains(self.response, 'sm:mx-0')
        self.assertIn('margin-inline: -1rem', self.CSS)   # подложка темы
        self.assertIn('overflow-wrap: break-word', self.CSS)
        # Кегль и интерлиньяж — разные свойства: раньше обе оси трогали
        # `line-height`, и порядок правил в файле решал, чья возьмёт.
        self.assertIn('.reader-size-base  { font-size: 17px; }', self.CSS)
        self.assertIn('.reader-lead-tight { line-height: 1.6; }', self.CSS)
        # На тексте в три абзаца ни мера, ни панель не проявляются.
        self.assertGreater(len(data.chapter_of(STORY_SLUG, 3).body), 2000)

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
                self.assertIn(key, self.JS)

    def test_the_component_is_registered_before_alpine_starts(self):
        """`defer` исполняет в порядке документа: reader.js обязан стоять
        выше alpine.min.js, иначе `alpine:init` уже прошёл и `storyReader`
        останется неизвестным именем — компонент молча не поднимется."""
        self.assertContains(self.response, 'js/reader.js')
        self.assertLess(self.html.index('js/reader.js'),
                        self.html.index('vendor/alpine.min.js'))
        self.assertNotIn('<style', self.html[self.html.index('</head>'):])

    def test_the_reading_panel_replaces_the_mobile_nav(self):
        """Две плавающие пилюли на 375px наехали бы друг на друга
        (docs/ui.md)."""
        self.assertContains(self.response, 'Оқу панелі')
        self.assertContains(self.response, 'Бөлімдер тізімі')
        self.assertContains(self.response, 'chaptersOpen')
        self.assertContains(self.response, 'reading-mode')


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
        self.assertEqual(data.reading_progress_of(user('aidana')).story.slug, STORY_SLUG)
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

    def test_a_first_vote_is_recorded_and_a_repeat_takes_it_back(self):
        login_as(self.client)
        likes_before, kind_before = self._story_likes(), self._kind_count('kuldim')

        self.client.post(self._url(), {'kind': 'kuldim'})
        self.assertEqual(self._kind_count('kuldim'), kind_before + 1)
        self.assertEqual(self._story_likes(), likes_before + 1)
        self.assertTrue(ChapterReactionVote.objects.filter(
            user__username='aidana', chapter__story__slug=STORY_SLUG,
            chapter__number=self.CHAPTER, kind='kuldim').exists())

        self.client.post(self._url(), {'kind': 'kuldim'})   # повтор снимает
        self.assertEqual(self._kind_count('kuldim'), kind_before)
        self.assertEqual(self._story_likes(), likes_before)
        self.assertFalse(ChapterReactionVote.objects.filter(
            user__username='aidana', chapter__story__slug=STORY_SLUG,
            chapter__number=self.CHAPTER).exists())

    def test_another_kind_replaces_the_vote_without_counting_twice(self):
        login_as(self.client)
        likes_before = self._story_likes()
        kuldim_before = self._kind_count('kuldim')
        jyladym_before = self._kind_count('jyladym')

        self.client.post(self._url(), {'kind': 'kuldim'})
        self.client.post(self._url(), {'kind': 'jyladym'})

        self.assertEqual(self._kind_count('kuldim'), kuldim_before)
        self.assertEqual(self._kind_count('jyladym'), jyladym_before + 1)
        self.assertEqual(self._story_likes(), likes_before + 1)  # голос один
        vote = ChapterReactionVote.objects.get(
            user__username='aidana', chapter__story__slug=STORY_SLUG,
            chapter__number=self.CHAPTER)
        self.assertEqual(vote.kind, 'jyladym')

    def test_neither_a_guest_nor_an_invented_kind_votes(self):
        likes_before = self._story_likes()
        self.client.post(self._url(), {'kind': 'kuldim'})
        self.assertEqual(self._story_likes(), likes_before)
        login_as(self.client)
        self.client.post(self._url(), {'kind': 'not-a-real-reaction'})
        self.assertFalse(ChapterReactionVote.objects.exists())

    def test_the_page_and_the_helper_report_the_picked_kind(self):
        """`Chapter.my_reaction` и `mine` в `reactions_of` отражают голос
        именно вошедшего — не жёсткий `False`, как до записи."""
        login_as(self.client)
        self.client.post(self._url(), {'kind': 'shabyt'})

        chapter = data.chapter_of(STORY_SLUG, self.CHAPTER, user('aidana'))
        self.assertEqual(chapter.my_reaction, 'shabyt')
        picked = [i['reaction'].slug for i in data.reactions_of(chapter) if i['mine']]
        self.assertEqual(picked, ['shabyt'])
        url = (reverse('core:story_detail', kwargs={'slug': STORY_SLUG})
               + f'?chapter={self.CHAPTER}')
        self.assertContains(self.client.get(url),
                            'Автор сенің реакцияңды көреді.')


class ChapterPollStates(TestCase):
    """FR-STORY-13 / DEC-33: необязательный опрос автора под главой."""

    OPEN_CHAPTER = 12    # последняя вышедшая — ответа ещё нет
    CLOSED_CHAPTER = 3   # следующая глава вышла, опрос закрыт

    def _get(self, chapter):
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG}) + f'?chapter={chapter}'
        return self.client.get(url)

    def test_an_open_poll_asks_its_own_question(self):
        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER)
        self.assertFalse(poll.closed)
        self.assertEqual(100, sum(r['percent'] for r in poll.results))
        self.assertContains(self._get(self.OPEN_CHAPTER), poll.question)
        # Цельный текст тоже может нести опрос.
        self.assertContains(
            self.client.get(reverse('core:story_detail',
                                    kwargs={'slug': 'tunge-deiin'})),
            'Автордың сұрағы')

    def test_it_closes_when_the_next_chapter_ships_and_points_at_the_answer(self):
        poll = data.poll_of(STORY_SLUG, self.CLOSED_CHAPTER)
        self.assertTrue(poll.closed)
        self.assertEqual(self.CLOSED_CHAPTER + 1, poll.answer_chapter)
        closed = self._get(self.CLOSED_CHAPTER)
        self.assertContains(closed, 'Сұрақ жабылды')
        self.assertContains(closed, f'{self.CLOSED_CHAPTER + 1}-бөлімде')

    def test_a_guest_votes_through_login_and_a_reader_gets_the_ballot(self):
        guest = self._get(self.OPEN_CHAPTER)
        self.assertContains(guest, 'Жауап беру үшін')
        self.assertContains(guest, reverse('core:login'))
        login_as(self.client)
        signed_in = self._get(self.OPEN_CHAPTER)
        self.assertContains(signed_in, 'Дұрыс жауабы жоқ')
        self.assertNotContains(signed_in, 'Жауап беру үшін')

    def test_a_chapter_without_a_poll_shows_nothing_at_all(self):
        """Опрос необязателен — его отсутствие не пустое состояние
        (BR-POLL-01). Декоративный блок из трёх захардкоженных вариантов,
        одинаковых на всех произведениях, снят DEC-33."""
        self.assertIsNone(data.poll_of(STORY_SLUG, 5))
        self.assertNotContains(self._get(5), 'Автордың сұрағы')
        first = self._get(1)
        self.assertNotContains(first, 'Батыл қадам')
        self.assertNotContains(first, 'Кейіпкердің келесі таңдауы')


class ChapterPollVoting(TestCase):
    """Ф15 Этап 4: голос в открытом опросе — один на опрос, не меняется
    (BR-POLL-*); закрытый опрос голос не принимает (BR-POLL-05)."""

    OPEN_CHAPTER = 12    # последняя вышедшая — ответа ещё нет
    CLOSED_CHAPTER = 3   # следующая глава вышла, опрос закрыт

    def _url(self, chapter):
        return reverse('core:poll_vote', kwargs={'slug': STORY_SLUG, 'chapter': chapter})

    def test_the_first_vote_is_recorded_and_the_ballot_becomes_results(self):
        login_as(self.client)
        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER)
        option = poll.options[0]
        before = option.votes

        self.client.post(self._url(self.OPEN_CHAPTER), {'option': option.slug})

        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER, user('aidana'))
        self.assertEqual(poll.my_vote, option.slug)
        self.assertEqual(poll.option_set.get(slug=option.slug).votes, before + 1)
        self.assertTrue(PollVote.objects.filter(
            user__username='aidana', poll=poll, option__slug=option.slug).exists())

        url = (reverse('core:story_detail', kwargs={'slug': STORY_SLUG})
               + f'?chapter={self.OPEN_CHAPTER}')
        voted = self.client.get(url)
        self.assertContains(voted, 'сенің жауабың')
        self.assertNotContains(voted, 'Дұрыс жауабы жоқ — тек сенің болжамың.')

    def test_a_second_vote_does_not_change_the_first(self):
        login_as(self.client)
        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER)
        first, second = poll.options[0], poll.options[1]
        second_before = second.votes

        self.client.post(self._url(self.OPEN_CHAPTER), {'option': first.slug})
        self.client.post(self._url(self.OPEN_CHAPTER), {'option': second.slug})

        poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER, user('aidana'))
        self.assertEqual(poll.my_vote, first.slug)
        self.assertEqual(poll.option_set.get(slug=second.slug).votes, second_before)
        self.assertEqual(
            PollVote.objects.filter(user__username='aidana', poll=poll).count(), 1)

    def test_a_guest_a_closed_poll_and_an_invented_option_are_all_refused(self):
        open_poll = data.poll_of(STORY_SLUG, self.OPEN_CHAPTER)
        self.client.post(self._url(self.OPEN_CHAPTER),
                         {'option': open_poll.options[0].slug})
        self.assertFalse(PollVote.objects.exists())

        login_as(self.client)
        closed = data.poll_of(STORY_SLUG, self.CLOSED_CHAPTER)
        self.assertTrue(closed.closed)
        option = closed.options[0]
        before = option.votes
        self.client.post(self._url(self.CLOSED_CHAPTER), {'option': option.slug})
        self.assertEqual(closed.option_set.get(slug=option.slug).votes, before)

        self.client.post(self._url(self.OPEN_CHAPTER),
                         {'option': 'not-a-real-option'})
        self.assertFalse(PollVote.objects.exists())


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

    def test_it_rises_above_the_comments_once_there_is_nothing_left_to_read(self):
        mid = self._html(3)
        self.assertLess(mid.index('пікірлері'), mid.index('Басқа шығармалар'))
        for html in (self._html(self.LAST),
                     self.client.get(reverse('core:story_detail',
                                             kwargs={'slug': 'tunge-deiin'})
                                     ).content.decode()):
            self.assertLess(html.index('Басқа шығармалар'), html.index('пікірлері'))

    def test_the_block_is_rendered_exactly_once(self):
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

    def test_a_guest_gets_only_the_link_item(self):
        response = self._get()
        self.assertContains(response, 'Пікір мәзірі')
        self.assertContains(response, 'Сілтемені көшіру')
        self.assertNotContains(response, 'Шағым жіберу')
        self.assertNotContains(response, "target: 'comment:")

    def test_a_reader_reports_a_stranger_and_deletes_their_own(self):
        """На свой комментарий жаловаться некому — его удаляют."""
        login_as(self.client)
        response = self._get()
        self.assertContains(response, 'Шағым жіберу')
        self.assertContains(response, "target: 'comment:")
        html = response.content.decode()
        own = next(c for c in data.comments_of_chapter(STORY_SLUG, 3)
                   if c.belongs_to('aidana'))
        block = html[html.index(f'id="comment-{own.id}"'):]
        block = block[:block.index('</article>')]
        self.assertIn('Жою', block)
        self.assertNotIn('Шағым жіберу', block)

    def test_the_anchor_is_the_primary_key(self):
        """Скопированная ссылка обязана работать и завтра.

        В стабе якорь считался из текста crc32-суммой — потому что ключа
        не было, а `hash()` рандомизируется от запуска к запуску. Теперь
        якорь и есть первичный ключ строки: устойчивее не бывает.
        """
        comment = data.comments_of_chapter(STORY_SLUG, 3)[0]
        self.assertIsInstance(comment.id, int)
        self.assertContains(self._get(), f'id="comment-{comment.id}"')

    def test_the_icons_say_what_they_mean(self):
        """Три точки — иконка контейнера («ещё варианты»), а не действия.

        На «Шағым жіберу» они стояли в двух местах сразу, и в меню
        комментария получалось «ещё варианты → ещё варианты». Жалоба
        помечена флажком, модерация — щитом: галочка говорит «готово»,
        а фраза — «защищено правилами».
        """
        login_as(self.client)
        html = self._get().content.decode()
        self.assertIn('#icon-flag', html)
        self.assertNotIn('#icon-dots-vertical', html)
        trigger_at = html.index('aria-label="Пікір мәзірі"')
        self.assertIn('#icon-dots-horizontal', html[trigger_at:trigger_at + 400])
        notice_at = html.index('модерация ережелерімен')
        self.assertIn('#icon-shield', html[notice_at - 500:notice_at])


class CommentLike(TestCase):
    """BR-31: лайк комментария переключается (Ф15, POST), гость уходит на логин."""

    def test_a_guest_sees_the_button_and_is_gated_to_login(self):
        response = self.client.get(
            reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        self.assertContains(response, 'aria-label="Ұнату"')
        self.assertContains(response, reverse('core:login'))
        comment = data.comments_of_chapter(STORY_SLUG, 1)[0]
        before = comment.likes
        self.client.post(reverse('core:comment_like',
                                 kwargs={'slug': STORY_SLUG,
                                         'comment_id': comment.pk}))
        comment.refresh_from_db()
        self.assertEqual(comment.likes, before)

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


class CommentReplies(TestCase):
    """BR-30: один уровень ответов — на ответ ответить нельзя."""

    def test_the_reply_form_belongs_to_the_signed_in(self):
        url = reverse('core:story_detail', kwargs={'slug': STORY_SLUG})
        guest = self.client.get(url)
        self.assertContains(guest, 'Жауап беру')
        self.assertNotContains(guest, 'пікіріне жауап жаз')
        login_as(self.client)
        self.assertContains(self.client.get(url), 'пікіріне жауап жаз')

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

    def test_the_name_leads_to_the_profile_and_no_link_is_dead(self):
        response = self.client.get(
            reverse('core:story_detail', kwargs={'slug': STORY_SLUG}))
        author = data.comments_of_chapter(STORY_SLUG, 1)[0].author
        self.assertContains(response, reverse('core:profile_other',
                                              kwargs={'username': author.username}))
        self.assertNotContains(response, '<a href="#" class="font-sans text-[13px]')


class StoryLinksBackToItsCollections(TestCase):
    """DEC-31: дочитавший ищет «ещё такого же». Жанр отвечает на это хуже
    всего — две фэнтези бывают совсем разными; подборка собрана по состоянию."""

    def setUp(self):
        self.response = self.client.get(
            reverse('core:story_detail', kwargs={'slug': 'tunge-deiin'}))
        self.html = self.response.content.decode()

    def test_the_block_lists_every_collection_and_stands_above_the_genre(self):
        """Редакционная подборка сильнее автоматической выдачи по жанру."""
        collections = data.collections_of(data.story_by_slug('tunge-deiin'))
        self.assertTrue(collections)
        self.assertContains(self.response, 'Мына жинақтарда бар')
        for collection in collections:
            with self.subTest(collection=collection.slug):
                self.assertContains(self.response,
                                    f'/collections/{collection.slug}/')
        self.assertLess(self.html.index('Мына жинақтарда бар'),
                        self.html.index('Басқа шығармалар'))

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

    def test_a_forged_parent_an_empty_text_and_a_guest_save_nothing(self):
        url = reverse('core:comment_create', kwargs={'slug': self.SLUG})
        # BR-30: ответ сам уже на верхнем уровне не лежит, одна вложенность.
        existing_reply = next(c.replies[0]
                              for c in data.comments_of_chapter(self.SLUG, 3)
                              if c.replies)
        # 'kronchessii' — другая работа: приклеить ответ к чужому дереву,
        # прислав его parent id, нельзя.
        foreign_parent = StoryComment.objects.filter(
            story__slug='kronchessii', parent__isnull=True).first()
        cases = {
            'ответ на ответ': {'text': 'Жауапқа жауап.', 'chapter': '3',
                               'parent': str(existing_reply.pk)},
            'чужое дерево': {'text': 'Бөтен ағашқа.', 'chapter': '3',
                             'parent': str(foreign_parent.pk)},
            'пустой текст': {'text': '   ', 'chapter': '3'},
        }
        before = StoryComment.objects.count()
        for label, payload in cases.items():
            with self.subTest(case=label):
                self.client.post(url, payload)
                self.assertEqual(StoryComment.objects.count(), before)
        Client().post(url, {'text': 'Қонақтың пікірі.', 'chapter': '3'})
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

    def test_neither_a_get_nor_a_stranger_nor_a_guest_deletes_anything(self):
        target = next(c for c in data.comments_of_chapter(self.SLUG, 3)
                      if not c.replies)
        url = reverse('core:comment_delete',
                      kwargs={'slug': self.SLUG, 'comment_id': target.pk})

        login_as(self.client, target.author.username)
        self.client.get(url)
        self.assertTrue(StoryComment.objects.filter(pk=target.pk).exists())

        stranger = next(a.username for a in data.all_authors()
                        if a.username != target.author.username)
        login_as(self.client, stranger)
        self.client.post(url)
        self.assertTrue(StoryComment.objects.filter(pk=target.pk).exists())

        Client().post(url)
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

    def test_a_first_visit_moves_both_counters_and_the_page_shows_it(self):
        """Цифра, отставшая на один заход, читается как «меня не засчитали»."""
        views_before, recent_before = self._counters()
        response = self.client.get(self._url())
        views, recent = self._counters()
        self.assertEqual(views, views_before + 1)
        self.assertEqual(recent, recent_before + 1)
        self.assertEqual(response.context['story'].views, views_before + 1)

    def test_one_reader_counts_once_however_much_they_hop(self):
        before = self._counters()[0]
        self.client.get(self._url())
        self.client.get(self._url())
        self.client.get(self._url(chapter=3))
        self.client.get(self._url(chapter=7))
        self.assertEqual(self._counters()[0], before + 1)
        # А другой — считается снова.
        Client().get(self._url())
        self.assertEqual(self._counters()[0], before + 2)

    def test_the_author_does_not_read_themselves_into_the_numbers(self):
        story = Story.objects.get(slug=self.SLUG)
        login_as(self.client, story.author.username)
        before = self._counters()
        self.client.get(self._url())
        self.assertEqual(self._counters(), before)

    def test_reading_passes_neither_for_editing_nor_for_a_story_that_is_gone(self):
        """`updated_at` двигает автор, а не читатель: «өзгертілген бүгін»
        после чужого захода — неправда, и она уезжает в сортировку."""
        before = Story.objects.get(slug=self.SLUG).updated_at
        self.client.get(self._url())
        self.assertEqual(Story.objects.get(slug=self.SLUG).updated_at, before)
        self.assertEqual(
            self.client.get(reverse('core:story_detail',
                                    kwargs={'slug': 'no-such-story'})).status_code,
            404)


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

    def test_the_bookmark_appears_moves_and_does_not_multiply(self):
        self.assertIsNone(self._progress())
        self.client.get(self._url(5))
        progress = self._progress()
        self.assertEqual(progress.current_chapter, 5)
        self.assertEqual(progress.last_read_on, timezone.localdate())
        for chapter in (2, 9):
            self.client.get(self._url(chapter))
        self.assertEqual(self._progress().current_chapter, 9)
        self.assertEqual(
            ReadingProgress.objects.filter(user__username=self.READER).count(), 1)

    def test_time_left_counts_the_chapters_still_ahead(self):
        chapters = data.chapters_of(self.SLUG)
        self.client.get(self._url(3))
        expected = sum(c.char_count for c in chapters if c.number > 3)
        self.assertEqual(self._progress().minutes_left, -(-expected // 900))
        self.client.get(self._url(len(chapters)))
        self.assertEqual(self._progress().minutes_left, 0)

    def test_the_first_visit_is_not_a_return_but_the_next_one_is(self):
        """Закладка пишется после резолва главы, а не до него: иначе первое
        знакомство с работой выглядело бы возвращением к ней, и тизер
        первой главы не показывался бы ни разу."""
        first = self.client.get(self._url())
        self.assertContains(first, 'Жалғастыру')
        self.assertFalse(first.context['has_progress'])

        self.client.get(self._url(6))
        back = self.client.get(self._url())
        self.assertEqual(back.context['chapter_number'], 6)
        self.assertTrue(back.context['has_progress'])

    def test_a_guest_gets_no_bookmark(self):
        self.client.logout()
        self.client.get(self._url(4))
        self.assertFalse(ReadingProgress.objects.filter(story__slug=self.SLUG,
                                                        user__username=self.READER).exists())
