"""WRITE — дорога на модерацию и обратно.

Единица проверки — глава, точнее её ревизия: у публичного сериала новая
часть уходит на модерацию, а всё остальное остаётся читателю.

Автор видит, что с его текстом: что он подан, что его вернули и с каким
замечанием, и может забрать подачу назад, пока её не взяли в работу.
Отказ называет недостающее поимённо — «не готово» без причины ничему не
учит.
"""


from unittest import mock

from django.test import Client, TestCase
from django.urls import reverse

from core import data
from core.models import Chapter, Story
from core.tests import factories
from core.tests.base import login_as, login_as_newcomer, user
from core.domain.formatting import kk_within_hours


class OnlyAReadyDraftMayBeSubmitted(TestCase):
    """«готова» и «уже ушла» — разные вопросы. У работы на
    модерации кнопка означала бы повторную заявку, у публичной — откат в
    непубличное, чего автор ею не просит."""

    def setUp(self):
        login_as(self.client)

    def _get(self, slug):
        return self.client.get(reverse('core:manage_story', kwargs={'slug': slug}))

    def test_an_incomplete_draft_sees_the_button_disabled(self):
        draft = data.story_by_slug_for_author('aidana-kus', user('aidana'))
        self.assertFalse(data.can_submit_for_review(draft))
        self.assertEqual(data.missing_for_review(draft), ['text', 'audience'])
        response = self._get('aidana-kus')
        self.assertFalse(response.context['can_submit'])
        self.assertContains(response, 'disabled')
        self.assertContains(response, 'Модерацияға жіберу')

    def test_a_work_that_already_left_the_drafts_sees_no_button(self):
        for slug in ('aidana-tan', 'aidana-erteg'):
            with self.subTest(story=slug):
                story = data.story_by_slug_for_author(slug, user('aidana'))
                self.assertIsNotNone(story)
                self.assertFalse(data.can_submit_for_review(story))
                self.assertNotContains(self._get(slug), 'Модерацияға жіберу')

    def test_readiness_asks_the_text_and_not_the_status(self):
        """Подаётся то, что изменилось, и статус тут ни при чём.

        Прежняя проверка требовала `status == 'NotPublished'` — то есть
        публичный сериал не мог отправить дописанную главу вовсе, и она
        публиковалась мимо модерации (C1).
        """
        published = data.story_by_slug_for_author('aidana-tan', user('aidana'))
        self.assertEqual(data.missing_for_review(published), [])
        # Всё опубликовано — подавать нечего, хотя чек-лист закрыт.
        self.assertFalse(data.can_submit_for_review(published))

        chapter = published.chapter_set.first()
        chapter.body += ' Автор бір сөйлем қосты.'
        chapter.save()
        self.assertTrue(data.can_submit_for_review(published))

    def test_a_brand_new_work_sees_the_editor_button_disabled_not_a_trap(self):
        """V14: на первой странице совсем новой работы кнопка была активна,
        хотя аннотации и жас белгісі ещё нет и быть не может, — нажатие
        гарантированно било мимо. Здесь — та же неактивная кнопка с
        подсказкой, что и на manage_story, а не молчаливая (см. ниже)."""
        draft = data.story_by_slug_for_author('aidana-kus', user('aidana'))
        self.assertEqual(data.missing_for_review(draft), ['text', 'audience'])
        response = self.client.get(
            reverse('core:chapter_new', kwargs={'slug': 'aidana-kus'}))
        self.assertFalse(response.context['can_submit'])
        self.assertContains(response, 'Модерацияға жіберу')
        self.assertContains(response, 'disabled')

    def test_nothing_to_submit_hides_the_editor_button_quietly(self):
        """Чек-лист закрыт, слать нечего (test_readiness_asks_the_text_...)
        — кнопка молчит совсем, а не остаётся мимо-кнопкой и не врёт
        disabled-подсказкой про несуществующие незакрытые пункты."""
        published = data.story_by_slug_for_author('aidana-tan', user('aidana'))
        self.assertEqual(data.missing_for_review(published), [])
        self.assertFalse(data.can_submit_for_review(published))
        chapter = published.chapter_set.first()
        response = self.client.get(reverse(
            'core:chapter_edit', kwargs={'slug': 'aidana-tan', 'chapter': chapter.pk}))
        self.assertNotContains(response, 'Модерацияға жіберу')


