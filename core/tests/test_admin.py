"""Админка как инструмент модерации (DEC-23, docs/19 §19.4, этап 10).

Кастомного UI до V2 не будет, значит проверять надо не «страница
открылась», а то, что модератор может довести дело до конца: решение по
работе доходит до автора (BR-11), причина отказа обязательна (BR-72b),
статус после одобрения зависит от формата (BR-10a), а в `media/` не
попадает SVG (BR-46).

Смоук по всем зарегистрированным моделям стоит здесь же: `list_display`
и `list_filter` проверяются системными чеками не полностью — свойство
без колонки, поставленное в фильтр, роняет страницу только при открытии.
"""

import shutil
import tempfile

from django.contrib import admin as django_admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms.models import modelform_factory
from django.test import override_settings
from django.urls import reverse

from core.models import (
    Chapter,
    Contest,
    ContestAward,
    Genre,
    Notification,
    Story,
    User,
)
from core.tests.base import TestCase


def _story(author, **kwargs):
    """Работа под тестом, а не из корпуса: статусами здесь двигают."""
    fields = {
        'slug': 'test-work', 'title': 'Сынақ шығармасы',
        'primary_genre': Genre.objects.first(),
        'status': 'OnModeration', 'format': 'single', 'chapters': 1,
    }
    fields.update(kwargs)
    return Story.objects.create(author=author, **fields)


class ModerationChangesStatusAndTellsTheAuthor(TestCase):
    """`Story.apply_moderation` — одна дверь на решение и уведомление."""

    def setUp(self):
        self.author = User.objects.get(username='aidana')

    def test_approved_single_becomes_published(self):
        story = _story(self.author, format='single')
        story.apply_moderation('approved')
        story.refresh_from_db()
        self.assertEqual(story.status, 'Published')

    def test_approved_serial_does_not_become_published(self):
        """BR-10a: у сериала `Published` невалиден — он продолжается.

        Литерал `'Published'` в одобрении означал бы, что после первой же
        модерации сериал перестаёт отвечать на вопрос «дописан ли он»:
        обе читательские метки — `OnProcess` и `Completed`.
        """
        story = _story(self.author, format='serial', chapters=4)
        story.apply_moderation('approved')
        story.refresh_from_db()
        self.assertEqual(story.status, 'OnProcess')

    def test_needs_work_returns_the_draft_with_a_reason(self):
        story = _story(self.author)
        note = story.apply_moderation('needs_work', 'Диалогтар үзіліп қалған.')
        story.refresh_from_db()
        self.assertEqual(story.status, 'NotPublished')
        self.assertEqual(note.user, self.author)
        self.assertEqual(note.kind, 'moderation')
        self.assertEqual(note.outcome, 'needs_work')
        self.assertEqual(note.text, 'Диалогтар үзіліп қалған.')
        self.assertEqual(note.story, story)

    def test_rejected_without_a_reason_is_refused(self):
        """BR-11: отказ без причины не сообщает автору ничего."""
        story = _story(self.author)
        with self.assertRaises(ValueError):
            story.apply_moderation('rejected', '   ')
        story.refresh_from_db()
        self.assertEqual(story.status, 'OnModeration')
        self.assertFalse(Notification.objects.filter(story=story).exists())

    def test_approval_needs_no_reason(self):
        story = _story(self.author)
        note = story.apply_moderation('approved')
        self.assertEqual(note.outcome, 'approved')
        self.assertEqual(note.text, '')

    def test_only_what_the_author_submitted_is_decided(self):
        """Одобрить чужой черновик значит опубликовать непоказанное.

        Готовность объявляет автор (FR-WRITE-09) — модератор отвечает
        «да» или «нет», а не решает за него, что работа готова.
        """
        draft = _story(self.author, status='NotPublished')
        with self.assertRaises(ValueError):
            draft.apply_moderation('approved')
        draft.refresh_from_db()
        self.assertEqual(draft.status, 'NotPublished')

    def test_unknown_outcome_is_refused(self):
        story = _story(self.author)
        with self.assertRaises(ValueError):
            story.apply_moderation('maybe', 'себебі')

    def test_the_notification_says_what_the_moderator_decided(self):
        """Подпись — из реестра (BR-72b), а не собрана в шаблоне."""
        story = _story(self.author)
        note = story.apply_moderation('needs_work', 'Толықтыр.')
        self.assertEqual(note.outcome_label, 'Толықтыру қажет')


