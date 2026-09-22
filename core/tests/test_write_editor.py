"""WRITE — редактор главы: черновик, опрос, автосохранение.

Редактор говорит правду о состоянии: «сақталды» не значит
«опубликовано», а номер главы — не её адрес.

Автосохранение пишет само и потому обязано быть скупым: тот же текст
второй раз не пишется вовсе, иначе `updated_at` работы сдвигался бы от
того, что автор смотрит на экран.
"""


from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core import data
from core.models import Chapter, ChapterPoll, Story
from core.tests import factories
from core.tests.base import login_as, login_as_newcomer, user


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
        того же на одном экране. Отступ снизу разводит панель с плавающей
        пилюлей `mobile_nav` (docs/ui.md): 6rem — это прежние `bottom-24`,
        а `env(safe-area-inset-bottom)` добавлен вместе с такой же добавкой
        у самой пилюли — на iPhone внизу 34px отданы жесту «домой»."""
        body = self.client.get(reverse(
            'core:chapter_new', kwargs={'slug': self.SLUG})).content.decode()
        self.assertIn('x-text="count"', body)
        self.assertIn('charCounter(', body)
        self.assertIn('@input="recount"', body)
        self.assertIn('sticky bottom-[calc(6rem+env(safe-area-inset-bottom))]', body)
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


class AutosaveWritesOnlyWhatChanged(TestCase):
    """Предела частоты у автосохранения нет и по времени быть не должно:
    автор, пишущий быстро, упирался бы в него ровно тогда, когда страховка
    нужнее всего.

    Предел тут по смыслу — запись, ничего не меняющая, не запись вовсе.
    Она стоила `UPDATE` по тексту главы, второго по `updated_at` работы и
    сдвигала «когда трогали» у работы, которую не трогали. Редактор шлёт
    автосохранение по таймеру, но адрес открытый: прямой POST повторял бы
    одно и то же тело сколько угодно раз.
    """

    def setUp(self):
        self.author = login_as(self.client)
        self.story = factories.story(author=self.author, chapters=1,
                                     published=False, status='NotPublished')
        self.chapter = self.story.chapter_set.first()
        self.url = reverse('core:chapter_autosave',
                           kwargs={'slug': self.story.slug,
                                   'chapter': self.chapter.pk})

    def _autosave(self, body, title=None):
        return self.client.post(self.url, {
            'title': self.chapter.title if title is None else title,
            'body': body,
        })

    def test_the_same_body_twice_writes_once(self):
        self._autosave('Жаңа мәтін.')
        self.story.refresh_from_db()
        touched = self.story.updated_at

        with self.assertNumQueries(5):
            # Сессия, пользователь, работа, резолв главы и сама глава — и
            # всё: ни `UPDATE` по тексту, ни сдвига `updated_at` у работы.
            # Пять — это чтение; писать здесь больше нечего.
            self._autosave('Жаңа мәтін.')

        self.story.refresh_from_db()
        self.assertEqual(self.story.updated_at, touched)

    def test_a_changed_body_still_writes(self):
        self._autosave('Бірінші нұсқа.')

        self._autosave('Екінші нұсқа.')

        self.chapter.refresh_from_db()
        self.assertEqual(self.chapter.body, 'Екінші нұсқа.')

    def test_a_changed_title_alone_still_writes(self):
        self._autosave('Мәтін.', title='Бірінші атау')

        self._autosave('Мәтін.', title='Екінші атау')

        self.chapter.refresh_from_db()
        self.assertEqual(self.chapter.title, 'Екінші атау')

    def test_the_browser_line_endings_do_not_count_as_a_change(self):
        """Браузер шлёт CRLF, база хранит LF. Без нормализации «ничего не
        изменилось» никогда не совпадало бы само с собой, и предел не
        срабатывал бы ни разу."""
        self._autosave('Бірінші жол.\nЕкінші жол.')
        self.story.refresh_from_db()
        touched = self.story.updated_at

        self._autosave('Бірінші жол.\r\nЕкінші жол.')

        self.story.refresh_from_db()
        self.assertEqual(self.story.updated_at, touched)

    def test_the_answer_is_the_same_either_way(self):
        """Редактор не должен отличать «сохранено» от «нечего сохранять»:
        для него это одно и то же состояние."""
        self._autosave('Мәтін.')

        response = self._autosave('Мәтін.')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['chapter'], self.chapter.pk)


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
