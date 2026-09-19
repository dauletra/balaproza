"""Судьба тега: отказ снимает его с работ и объясняет автору, почему.

До этой работы отклонение было одним `update(status='rejected')`, и
обещание держалось наполовину: публике тег переставал показываться
(выдача режет по `accepted`), а у автора он оставался висеть на работе —
без слова о том, что случилось.

Половина тестов здесь про то, чего произойти **не должно**: работа
остаётся опубликованной, текст не трогается, чужие теги не задеты. Самый
важный из них — `TheVerdictDoesNotTouchTheWork`: событие о теге,
записанное как решение по публикации, увело бы работу из каталога, и
заметить это можно было бы только по пропавшей странице.
"""

from django.urls import reverse

from core import data
from core.links import notification_href
from core.models import Notification, Story, StoryTag, Tag, User
from core.tests import factories as f
from core.tests.base import TestCase


def _tagged(story, name: str) -> Tag:
    tag = f.tag(status='pending', slug=name, name=name)
    StoryTag.objects.create(story=story, tag=tag)
    return tag


class ARejectedTagLeavesTheWork(TestCase):

    def setUp(self):
        super().setUp()
        self.author = f.user()
        self.story = f.story(author=self.author, chapters=1)
        self.tag = _tagged(self.story, 'жаман-тег')

    def test_the_link_is_removed_and_the_status_recorded(self):
        data.reject_tags([self.tag], 'Ережеге қайшы.')

        self.tag.refresh_from_db()
        self.assertEqual(self.tag.status, 'rejected')
        self.assertFalse(self.story.tags.filter(pk=self.tag.pk).exists())

    def test_the_author_is_told_with_the_reason(self):
        data.reject_tags([self.tag], 'Ережеге қайшы.')

        note = Notification.objects.get(user=self.author, kind='tag')
        self.assertEqual(note.story, self.story)
        self.assertIn('жаман-тег', note.text)
        self.assertIn('Ережеге қайшы.', note.text)
        # Решение платформы не подписывается именем модератора — как и
        # решение по публикации.
        self.assertIsNone(note.actor)

    def test_the_notification_leads_where_tags_are_edited(self):
        """«Поставь другой» без адреса поля — половина ответа."""
        data.reject_tags([self.tag], 'Ережеге қайшы.')
        note = Notification.objects.get(user=self.author, kind='tag')

        self.assertEqual(
            notification_href(note),
            reverse('core:story_settings', kwargs={'slug': self.story.slug}))

    def test_a_reason_is_required(self):
        """«Нельзя» без «почему» автор исправить не может (BR-11)."""
        with self.assertRaises(ValueError):
            data.reject_tags([self.tag], '   ')

        self.tag.refresh_from_db()
        self.assertEqual(self.tag.status, 'pending')
        self.assertTrue(self.story.tags.filter(pk=self.tag.pk).exists())
        self.assertFalse(Notification.objects.filter(kind='tag').exists())

    def test_every_work_carrying_the_tag_is_told(self):
        second = f.story(author=self.author, chapters=1)
        StoryTag.objects.create(story=second, tag=self.tag)

        changed, told = data.reject_tags([self.tag], 'Ережеге қайшы.')

        self.assertEqual((changed, told), (1, 2))
        self.assertEqual(
            Notification.objects.filter(user=self.author, kind='tag').count(), 2)

    def test_a_tag_on_nobodys_work_just_changes_status(self):
        lonely = f.tag(status='pending')

        changed, told = data.reject_tags([lonely], 'Керек емес.')

        self.assertEqual((changed, told), (1, 0))
        lonely.refresh_from_db()
        self.assertEqual(lonely.status, 'rejected')

    def test_the_neighbours_are_untouched(self):
        keeper = f.tag(status='accepted')
        StoryTag.objects.create(story=self.story, tag=keeper)

        data.reject_tags([self.tag], 'Ережеге қайшы.')

        self.assertTrue(self.story.tags.filter(pk=keeper.pk).exists())
        keeper.refresh_from_db()
        self.assertEqual(keeper.status, 'accepted')