class ThePromisedTurnaroundComesFromOneNumber(TestCase):
    """Срок, который портал обещает автору, и срок, по которому раздел
    модерации считает просрочку, — одно число.

    Раньше их было два: константа в домене, которую читала очередь, и
    литерал «тәулік ішінде» в панели отправки. Комментарий у константы
    прямо объяснял, что она в домене именно затем, что её читают обе
    стороны, — а панель её не читала. Сдвинуть обещание, не разойдясь с
    тем, что человеку сказано, было нельзя.
    """

    SLUG = 'aidana-kus'

    def setUp(self):
        login_as(self.client)
        # Обещание стоит рядом с живой кнопкой отправки, значит работа
        # должна быть готова к ней: у недозаполненного черновика этого
        # абзаца нет вовсе — и правильно, обещать нечего.
        story = Story.objects.get(slug=self.SLUG)
        story.audience = '10+'
        story.save(update_fields=['audience'])
        Chapter.objects.create(story=story, number=1,
                               title='1-бөлім', body='Мәтін бар.')

    def _panel(self):
        return self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.SLUG})
        ).content.decode()

    def test_the_author_is_told_the_turnaround(self):
        self.assertIn('әдетте тәулік ішінде', self._panel())

    def test_moving_the_number_moves_what_the_author_reads(self):
        with mock.patch('core.templatetags.qazaqnovel.REVIEW_PROMISE_HOURS', 48):
            self.assertIn('әдетте 2 тәулік ішінде', self._panel())

    def test_a_turnaround_shorter_than_a_day_is_spoken_in_hours(self):
        """Суток нет — нет и слова «тәулік»: «6 сағат ішінде» человек
        читает без деления в уме."""
        self.assertEqual(kk_within_hours(6), '6 сағат ішінде')
        self.assertEqual(kk_within_hours(24), 'тәулік ішінде')
        self.assertEqual(kk_within_hours(72), '3 тәулік ішінде')


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


