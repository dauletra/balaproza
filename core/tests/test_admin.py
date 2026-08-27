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
        'status': 'OnModeration', 'format': 'single',
    }
    fields.update(kwargs)
    return Story.objects.create(author=author, **fields)


class ADecisionReachesTheAuthor(TestCase):
    """`Story.apply_moderation` — одна дверь на решение и уведомление
    (BR-11). Порознь они бессмысленны: статус без уведомления оставляет
    автора гадать, что случилось, а уведомление без статуса обещает
    публикацию, которой не произошло."""

    def setUp(self):
        self.author = User.objects.get(username='aidana')

    def test_approval_depends_on_the_format(self):
        """BR-10a: у сериала `Published` невалиден — он продолжается. Обе
        его читательские метки это `OnProcess` и `Completed`, и литерал в
        одобрении отнял бы у сериала ответ на «дописан ли он»."""
        single = _story(self.author, format='single')
        single.apply_moderation('approved')
        single.refresh_from_db()
        self.assertEqual(single.status, 'Published')

        serial = _story(self.author, slug='test-serial', format='serial')
        note = serial.apply_moderation('approved')
        serial.refresh_from_db()
        self.assertEqual(serial.status, 'OnProcess')
        self.assertEqual(note.outcome, 'approved')
        self.assertEqual(note.text, '')

    def test_a_return_carries_its_reason_all_the_way(self):
        """Подпись исхода берётся из реестра (BR-72b), а не собирается в
        шаблоне."""
        story = _story(self.author)
        note = story.apply_moderation('needs_work', 'Диалогтар үзіліп қалған.')
        story.refresh_from_db()
        self.assertEqual(story.status, 'NotPublished')
        self.assertEqual(note.user, self.author)
        self.assertEqual(note.kind, 'moderation')
        self.assertEqual(note.outcome, 'needs_work')
        self.assertEqual(note.text, 'Диалогтар үзіліп қалған.')
        self.assertEqual(note.story, story)
        self.assertEqual(note.outcome_label, 'Толықтыру қажет')

    def test_what_the_door_refuses(self):
        """Отказ без причины не сообщает автору ничего (BR-11). Одобрить
        чужой черновик значит опубликовать непоказанное: готовность
        объявляет автор (FR-WRITE-09), модератор отвечает «да» или «нет»."""
        story = _story(self.author)
        for outcome, reason in (('rejected', '   '), ('maybe', 'себебі')):
            with self.subTest(outcome=outcome):
                with self.assertRaises(ValueError):
                    story.apply_moderation(outcome, reason)
        story.refresh_from_db()
        self.assertEqual(story.status, 'OnModeration')
        self.assertFalse(Notification.objects.filter(story=story).exists())

        draft = _story(self.author, slug='test-draft', status='NotPublished')
        with self.assertRaises(ValueError):
            draft.apply_moderation('approved')
        draft.refresh_from_db()
        self.assertEqual(draft.status, 'NotPublished')


class TheModeratorWorksThroughTheAdmin(TestCase):
    """Тот же путь, каким им пользуются: список работ и действие над ним.
    Кастомного UI до V2 не будет (DEC-23), значит проверять надо не
    «страница открылась», а то, что дело доводится до конца."""

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

    def test_a_negative_outcome_asks_for_a_reason_and_only_then_applies(self):
        asked = self._act('send_back')
        self.assertContains(asked, 'Толықтыру қажет')
        self.story.refresh_from_db()
        self.assertEqual(self.story.status, 'OnModeration')

        empty = self._act('reject', apply='1', reason='  ')
        self.assertContains(empty, 'Себепті жазу керек')
        self.story.refresh_from_db()
        self.assertEqual(self.story.status, 'OnModeration')
        self.assertFalse(Notification.objects.filter(story=self.story).exists())

        self._act('send_back', apply='1', reason='Соңы жоқ.')
        self.story.refresh_from_db()
        self.assertEqual(self.story.status, 'NotPublished')
        note = Notification.objects.get(story=self.story)
        self.assertEqual(note.outcome, 'needs_work')
        self.assertEqual(note.text, 'Соңы жоқ.')

    def test_approval_goes_through_without_a_reason(self):
        self._act('approve', apply='1', reason='')
        self.story.refresh_from_db()
        self.assertEqual(self.story.status, 'Published')
        self.assertEqual(Notification.objects.get(story=self.story).outcome,
                         'approved')

    def test_a_work_outside_the_queue_is_named_not_skipped_silently(self):
        """Иначе модератор считает решёнными все, что выбрал."""
        self.story.status = 'NotPublished'
        self.story.save(update_fields=['status'])
        self.assertContains(self._act('approve'), 'өткізілді')
        self.story.refresh_from_db()
        self.assertEqual(self.story.status, 'NotPublished')

    def test_editing_the_field_by_hand_warns_that_nobody_was_told(self):
        """Правка поля — не модерация: уведомление пишет только решение.
        Молча она означала бы, что работа ушла из очереди, а автор об этом
        не узнал."""
        form = {
            'slug': self.story.slug, 'title': self.story.title,
            'author': self.author.pk, 'annotation': '',
            'primary_genre': self.story.primary_genre_id,
            'secondary_genre': '', 'tags': [],
            'format': 'single', 'audience': '',
            'status': 'Published', 'views': 0, 'recent_views': 0,
            'likes': 0, 'comments': 0,
            'chapter_set-TOTAL_FORMS': '0', 'chapter_set-INITIAL_FORMS': '0',
            # StoryTagInline: `tags` — M2M через `through`, вне fieldsets.
            'storytag_set-TOTAL_FORMS': '0', 'storytag_set-INITIAL_FORMS': '0',
        }
        response = self.client.post(
            reverse('admin:core_story_change', args=[self.story.pk]),
            form, follow=True)
        self.story.refresh_from_db()
        self.assertEqual(self.story.status, 'Published')
        self.assertContains(response, 'автор хабарлама алмады')
        self.assertFalse(Notification.objects.filter(story=self.story).exists())


MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class MediaUploadsTakeRasterOnly(TestCase):
    """BR-46: файл из `/media/` открывается в origin сайта, а SVG — это
    документ, а не картинка."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def _form(self, upload):
        Form = modelform_factory(ContestAward,
                                 fields=('contest', 'slug', 'title', 'image'))
        return Form({'contest': Contest.objects.first().pk,
                     'slug': 'bas-julde-test', 'title': 'Бас жүлде'},
                    {'image': upload})

    def test_a_raster_lands_under_its_contest_and_an_svg_does_not_land(self):
        png = self._form(SimpleUploadedFile('эмблема.png', b'\x89PNG demo',
                                            content_type='image/png'))
        self.assertTrue(png.is_valid(), png.errors)
        award = png.save()
        self.assertTrue(award.image.name.startswith(f'awards/{award.contest.slug}/'))
        self.assertTrue(award.image.name.endswith('.png'))

        svg = self._form(SimpleUploadedFile('эмблема.svg', b'<svg/>',
                                            content_type='image/svg+xml'))
        self.assertFalse(svg.is_valid())
        self.assertIn('SVG', str(svg.errors))


class TheWholeToolOpens(TestCase):
    """Смоук по админке. Системные чеки ловят не всё: свойство без колонки
    в `list_filter` проходит проверку и падает при открытии страницы — а
    открывают её редко, модерация в MVP это и есть весь инструмент."""

    def setUp(self):
        self.client.force_login(
            User.objects.create_superuser('moderator', password='x'))

    def test_every_registered_model_has_a_list_and_a_form(self):
        for model in django_admin.site._registry:
            opts = model._meta
            with self.subTest(model=opts.model_name):
                self.assertEqual(self.client.get(reverse(
                    f'admin:{opts.app_label}_{opts.model_name}_changelist')
                ).status_code, 200)
                # 403 — тоже ответ: уведомление руками не заводят (BR-72b).
                self.assertIn(self.client.get(reverse(
                    f'admin:{opts.app_label}_{opts.model_name}_add')
                ).status_code, (200, 403))

    def test_the_moderation_queue_is_a_filter_on_the_story_list(self):
        self.assertEqual(self.client.get(
            reverse('admin:core_story_changelist') + '?status=OnModeration'
        ).status_code, 200)

    def test_a_notification_is_written_by_the_event_not_by_hand(self):
        """BR-72b. Django отдаёт карточку в режиме просмотра, но без формы
        сохранения."""
        note = Notification.objects.first()
        self.assertEqual(self.client.get(
            reverse('admin:core_notification_add')).status_code, 403)
        self.assertNotContains(self.client.get(
            reverse('admin:core_notification_change', args=[note.pk])),
            'name="_save"')

    def test_chapter_text_is_editable_here(self):
        chapter = Chapter.objects.exclude(body='').first()
        self.assertContains(self.client.get(
            reverse('admin:core_chapter_change', args=[chapter.pk])),
            'name="body"')