class ModerationThroughTheAdmin(TestCase):
    """Тот же путь, каким им пользуются: список работ и действие над ним."""

    def setUp(self):
        self.moderator = User.objects.create_superuser(
            'moderator', password='x', name='Модератор')
        self.client.force_login(self.moderator)
        self.author = User.objects.get(username='aidana')
        self.story = _story(self.author)
        self.url = reverse('admin:core_story_changelist')

    def _act(self, action, **extra):
        return self.client.post(self.url, {
            'action': action,
            '_selected_action': [self.story.pk],
            **extra,
        }, follow=True)

    def test_action_asks_for_a_reason_before_applying(self):
        r = self._act('send_back')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Толықтыру қажет')
        self.story.refresh_from_db()
        self.assertEqual(self.story.status, 'OnModeration')

    def test_applying_moves_the_work_and_notifies(self):
        self._act('send_back', apply='1', reason='Соңы жоқ.')
        self.story.refresh_from_db()
        self.assertEqual(self.story.status, 'NotPublished')
        note = Notification.objects.get(story=self.story)
        self.assertEqual(note.outcome, 'needs_work')
        self.assertEqual(note.text, 'Соңы жоқ.')

    def test_empty_reason_does_not_apply(self):
        r = self._act('reject', apply='1', reason='  ')
        self.assertContains(r, 'Себепті жазу керек')
        self.story.refresh_from_db()
        self.assertEqual(self.story.status, 'OnModeration')
        self.assertFalse(Notification.objects.filter(story=self.story).exists())

    def test_approval_goes_through_without_a_reason(self):
        self._act('approve', apply='1', reason='')
        self.story.refresh_from_db()
        self.assertEqual(self.story.status, 'Published')
        self.assertEqual(Notification.objects.get(story=self.story).outcome,
                         'approved')

    def test_work_outside_the_queue_is_named_not_skipped_silently(self):
        """Иначе модератор считает решёнными все, что выбрал."""
        self.story.status = 'NotPublished'
        self.story.save(update_fields=['status'])
        r = self._act('approve')
        self.assertContains(r, 'өткізілді')
        self.story.refresh_from_db()
        self.assertEqual(self.story.status, 'NotPublished')

    def test_manual_status_change_warns_that_nobody_was_told(self):
        """Правка поля — не модерация: уведомление пишет только решение.

        Молча она означала бы, что работа ушла из очереди, а автор об
        этом не узнал.
        """
        url = reverse('admin:core_story_change', args=[self.story.pk])
        form = {
            'slug': self.story.slug, 'title': self.story.title,
            'author': self.author.pk, 'annotation': '',
            'primary_genre': self.story.primary_genre_id,
            'secondary_genre': '', 'tags': [],
            'format': 'single', 'chapters': 1, 'audience': '',
            'status': 'Published', 'views': 0, 'recent_views': 0,
            'likes': 0, 'comments': 0,
            'chapter_set-TOTAL_FORMS': '0', 'chapter_set-INITIAL_FORMS': '0',
        }
        r = self.client.post(url, form, follow=True)
        self.story.refresh_from_db()
        self.assertEqual(self.story.status, 'Published')
        self.assertContains(r, 'автор хабарлама алмады')
        self.assertFalse(Notification.objects.filter(story=self.story).exists())


class NotificationsAreReadOnly(TestCase):
    """Уведомление пишет событие, а не рука модератора (BR-72b)."""

    def setUp(self):
        self.client.force_login(
            User.objects.create_superuser('moderator', password='x'))

    def test_no_add_and_no_change(self):
        note = Notification.objects.first()
        self.assertEqual(
            self.client.get(reverse('admin:core_notification_add')).status_code,
            403)
        r = self.client.get(
            reverse('admin:core_notification_change', args=[note.pk]))
        # Django отдаёт карточку в режиме просмотра, но без формы сохранения.
        self.assertNotContains(r, 'name="_save"')


MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class MediaUploadsTakeRasterOnly(TestCase):
    """BR-46: файл из `/media/` открывается в origin сайта, SVG — документ."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def _form(self, upload):
        Form = modelform_factory(ContestAward, fields=('contest', 'slug',
                                                       'title', 'image'))
        contest = Contest.objects.first()
        return Form({'contest': contest.pk, 'slug': 'bas-julde-test',
                     'title': 'Бас жүлде'},
                    {'image': upload})

    def test_png_is_accepted_and_lands_under_its_contest(self):
        form = self._form(SimpleUploadedFile('эмблема.png', b'\x89PNG demo',
                                             content_type='image/png'))
        self.assertTrue(form.is_valid(), form.errors)
        award = form.save()
        self.assertTrue(award.image.name.startswith(
            f'awards/{award.contest.slug}/'))
        self.assertTrue(award.image.name.endswith('.png'))

    def test_svg_is_refused(self):
        form = self._form(SimpleUploadedFile('эмблема.svg', b'<svg/>',
                                             content_type='image/svg+xml'))
        self.assertFalse(form.is_valid())
        self.assertIn('SVG', str(form.errors))


class EveryRegisteredPageOpens(TestCase):
    """Смоук по админке: список и форма добавления у каждой модели.

    Системные чеки ловят не всё: свойство без колонки в `list_filter`
    проходит проверку и падает при открытии страницы. А открывают её
    редко — модерация в MVP это и есть весь инструмент.
    """

    def setUp(self):
        self.client.force_login(
            User.objects.create_superuser('moderator', password='x'))

    def test_changelists_render(self):
        for model in django_admin.site._registry:
            opts = model._meta
            with self.subTest(model=opts.model_name):
                url = reverse(f'admin:{opts.app_label}_{opts.model_name}_changelist')
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_add_forms_render(self):
        for model in django_admin.site._registry:
            opts = model._meta
            with self.subTest(model=opts.model_name):
                url = reverse(f'admin:{opts.app_label}_{opts.model_name}_add')
                # 403 — тоже ответ: уведомление руками не заводят (BR-72b).
                self.assertIn(self.client.get(url).status_code, (200, 403))

    def test_moderation_queue_is_reachable_by_filter(self):
        """Очередь модератора — это `?status=OnModeration` в списке работ."""
        url = reverse('admin:core_story_changelist') + '?status=OnModeration'
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)


class ChapterTextIsEditable(TestCase):
    """Текст главы правится в админке: форм автора нет до Ф15."""

    def setUp(self):
        self.client.force_login(
            User.objects.create_superuser('moderator', password='x'))

    def test_chapter_change_form_has_the_body(self):
        chapter = Chapter.objects.exclude(body='').first()
        r = self.client.get(
            reverse('admin:core_chapter_change', args=[chapter.pk]))
        self.assertContains(r, 'name="body"')