class TheVerdictDoesNotTouchTheWork(TestCase):
    """Самое важное здесь: тег снимается, работа остаётся.

    Событие о теге нельзя записать как `moderation` именно поэтому:
    `Story.refresh_status` выводит статус из **последнего** такого
    события, и отрицательный исход увёл бы опубликованную работу в
    «Толықтыру қажет», то есть из каталога. Заметить это можно было бы
    только по пропавшей странице.
    """

    def setUp(self):
        super().setUp()
        self.author = f.user()
        self.story = f.story(author=self.author, chapters=1)
        self.tag = _tagged(self.story, 'шектеулі')

    def test_a_published_work_stays_published(self):
        data.reject_tags([self.tag], 'Ережеге қайшы.')

        self.story.refresh_from_db()
        self.assertEqual(self.story.status, 'Published')
        self.assertTrue(self.story.is_public)

    def test_it_survives_the_next_status_recount(self):
        """Пересчёт читает последнее решение по работе — событие о теге
        в этот счёт входить не должно."""
        data.reject_tags([self.tag], 'Ережеге қайшы.')

        self.assertEqual(Story.objects.get(pk=self.story.pk).refresh_status(),
                         'Published')

    def test_the_text_is_not_touched(self):
        body = self.story.chapter_set.get().body

        data.reject_tags([self.tag], 'Ережеге қайшы.')

        self.assertEqual(self.story.chapter_set.get().body, body)
        self.assertTrue(self.story.chapter_set.get().is_published)


class AcceptingATagSaysNothing(TestCase):
    """Тег заработал молча: автор увидит, что пометка «тексеруде» ушла с
    чипа, и отдельного события тут нет."""

    def test_it_only_changes_the_status(self):
        author = f.user()
        story = f.story(author=author, chapters=1)
        tag = _tagged(story, 'жақсы-тег')

        data.accept_tags([tag])

        tag.refresh_from_db()
        self.assertEqual(tag.status, 'accepted')
        self.assertTrue(story.tags.filter(pk=tag.pk).exists())
        self.assertFalse(Notification.objects.filter(kind='tag').exists())


class TheModeratorRejectsThroughTheAdmin(TestCase):
    """Тот путь, каким этим пользуются: список тегов и действие над ним."""

    def setUp(self):
        super().setUp()
        self.moderator = User.objects.create_superuser('tagmod', password='x')
        self.client.force_login(self.moderator)
        self.author = f.user()
        self.story = f.story(author=self.author, chapters=1)
        self.tag = _tagged(self.story, 'даулы')
        self.url = reverse('admin:core_tag_changelist')

    def _act(self, **extra):
        return self.client.post(self.url, {
            'action': 'reject',
            '_selected_action': [self.tag.pk],
            **extra,
        }, follow=True)

    def test_it_asks_for_a_reason_before_doing_anything(self):
        page = self._act()

        self.assertContains(page, 'Себебі')
        # Страница обязана назвать цену решения до нажатия: тег снимается
        # со всех работ разом.
        self.assertContains(page, '1 жұмыстан')
        self.tag.refresh_from_db()
        self.assertEqual(self.tag.status, 'pending')

    def test_an_empty_reason_changes_nothing(self):
        page = self._act(apply='1', reason='   ')

        self.assertContains(page, 'Себепті жазу керек')
        self.tag.refresh_from_db()
        self.assertEqual(self.tag.status, 'pending')

    def test_with_a_reason_it_goes_all_the_way(self):
        self._act(apply='1', reason='Балалар алаңына жарамайды.')

        self.tag.refresh_from_db()
        self.assertEqual(self.tag.status, 'rejected')
        self.assertFalse(self.story.tags.exists())
        note = Notification.objects.get(user=self.author, kind='tag')
        self.assertIn('Балалар алаңына жарамайды.', note.text)

    def test_accepting_needs_no_page(self):
        self.client.post(self.url, {'action': 'accept',
                                    '_selected_action': [self.tag.pk]},
                         follow=True)

        self.tag.refresh_from_db()
        self.assertEqual(self.tag.status, 'accepted')
