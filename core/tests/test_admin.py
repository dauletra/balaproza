"""Админка как редакционный инструмент.

Решение по работе здесь больше не принимается — для него есть раздел
`/moderation/`. Осталось то, ради чего админка и нужна: карточка работы
с правкой полей, справочники, загрузка растра.

Проверяется поэтому не «страница открылась», а две вещи: одна дверь
решения (`Story.apply_moderation`) доводит дело до автора, и ручная
правка поля честно говорит, что уведомления не было.

Смоук по всем зарегистрированным моделям стоит здесь же: `list_display`
и `list_filter` проверяются системными чеками не полностью — свойство
без колонки, поставленное в фильтр, роняет страницу только при открытии.
"""

import shutil
import tempfile

from django.contrib import admin as django_admin
from django.contrib.admin.models import LogEntry
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.forms.models import modelform_factory
from django.template.loader import render_to_string
from django.test import RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.urls import reverse

from core import data
from core.domain import contests as contest_rules
from core.domain import notifications as notification_rules
from core.domain import story as story_rules
from core.domain import tags as tag_rules
from core.domain.story import STORY_STATUS_LABELS
from core.admin.catalog import BookOfWeekAdmin, GenreAdmin
from core.admin.social import NotificationAdmin
from core.admin.story import StoryTagInline
from core.models import (
    AwardGrant,
    BookOfWeek,
    Chapter,
    ChapterRevision,
    Contest,
    ContestAward,
    Genre,
    Notification,
    Story,
    StoryTag,
    TimelineStage,
    User,
)
from core.templatetags.qazaqnovel import outcome_label
from core.tests import factories
from core.tests.base import TestCase, login_as


def _story(author, submitted=True, **kwargs):
    """Работа под тестом, а не из корпуса: статусами здесь двигают.

    Работа приходит **с поданной главой**: решение принимается по
    ревизии, а не по статусу, и работа без единой ждущей ревизии для
    модератора пуста — решать в ней нечего.
    """
    fields = {
        'slug': 'test-work', 'title': 'Сынақ шығармасы',
        'primary_genre': Genre.objects.first(),
        'status': 'OnModeration', 'format': 'single',
    }
    fields.update(kwargs)
    story = Story.objects.create(author=author, **fields)
    chapter = Chapter.objects.create(story=story, number=1,
                                     title='1-бөлім', body='Сынақ мәтіні.')
    if submitted:
        ChapterRevision.objects.create(
            chapter=chapter, title=chapter.title, body=chapter.body,
            state='pending', submitted_at=timezone.now())
    return story


