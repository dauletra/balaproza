"""STORY — страница произведения: решение «читать ли» и само чтение.

Отдельного маршрута `/read/` нет: глава открывается на той же странице
через `?chapter=N`. Поэтому здесь и решение читателя (о чём работа, что
откроет главная кнопка, на какой я полке), и сама поверхность чтения.

Следы чтения — оқылым, закладка, полка — в `test_reading.py`, отклик
(реакции и опрос) — в `test_reactions.py`, разговор — в
`test_comments.py`.
"""


from pathlib import Path

from core.tests import factories as make
from core.tests.base import STORY_SLUG, TestCase, login_as, login_as_newcomer, user
from django.test import Client
from django.urls import reverse

from core import data
from core.models import (
    ChapterReactionVote,
    LibraryEntry,
    ReadingProgress,
    Story,
    StoryComment,
    StoryView,
)


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

    def test_the_first_chapter_opens_in_full(self):
        """Чтение идёт inline: отдельного маршрута `/read/` нет,
        и старого scrollspy-блока тоже. Текст не обрезается —
        последнее предложение главы обязано попасть в ответ целиком."""
        body = data.chapter_of(STORY_SLUG, 1).body
        self.assertContains(self.response, data.chapter_of(STORY_SLUG, 1).title)
        self.assertContains(self.response, '1-бөлім')
        self.assertContains(self.response, body.strip().rsplit('\n', 1)[-1])
        self.assertNotContains(self.response, 'expanded: false')
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


class PendingTagsAreVisibleOnlyToTheirAuthor(TestCase):
    """Тег ещё не прошёл модератора. Автор обязан видеть свой —
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

    def test_removal_survives_landing_back_on_the_page(self):
        """Снятие обязано пережить редирект, который его же и показывает.

        Кнопка отвечает POST'ом и редиректит на страницу произведения, а та
        кладёт читаемую работу на «оқу үстінде». Пока полку двигал
        сам факт открытия, запись воскресала раньше, чем читатель видел
        результат нажатия: снять работу с полки было нельзя ни на одном
        произведении, у которого есть главы. Держалось это на том, что
        единственной фикстурой «не в библиотеке» была работа **без глав**.
        """
        login_as(self.client)
        page = self._url(self.NOT_IN_LIBRARY)

        self.client.post(reverse('core:library_toggle',
                                 kwargs={'slug': self.NOT_IN_LIBRARY}), follow=True)
        self.assertEqual(self._entry(self.NOT_IN_LIBRARY).kind, 'saved')
        # Взгляд на страницу не перебивает ручную полку на «оқу үстінде».
        self.client.get(page)
        self.assertEqual(self._entry(self.NOT_IN_LIBRARY).kind, 'saved')

        self.client.post(reverse('core:library_toggle',
                                 kwargs={'slug': self.NOT_IN_LIBRARY}), follow=True)
        self.assertIsNone(self._entry(self.NOT_IN_LIBRARY))
        self.client.get(page)
        self.assertIsNone(self._entry(self.NOT_IN_LIBRARY))

        # А настоящее продвижение по главам полку возвращает.
        self.client.get(page, {'chapter': 2})
        self.assertEqual(self._entry(self.NOT_IN_LIBRARY).kind, 'reading')

    def test_neither_a_guest_nor_a_get_writes_to_a_shelf(self):
        before = LibraryEntry.objects.count()
        self._toggle(self.NOT_IN_LIBRARY)
        self.assertEqual(LibraryEntry.objects.count(), before)
        login_as(self.client)
        self.client.get(reverse('core:library_toggle',
                                kwargs={'slug': self.NOT_IN_LIBRARY}))
        self.assertEqual(LibraryEntry.objects.count(), before)


class TheReadingSurfaceIsBuiltForAPhone(TestCase):
    """На 375px контейнер `px-4` и карточка `p-6`
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

    def test_both_pills_sit_at_the_same_height_above_the_home_gesture(self):
        """Панель чтения встаёт на место меню, поэтому её нижний отступ
        обязан совпадать с меню дословно — иначе подмена одной пилюли
        другой читается прыжком. Обе несут `env(safe-area-inset-bottom)`:
        на iPhone без кнопки внизу 34px отданы жесту «домой», и голый
        `bottom-4` сажал пилюлю на индикатор (docs/ui.md)."""
        offset = 'bottom-[calc(1rem+env(safe-area-inset-bottom))]'
        self.assertEqual(self.html.count(offset), 2)


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
        self.assertLess(html.index('Басқа шығармалар'),
                        html.index(f"report_url: '/story/{STORY_SLUG}/report/"))


class RelatedStoriesCoverAllPublicStatuses(TestCase):
    """«Басқа шығармалар» не должен состоять из одних `Published`.

    Блок сужался литералом `status='Published'` поверх уже публичной
    выдачи, и это выкидывало из рекомендаций **все** сериалы —
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
            'выдача снова сужена до литерала Published',
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


class StoryLinksBackToItsCollections(TestCase):
    """Дочитавший ищет «ещё такого же». Жанр отвечает на это хуже
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