class ModerationIsPerChapterNotPerWork(TestCase):
    """То, ради чего заведены ревизии.

    До них одобрение выдавалось работе один раз и дальше не значило
    ничего: вторая глава публичного сериала появлялась у читателя в момент
    сохранения, а переписанный одобренный текст — тем же движением. То
    есть модерация фактически отсутствовала у всего длинного контента
    .
    """

    def setUp(self):
        super().setUp()
        self.author = login_as_newcomer(self.client, 'revisions_author')
        self.reader = Client()
        self.serial = factories.story(
            author=self.author, status='OnProcess', format='serial',
            chapters=1, slug='revisions-serial')

    def _reader_sees(self, chapter_number=None):
        url = reverse('core:story_detail', kwargs={'slug': self.serial.slug})
        if chapter_number:
            url = f'{url}?chapter={chapter_number}'
        return self.reader.get(url).content.decode()

    # ── C1: новая глава ──────────────────────────────────────────────────
    def test_a_new_chapter_waits_for_the_moderator(self):
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.serial.slug}),
            {'title': 'Екінші бөлім', 'body': 'ТЕКСЕРІЛМЕГЕН МӘТІН',
             'action': 'draft'})
        self.serial.refresh_from_db()
        self.assertEqual(self.serial.chapter_set.count(), 2)
        self.assertNotIn('ТЕКСЕРІЛМЕГЕН МӘТІН', self._reader_sees(2))
        self.assertEqual(len(data.chapters_of(self.serial.slug)), 1)
        # И работа не ушла из каталога: опубликованное осталось на месте.
        self.assertEqual(self.serial.status, 'OnProcess')

    def test_the_chapter_appears_only_after_approval(self):
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.serial.slug}),
            {'title': 'Екінші бөлім', 'body': 'ТЕКСЕРІЛГЕН МӘТІН',
             'action': 'submit_review'})
        self.assertNotIn('ТЕКСЕРІЛГЕН МӘТІН', self._reader_sees(2))

        self.serial.refresh_from_db()
        self.serial.apply_moderation('approved')
        self.assertIn('ТЕКСЕРІЛГЕН МӘТІН', self._reader_sees(2))
        self.assertEqual(len(data.chapters_of(self.serial.slug)), 2)

    # ── C2: правка одобренного ───────────────────────────────────────────
    def test_rewriting_an_approved_chapter_does_not_reach_the_reader(self):
        first = self.serial.chapter_set.get(number=1)
        published_before = first.published_revision_id

        self.client.post(
            reverse('core:chapter_edit',
                    kwargs={'slug': self.serial.slug, 'chapter': first.pk}),
            {'title': first.title, 'body': 'ТҮГЕЛ АУЫСТЫРЫЛҒАН МӘТІН',
             'action': 'submit_review'})

        first.refresh_from_db()
        self.assertEqual(first.body, 'ТҮГЕЛ АУЫСТЫРЫЛҒАН МӘТІН')  # рабочая копия
        self.assertEqual(first.published_revision_id, published_before)
        self.assertNotIn('ТҮГЕЛ АУЫСТЫРЫЛҒАН МӘТІН', self._reader_sees(1))

        self.serial.refresh_from_db()
        self.serial.apply_moderation('approved')
        first.refresh_from_db()
        self.assertNotEqual(first.published_revision_id, published_before)
        self.assertIn('ТҮГЕЛ АУЫСТЫРЫЛҒАН МӘТІН', self._reader_sees(1))

    # ── Отказ не уносит опубликованное ───────────────────────────────────
    def test_a_returned_chapter_leaves_the_published_ones_alone(self):
        """Прежний исход назначал `NotPublished` любому отказу — и публичный
        сериал, чью новую главу вернули, исчезал из каталога целиком."""
        self.client.post(
            reverse('core:chapter_new', kwargs={'slug': self.serial.slug}),
            {'title': 'Екінші бөлім', 'body': 'Шикі мәтін.',
             'action': 'submit_review'})
        self.serial.refresh_from_db()
        self.serial.apply_moderation('needs_work', 'Соңы жоқ.')

        self.serial.refresh_from_db()
        self.assertEqual(self.serial.status, 'OnProcess')
        self.assertTrue(self.serial.is_public)
        self.assertEqual(len(data.chapters_of(self.serial.slug)), 1)
        # Рабочая копия автора при этом цела — править есть что.
        self.assertEqual(self.serial.chapter_set.get(number=2).body,
                         'Шикі мәтін.')

    # ── V10: правка во время очереди ─────────────────────────────────────
    def test_editing_while_queued_replaces_what_was_submitted(self):
        """Автор правил текст после отправки, и модератор читал не то, что
        ему прислали. Вторая заявка при этом не заводится."""
        first_id = self.serial.chapter_set.get(number=1).pk
        url = reverse('core:chapter_edit',
                      kwargs={'slug': self.serial.slug, 'chapter': first_id})
        self.client.post(url, {'title': '1-бөлім', 'body': 'Бірінші нұсқа.',
                               'action': 'submit_review'})
        self.client.post(url, {'title': '1-бөлім', 'body': 'Түзетілген нұсқа.',
                               'action': 'submit_review'})

        first = self.serial.chapter_set.get(number=1)
        pending = [r for r in first.revisions.all() if r.state == 'pending']
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].body, 'Түзетілген нұсқа.')

    # ── S10: история ─────────────────────────────────────────────────────
    def test_every_version_stays_in_history(self):
        """Перезаписи больше нет: у главы копятся ревизии, и потерянного
        текста, который нечем восстановить, не остаётся."""
        first = self.serial.chapter_set.get(number=1)
        url = reverse('core:chapter_edit',
                      kwargs={'slug': self.serial.slug, 'chapter': first.pk})
        for text in ('Бірінші түзету.', 'Екінші түзету.'):
            self.client.post(url, {'title': '1-бөлім', 'body': text,
                                   'action': 'submit_review'})
            self.serial.refresh_from_db()
            self.serial.apply_moderation('approved')

        bodies = [r.body for r in first.revisions.all()]
        self.assertIn('Бірінші түзету.', bodies)
        self.assertIn('Екінші түзету.', bodies)
        self.assertEqual(first.revisions.filter(state='approved').count(), 3)