class ADecisionReachesTheAuthor(TestCase):
    """`Story.apply_moderation` — одна дверь на решение и уведомление.
 Порознь они бессмысленны: статус без уведомления оставляет
    автора гадать, что случилось, а уведомление без статуса обещает
    публикацию, которой не произошло."""

    def setUp(self):
        self.author = User.objects.get(username='aidana')

    def test_approval_depends_on_the_format(self):
        """У сериала `Published` невалиден — он продолжается. Обе
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
        """Подпись исхода берётся из реестра, а не собирается в
        шаблоне."""
        story = _story(self.author)
        note = story.apply_moderation('needs_work', 'Диалогтар үзіліп қалған.')
        story.refresh_from_db()
        # Не `NotPublished`: возвращённое отличается от нетронутого
        # черновика — автор обязан видеть, что работа ждёт его.
        self.assertEqual(story.status, 'NeedsWork')
        self.assertEqual(note.user, self.author)
        self.assertEqual(note.kind, 'moderation')
        self.assertEqual(note.outcome, 'needs_work')
        self.assertEqual(note.text, 'Диалогтар үзіліп қалған.')
        self.assertEqual(note.story, story)
        self.assertEqual(outcome_label(note), 'Толықтыру қажет')

    def test_what_the_door_refuses(self):
        """Отказ без причины не сообщает автору ничего. Одобрить
        чужой черновик значит опубликовать непоказанное: готовность
        объявляет автор, модератор отвечает «да» или «нет»."""
        story = _story(self.author)
        for outcome, reason in (('rejected', '   '), ('maybe', 'себебі')):
            with self.subTest(outcome=outcome):
                with self.assertRaises(ValueError):
                    story.apply_moderation(outcome, reason)
        story.refresh_from_db()
        self.assertEqual(story.status, 'OnModeration')
        self.assertFalse(Notification.objects.filter(story=story).exists())

        draft = _story(self.author, slug='test-draft',
                       status='NotPublished', submitted=False)
        with self.assertRaises(ValueError):
            draft.apply_moderation('approved')
        draft.refresh_from_db()
        self.assertEqual(draft.status, 'NotPublished')


class HandEditingIsNotModeration(TestCase):
    """Решение по работе принимается в разделе `/moderation/`, и только
    там. В админке оставлена карточка работы — редакционная правка полей,
    — и она обязана говорить, что уведомления при этом не было.

    Действия списка, повторявшие три кнопки решения, сняты: они ходили в
    ту же дверь `Story.apply_moderation`, то есть расхождения дать не
    могли, но показать модератору текст, по которому решают, всё равно не
    умели. Проверка самих решений — в `ADecisionReachesTheAuthor` выше и
    в `test_moderation.py`.
    """

    def setUp(self):
        self.moderator = User.objects.create_superuser(
            'moderator', password='x')
        self.client.force_login(self.moderator)
        self.author = User.objects.get(username='aidana')
        self.story = _story(self.author)

    def test_the_list_offers_no_moderation_action(self):
        """Дубля нет и в интерфейсе: выпадающий список действий не
        предлагает решить судьбу работы."""
        page = self.client.get(
            reverse('admin:core_story_changelist')).content.decode()
        for action in ('approve', 'send_back', 'reject'):
            with self.subTest(action=action):
                self.assertNotIn(f'value="{action}"', page)

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
    """Файл из `/media/` открывается в origin сайта, а SVG — это
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
        png = self._form(factories.tiny_image('эмблема.png'))
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
                # 403 — тоже ответ: уведомление руками не заводят.
                self.assertIn(self.client.get(reverse(
                    f'admin:{opts.app_label}_{opts.model_name}_add')
                ).status_code, (200, 403))

    def test_the_moderation_queue_is_a_filter_on_the_story_list(self):
        self.assertEqual(self.client.get(
            reverse('admin:core_story_changelist') + '?status=OnModeration'
        ).status_code, 200)

    def test_a_notification_is_written_by_the_event_not_by_hand(self):
        """Django отдаёт карточку в режиме просмотра, но без формы
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

    def test_no_list_pays_a_query_per_row(self):
        """Список не делает запрос на строку. Сравнение не с абсолютным
        числом, а с самим собой: страница на одну строку и на все строки
        должны стоить одинаково, иначе колонка тянет связь поштучно."""
        def cost(url):
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(self.client.get(url).status_code, 200)
            return len(ctx)

        for model in django_admin.site._registry:
            opts = model._meta
            if model._default_manager.count() < 2:
                continue
            url = reverse(f'admin:{opts.app_label}_{opts.model_name}_changelist')
            first = model._default_manager.order_by('pk').first()
            with self.subTest(model=opts.model_name):
                # Та же страница, урезанная фильтром до одной строки.
                one = cost(f'{url}?pk__exact={first.pk}')
                many = cost(url)
                self.assertLessEqual(many, one + 1, 'N+1 в колонке списка')


class TheHeaderLeadsToModeration(TestCase):
    """Решения — в `/moderation/`, и дверь туда на каждой странице."""

    def test_every_page_links_to_the_moderation_section(self):
        self.client.force_login(
            User.objects.create_superuser('moderator', password='x'))
        page = self.client.get(reverse('admin:index'))
        self.assertContains(page, reverse('core:moderation_queue'))
        self.assertContains(page, 'Qazaqnovel')
        self.assertNotContains(page, 'Django administration')


class ActsAndCountersStayReadOnly(TestCase):
    """Что пересчитывается по строкам или объявляет чужое решение, руками
    не правится: ревизия главы, статус тега, счётчики."""

    def setUp(self):
        self.client.force_login(
            User.objects.create_superuser('moderator', password='x'))

    def test_a_revision_cannot_be_edited_added_or_deleted(self):
        chapter = Chapter.objects.exclude(published_revision=None).first()
        page = self.client.get(
            reverse('admin:core_chapter_change', args=[chapter.pk])
        ).content.decode()
        for name in ('chapterrevision_set-0-body', 'chapterrevision_set-0-state',
                     'chapterrevision_set-0-DELETE',
                     'chapterreaction_set-0-count'):
            with self.subTest(field=name):
                self.assertNotIn(f'name="{name}"', page)
        self.assertIn(chapter.published_revision.body[:20], page)

    def test_a_tag_status_is_not_a_form_field(self):
        """Отказ — только действием с причиной: оно снимает тег с работ и
        пишет авторам."""
        tag = factories.tag(status='pending')
        page = self.client.get(
            reverse('admin:core_tag_change', args=[tag.pk])).content.decode()
        self.assertNotIn('name="status"', page)

    def test_story_counters_are_not_form_fields(self):
        story = Story.objects.first()
        page = self.client.get(
            reverse('admin:core_story_change', args=[story.pk])).content.decode()
        for name in ('views', 'recent_views', 'likes', 'comments'):
            with self.subTest(field=name):
                self.assertNotIn(f'name="{name}"', page)


class AccountRecoveryRebindsTelegram(TestCase):
    """Процедура возврата аккаунта из правил — привязать к нему новый
    Telegram. Кода у неё нет, кроме этого поля."""

    def setUp(self):
        self.client.force_login(
            User.objects.create_superuser('moderator', password='x'))

    def _post(self, user, telegram_id):
        return self.client.post(
            reverse('admin:core_user_change', args=[user.pk]), {
                'username': user.username, 'pen_name': user.pen_name,
                'bio': user.bio, 'email': user.email,
                'telegram_id': telegram_id,
                'telegram_push': 'on', 'push_moderation': 'on',
                'push_response': 'on', 'push_new_chapter': 'on',
                'is_active': 'on',
                'last_login_0': '', 'last_login_1': '',
                'date_joined_0': '2026-01-01', 'date_joined_1': '00:00:00',
            })

    def test_a_new_telegram_is_bound_and_a_taken_one_is_refused(self):
        user = factories.user(telegram_id=factories.next_telegram_id())
        other = factories.user(telegram_id=factories.next_telegram_id())

        response = self._post(user, 424242424)
        self.assertEqual(response.status_code, 302, response.content[:2000])
        user.refresh_from_db()
        self.assertEqual(user.telegram_id, 424242424)

        response = self._post(user, other.telegram_id)
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.telegram_id, 424242424)


class AGrantStaysInsideItsContest(TestCase):
    """Номинация — того же конкурса, работа — из принятых заявок."""

    def setUp(self):
        self.grant = AwardGrant.objects.select_related(
            'contest', 'award', 'story').first()

    def _copy(self, **changes):
        fields = {'contest': self.grant.contest, 'award': self.grant.award,
                  'story': self.grant.story}
        fields.update(changes)
        return AwardGrant(**fields)

    def test_the_existing_grant_is_valid(self):
        self.grant.full_clean()

    def test_an_award_of_another_contest_is_refused(self):
        foreign = ContestAward.objects.exclude(
            contest=self.grant.contest).first()
        with self.assertRaises(ValidationError) as caught:
            self._copy(award=foreign).clean()
        self.assertIn('award', caught.exception.message_dict)

    def test_a_story_without_an_accepted_submission_is_refused(self):
        outsider = Story.objects.exclude(
            submissions__contest=self.grant.contest,
            submissions__status='accepted').first()
        with self.assertRaises(ValidationError) as caught:
            self._copy(story=outsider).clean()
        self.assertIn('story', caught.exception.message_dict)


class IconsComeFromTheSprite(TestCase):
    """Опечатка в иконке рисует пустой квадрат — поле выбирает из спрайта."""

    def test_an_unknown_icon_is_refused_and_a_known_one_accepted(self):
        Form = GenreAdmin(Genre, django_admin.site).get_form(None)
        base = {'slug': 'test-genre', 'name': 'Сынақ', 'hue': 120,
                'position': 99}
        self.assertFalse(Form({**base, 'icon': 'no-such-icon'}).is_valid())
        self.assertTrue(Form({**base, 'icon': 'feather'}).is_valid())
        # У жанра иконка необязательна — пустой выбор остаётся.
        self.assertTrue(Form({**base, 'icon': ''}).is_valid())


def _staff_request():
    """Запрос сотрудника для форм с автокомплитом: виджет спрашивает права."""
    request = RequestFactory().get('/')
    request.user = User.objects.create_superuser(
        factories._uniq('staff'), password='x')
    return request


class TheAuthorsPathIsNotRepeatedHere(TestCase):
    """Что делается в рабочем месте автора, в админке не повторяется
    второй дверью, делающей половину."""

    def setUp(self):
        self.client.force_login(
            User.objects.create_superuser('moderator', password='x'))

    def test_deleting_a_chapter_here_does_what_the_author_would(self):
        """Оставшиеся смыкаются, пікірлер главы становятся общими, статус
        работы пересчитывается — как у `data.delete_chapter`."""
        story = factories.story(chapters=2, status='OnProcess')
        first = story.chapter_set.get(number=1)
        note = factories.comment(story, chapter_number=1)
        response = self.client.post(
            reverse('admin:core_chapter_delete', args=[first.pk]),
            {'post': 'yes'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(story.chapter_set.values_list('number', flat=True)),
                         [1])
        note.refresh_from_db()
        self.assertIsNone(note.chapter_number)

    def test_a_chapter_is_not_added_or_moved_here(self):
        chapter = Chapter.objects.first()
        self.assertEqual(self.client.get(
            reverse('admin:core_chapter_add')).status_code, 403)
        page = self.client.get(
            reverse('admin:core_chapter_change', args=[chapter.pk])
        ).content.decode()
        for name in ('story', 'number', 'position'):
            with self.subTest(field=name):
                self.assertNotIn(f'name="{name}"', page)

    def test_a_submission_is_filed_by_its_author(self):
        self.assertEqual(self.client.get(
            reverse('admin:core_submission_add')).status_code, 403)
        submission = factories.contest().submission_set.create(
            author=(story := factories.story()).author, story=story,
            submitted_on=timezone.localdate())
        page = self.client.get(reverse(
            'admin:core_submission_change', args=[submission.pk])).content.decode()
        for name in ('contest', 'author', 'story', 'submitted_on'):
            with self.subTest(field=name):
                self.assertNotIn(f'name="{name}"', page)
        self.assertIn('name="status"', page)

    def test_the_audience_mark_is_the_authors(self):
        story = Story.objects.first()
        page = self.client.get(
            reverse('admin:core_story_change', args=[story.pk])).content.decode()
        self.assertNotIn('name="audience"', page)

    def test_a_tag_is_rejected_not_deleted(self):
        tag = factories.tag(status='pending')
        self.assertEqual(self.client.get(
            reverse('admin:core_tag_delete', args=[tag.pk])).status_code, 403)
        page = self.client.get(
            reverse('admin:core_tag_changelist')).content.decode()
        self.assertNotIn('value="delete_selected"', page)

    def test_a_rejected_tag_is_not_attached_to_a_story(self):
        inline = StoryTagInline(Story, django_admin.site)
        field = inline.formfield_for_foreignkey(
            StoryTag._meta.get_field('tag'), _staff_request())
        rejected = factories.tag(status='rejected')
        self.assertFalse(field.queryset.filter(pk=rejected.pk).exists())


class TheShowcaseShowsOnlyWhatOpens(TestCase):
    """Подборка и книга недели ведут только к тому, что читатель откроет:
    работа, ушедшая из публичного после того, как её поставили, с
    витрины пропадает."""

    def test_a_collection_drops_a_story_that_left_the_public(self):
        collection = data.all_collections().first()
        story = collection.stories[0]
        Story.objects.filter(pk=story.pk).update(status='NeedsWork')
        fresh = data.all_collections().get(pk=collection.pk)
        self.assertNotIn(story.pk, [s.pk for s in fresh.stories])
        self.assertNotIn(story.pk, [
            s.pk for s in data.collection_by_slug(collection.slug).stories])

    def test_a_collection_of_hidden_stories_is_empty(self):
        collection = data.all_collections().first()
        Story.objects.filter(collection_items__collection=collection).update(
            status='NotPublished')
        self.assertFalse(data.all_collections().filter(pk=collection.pk).exists())

    def test_the_book_of_the_week_falls_back_to_a_public_pick(self):
        draft = factories.story(status='NotPublished', published=False)
        BookOfWeek.objects.create(story=draft, editorial_note='—', quote='—',
                                  published_on=timezone.localdate()
                                  + timezone.timedelta(days=1))
        self.assertNotEqual(data.book_of_week().story, draft)

    def test_the_admin_form_refuses_a_draft(self):
        Form = BookOfWeekAdmin(BookOfWeek, django_admin.site).get_form(
            _staff_request())
        base = {'editorial_note': '—', 'quote': '—',
                'published_on': timezone.localdate()}
        draft = factories.story(status='NotPublished', published=False)
        public = factories.story()
        form = Form({**base, 'story': draft.pk})
        self.assertFalse(form.is_valid())
        self.assertIn('story', form.errors)
        self.assertTrue(Form({**base, 'story': public.pk}).is_valid())


class JournalsTellTheTruth(TestCase):

    def test_an_outcome_is_shown_only_for_a_moderation_event(self):
        column = NotificationAdmin(Notification, django_admin.site).outcome_label
        self.assertEqual(column(Notification(kind='like', outcome='')), '')
        self.assertEqual(column(Notification(kind='moderation', outcome='')),
                         'Модерацияда')

    def test_a_stage_cannot_end_before_it_starts(self):
        stage = TimelineStage.objects.first()
        stage.ends = stage.starts - timezone.timedelta(days=1)
        with self.assertRaises(ValidationError) as caught:
            stage.full_clean()
        self.assertIn('ends', caught.exception.message_dict)

    def test_contest_dates_are_refused_in_words(self):
        contest = Contest.objects.first()
        contest.closes_on = contest.opens_on - timezone.timedelta(days=1)
        with self.assertRaises(ValidationError) as caught:
            contest.full_clean()
        self.assertIn('Қабылдау басталмай', str(caught.exception))


class TagDecisionsLeaveATrace(TestCase):
    """Действие списка Django не журналирует; решение по тегу — пишется."""

    def test_accepting_and_rejecting_are_in_the_history(self):
        moderator = User.objects.create_superuser('moderator', password='x')
        self.client.force_login(moderator)
        accepted = factories.tag(status='pending')
        rejected = factories.tag(status='pending')
        url = reverse('admin:core_tag_changelist')
        self.client.post(url, {'action': 'accept',
                               '_selected_action': [accepted.pk]})
        self.client.post(url, {'action': 'reject', 'apply': '1',
                               'reason': 'Жанрды сипаттамайды.',
                               '_selected_action': [rejected.pk]})
        trail = dict(LogEntry.objects.filter(user=moderator).values_list(
            'object_id', 'change_message'))
        self.assertEqual(trail[str(accepted.pk)], 'Қабылданды.')
        self.assertEqual(trail[str(rejected.pk)],
                         'Қабылданбады: Жанрды сипаттамайды.')


class TheDecisionJournalIsNotDeletedByHand(TestCase):
    """Из последнего акта выводится статус работы: удалённый возврат
    молча делал бы её черновиком. Каскад от удаления самой работы при
    этом проходит — акт по несуществующей работе хранить незачем."""

    def setUp(self):
        self.client.force_login(
            User.objects.create_superuser('moderator', password='x'))
        self.story = _story(User.objects.get(username='aidana'))
        self.story.apply_moderation('needs_work', 'Себебі.')
        self.decision = self.story.moderation_decisions.get()

    def test_there_is_no_door_to_delete_a_decision(self):
        self.assertEqual(self.client.get(reverse(
            'admin:core_moderationdecision_delete',
            args=[self.decision.pk])).status_code, 403)
        page = self.client.get(reverse(
            'admin:core_moderationdecision_changelist')).content.decode()
        self.assertNotIn('value="delete_selected"', page)
        card = self.client.get(reverse(
            'admin:core_moderationdecision_change',
            args=[self.decision.pk])).content.decode()
        self.assertNotIn('deletelink', card)

    def test_deleting_the_story_still_takes_its_decisions(self):
        response = self.client.post(
            reverse('admin:core_story_delete', args=[self.story.pk]),
            {'post': 'yes'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Story.objects.filter(pk=self.story.pk).exists())


class StatusesAreWordsNotCodes(TestCase):
    """Редактор видит те же слова, что автор: `Жазылып жатыр`, а не
    `OnProcess`. Словарь один — в домене; модель строит из него `choices`,
    бейдж на сайте читает его фильтром."""

    def test_every_code_has_a_word(self):
        """Новый статус без подписи уронил бы `choices` модели при импорте
        — но только если его забыли в словаре; проверка — сама полнота."""
        for codes, labels in (
                (story_rules.STORY_STATUSES, story_rules.STORY_STATUS_LABELS),
                (story_rules.STORY_FORMATS, story_rules.STORY_FORMAT_LABELS),
                (story_rules.REVISION_STATES,
                 story_rules.REVISION_STATE_LABELS),
                (tag_rules.TAG_STATUSES, tag_rules.TAG_STATUS_LABELS),
                (contest_rules.SUBMISSION_STATUSES,
                 contest_rules.SUBMISSION_STATUS_LABELS),
                (contest_rules.AI_DECLARATIONS,
                 contest_rules.AI_DECLARATION_LABELS),
                (notification_rules.NOTIF_KINDS,
                 notification_rules.NOTIF_KIND_LABELS)):
            with self.subTest(codes=codes):
                self.assertEqual(set(codes), set(labels))
                self.assertTrue(all(labels.values()))

    def test_the_admin_lists_speak_kazakh(self):
        self.client.force_login(
            User.objects.create_superuser('moderator', password='x'))
        for url, word, code in (
                ('admin:core_story_changelist', 'Жазылып жатыр', 'OnProcess'),
                ('admin:core_story_changelist', 'Көп бөлімді', 'serial'),
                ('admin:core_submission_changelist', 'Қаралуда', 'reviewing'),
                ('admin:core_tag_changelist', 'Тексеруде', 'pending'),
                ('admin:core_notification_changelist', 'Реакция', 'like')):
            with self.subTest(url=url, code=code):
                page = self.client.get(reverse(url)).content.decode()
                self.assertIn(word, page)
                # Код остаётся значением фильтра в адресе — но не текстом.
                self.assertNotIn(f'>{code}<', page)

    def test_the_site_badge_reads_the_same_word(self):
        for key, word in STORY_STATUS_LABELS.items():
            with self.subTest(key=key):
                self.assertIn(word, render_to_string(
                    'components/status_badge.html', {'key': key}))

    def test_the_author_chooses_a_format_by_the_same_words(self):
        """Карточки выбора формата у автора берут слово из того же
        словаря, что и админка."""
        login_as(self.client)
        for url in (reverse('core:new_story'),
                    reverse('core:story_settings', kwargs={'slug': 'aidana-kus'})):
            with self.subTest(url=url):
                page = self.client.get(url).content.decode()
                self.assertIn('Бір бөлімді', page)
                self.assertIn('Көп бөлімді', page)