class AnUnpublishedWorkExistsOnlyForItsAuthorAndTheModerator(TestCase):
    """Страница произведения не смотрела на статус вообще: черновик
    и работа на модерации отдавались целиком любому, кто открыл адрес, —
    включая гостя. Слаг при этом собирается из названия (`slugify_kz`),
    то есть подбирается, а не только утекает ссылкой.

    Проверяется не «страница пустая», а «страницы нет»: 404, тот же ответ,
    что у выдуманного адреса. Разница между «нельзя» и «не существует»
    здесь важна — первое подтверждает, что работа есть.
    """

    def setUp(self):
        super().setUp()
        self.author = make.user()
        self.draft = make.story(author=self.author, status='NotPublished',
                                chapters=1, slug='audit-draft')
        self.queued = make.story(author=self.author, status='OnModeration',
                                 chapters=1, slug='audit-queued')
        self.public = make.story(author=self.author, status='Published',
                                 chapters=1, slug='audit-public')

    def _get(self, story, client=None):
        return (client or self.client).get(
            reverse('core:story_detail', kwargs={'slug': story.slug}))

    # ── Кому нельзя ──────────────────────────────────────────────────────
    def test_a_guest_gets_the_same_404_as_for_a_made_up_slug(self):
        for story in (self.draft, self.queued):
            with self.subTest(status=story.status):
                self.assertEqual(self._get(story).status_code, 404)
        self.assertEqual(self._get(self.public).status_code, 200)

    def test_a_signed_in_stranger_gets_404_too(self):
        stranger = Client()
        login_as_newcomer(stranger, 'audit_stranger')
        for story in (self.draft, self.queued):
            with self.subTest(status=story.status):
                self.assertEqual(self._get(story, stranger).status_code, 404)

    def test_the_text_never_reaches_the_response(self):
        """Не только код ответа: 404-страница не должна нести ни названия,
        ни текста — иначе правило выполнено формально."""
        body = self._get(self.draft).content.decode()
        self.assertNotIn(self.draft.title, body)
        self.assertNotIn(self.draft.chapter_set.first().body[:40], body)

    # ── Кому можно ───────────────────────────────────────────────────────
    def test_the_author_sees_his_own_work_as_a_preview(self):
        mine = Client()
        mine.force_login(self.author)
        for story in (self.draft, self.queued):
            with self.subTest(status=story.status):
                response = self._get(story, mine)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['is_preview'])
                self.assertContains(response, 'алдын ала қарау')

    def test_the_moderator_sees_the_queue_because_he_has_to_read_it(self):
        """Решение по работе принимается по её тексту, а в админке лежат
        номера глав. Закрыть страницу от модератора значит закрыть
        модерацию."""
        staff = Client()
        moderator = make.user(username='audit_moderator')
        moderator.is_staff = True
        moderator.save(update_fields=['is_staff'])
        staff.force_login(moderator)
        response = self._get(self.queued, staff)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_preview'])
        # Чужая работа — не его кабинет: ссылки в управление ему не дают.
        self.assertNotContains(response, 'Басқаруға оралу')

    def test_a_preview_offers_no_shelf_and_no_share(self):
        """Полки у непубличной работы не бывает, а ссылка из «Бөлісу» у
        получателя открывается 404. Обе кнопки работали только потому, что
        черновик был открыт всем; вместе с дырой уходит и обещание."""
        mine = Client()
        mine.force_login(self.author)
        # Не по слову «Бөлісу»: `share_modal.html` монтируется на странице
        # всегда и несёт то же слово. Кнопку опознаёт её `aria-label`.
        share = 'aria-label="Бөлісу"'
        preview = self._get(self.draft, mine)
        self.assertNotContains(
            preview, reverse('core:library_toggle',
                             kwargs={'slug': self.draft.slug}))
        self.assertNotContains(preview, share)
        # У публичной обе на месте — иначе тест проверял бы пустоту.
        public = self._get(self.public, mine)
        self.assertContains(public, reverse('core:library_toggle',
                                            kwargs={'slug': self.public.slug}))
        self.assertContains(public, share)

    def test_a_published_work_carries_no_preview_notice(self):
        response = self._get(self.public)
        self.assertFalse(response.context['is_preview'])
        self.assertNotContains(response, 'алдын ала қарау')

    # ── Следы, которых непубличная работа оставлять не должна ────────────
    def test_looking_at_a_draft_does_not_count_as_a_read(self):
        mine = Client()
        mine.force_login(self.author)
        self._get(self.draft, mine)
        Client().get(reverse('core:story_detail',
                             kwargs={'slug': self.draft.slug}))
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.views, 0)
        self.assertEqual(self.draft.recent_views, 0)
        self.assertFalse(StoryView.objects.filter(story=self.draft).exists())

    def test_a_draft_never_lands_on_a_shelf_or_gets_a_bookmark(self):
        mine = Client()
        mine.force_login(self.author)
        self._get(self.draft, mine)
        self.assertFalse(LibraryEntry.objects.filter(story=self.draft).exists())
        self.assertFalse(ReadingProgress.objects.filter(story=self.draft).exists())

    # ── Действия по слагу ────────────────────────────────────────────────
    def test_no_stranger_may_act_on_a_work_he_cannot_see(self):
        """Комментарий, полка, реакция и голос принимают слаг, а не объект,
        и до этого отвечали на чужой черновик так же, как на витрину."""
        stranger = Client()
        login_as_newcomer(stranger, 'audit_actor')
        slug, chapter = self.draft.slug, 1

        stranger.post(reverse('core:comment_create', kwargs={'slug': slug}),
                      {'text': 'Көрінбейтін пікір', 'chapter': chapter})
        stranger.post(reverse('core:library_toggle', kwargs={'slug': slug}))
        stranger.post(reverse('core:chapter_react',
                              kwargs={'slug': slug, 'chapter': chapter}),
                      {'kind': 'kuldim'})

        self.assertFalse(StoryComment.objects.filter(story=self.draft).exists())
        self.assertFalse(LibraryEntry.objects.filter(story=self.draft).exists())
        self.assertFalse(ChapterReactionVote.objects.filter(
            chapter__story=self.draft).exists())