class ReturnedWorkKnowsItWasReturned(TestCase):
    """Возврат «на доработку» не оставлял следа: работа падала
    в черновики, чек-лист снова горел зелёным, кнопка отправки была
    активна, и единственный экземпляр причины лежал в ленте уведомлений —
    автор должен был помнить её наизусть, пока правит (S1)."""

    def setUp(self):
        super().setUp()
        self.author = login_as_newcomer(self.client, 'returned_author')
        self.story = factories.story(
            author=self.author, chapters=1, format='single',
            slug='returned-work', published=False)
        factories.submit(self.story)
        self.story.refresh_status()

    def _manage(self):
        return self.client.get(
            reverse('core:manage_story', kwargs={'slug': self.story.slug}))

    def test_the_reason_stays_on_the_working_screen(self):
        self.story.apply_moderation('needs_work', 'Диалогтар үзіліп қалған.')
        response = self._manage()
        self.assertContains(response, 'Диалогтар үзіліп қалған.')
        self.assertContains(response, 'Толықтыру қажет')
        self.story.refresh_from_db()
        self.assertEqual(self.story.status, 'NeedsWork')

    def test_the_reason_goes_away_once_it_was_resubmitted(self):
        """Замечание — про прошлую версию: после повторной подачи оно уже
        не про то, что лежит у модератора."""
        self.story.apply_moderation('needs_work', 'Соңы жоқ.')
        chapter = self.story.chapter_set.first()
        chapter.body += ' Соңы жазылды.'
        chapter.save()
        self.client.post(reverse('core:manage_story',
                                 kwargs={'slug': self.story.slug}))
        self.assertNotContains(self._manage(), 'Соңы жоқ.')

    def test_a_returned_work_is_told_apart_from_an_untouched_draft(self):
        untouched = factories.story(author=self.author, chapters=1,
                                    format='single', published=False,
                                    slug='untouched-draft')
        untouched.refresh_status()
        self.story.apply_moderation('needs_work', 'Түзет.')

        self.story.refresh_from_db()
        untouched.refresh_from_db()
        self.assertEqual(self.story.status, 'NeedsWork')
        self.assertEqual(untouched.status, 'NotPublished')

        listing = self.client.get(reverse('core:my_stories'))
        self.assertContains(listing, 'толықтыруды күтеді')

    def test_a_public_serial_stays_public_when_a_chapter_is_returned(self):
        """`NeedsWork` — только у непубличного: увести работу из каталога
        значит наказать читателя за то, чего он не видел."""
        serial = factories.story(author=self.author, chapters=1,
                                 format='serial', status='OnProcess',
                                 slug='public-returned')
        factories.chapter(serial, number=2, chars=300)
        factories.submit(serial)
        serial.refresh_status()
        serial.apply_moderation('needs_work', 'Екінші бөлім шикі.')

        serial.refresh_from_db()
        self.assertEqual(serial.status, 'OnProcess')
        self.assertTrue(serial.is_public)


class TheAuthorMayTakeTheSubmissionBack(TestCase):
    """Кнопки отзыва не было вовсе: заметив опечатку через
    минуту после отправки, автор мог только ждать модератора."""

    def setUp(self):
        super().setUp()
        self.author = login_as_newcomer(self.client, 'withdraw_author')
        self.story = factories.story(
            author=self.author, chapters=1, format='single',
            slug='withdraw-work', published=False)
        self.url = reverse('core:manage_story',
                           kwargs={'slug': self.story.slug})
        self.client.post(self.url)          # отправили на модерацию

    def test_the_queue_shows_the_button_and_how_long_it_waits(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Мәтін модераторда')
        self.assertContains(response, 'Өтінімді кері қайтару')

    def test_withdrawing_empties_the_queue_without_losing_the_text(self):
        self.client.post(self.url, {'action': 'withdraw'})
        self.story.refresh_from_db()
        self.assertIsNone(data.pending_review_since(self.story))
        self.assertEqual(self.story.status, 'NotPublished')
        # Снимок остаётся историей, а не исчезает вместе с заявкой.
        chapter = self.story.chapter_set.first()
        self.assertEqual(chapter.revisions.count(), 1)
        self.assertEqual(chapter.revisions.first().state, 'draft')
        self.assertTrue(chapter.body)
        # И подать снова можно сразу.
        self.assertTrue(data.can_submit_for_review(self.story))

    def test_a_withdrawn_work_is_out_of_the_moderator_queue(self):
        self.client.post(self.url, {'action': 'withdraw'})
        self.story.refresh_from_db()
        with self.assertRaises(ValueError):
            self.story.apply_moderation('approved')


class TheRefusalNamesWhatIsMissing(TestCase):
    """Сообщение перечисляло причины на память — «аннотация
    мен жас белгісі», — и врало всякий раз, когда не хватало текста."""

    def setUp(self):
        super().setUp()
        self.author = login_as_newcomer(self.client, 'refusal_author')

    def test_it_names_the_missing_items_in_words(self):
        bare = factories.story(author=self.author, chapters=0,
                               format='serial', published=False,
                               annotation='', audience='', slug='bare-work')
        response = self.client.post(
            reverse('core:manage_story', kwargs={'slug': bare.slug}),
            follow=True)
        text = ' '.join(m.message for m in response.context['messages'])
        self.assertIn('Алғашқы бөлімді жаз', text)
        self.assertIn('Аннотация жаз', text)
        self.assertIn('Жас белгісін қой', text)

    def test_the_panel_and_the_message_speak_the_same_words(self):
        """Один список подписей: разойдясь, они снова стали бы врать."""
        bare = factories.story(author=self.author, chapters=0,
                               format='single', published=False,
                               annotation='', audience='', slug='bare-single')
        panel = self.client.get(
            reverse('core:manage_story', kwargs={'slug': bare.slug}))
        for label in data.missing_labels(bare):
            with self.subTest(label=label):
                self.assertContains(panel, label)
        # У одночастной работы «бөлім» не предлагают — их у неё нет.
        self.assertIn('Мәтін жаз', data.missing_labels(bare))
