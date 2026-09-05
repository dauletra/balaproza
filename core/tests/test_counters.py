"""Счётчики-кэши (`core/counters.py`): сигнал обязан пережить путь, которым
доменная функция не пользовалась — массовое удаление в админке и каскад от
удаления пользователя. Ручной `F()` внутри `add_comment`/`toggle_follow` и
подобных проверяют уже существующие тесты `test_story.py`/`test_profile.py`;
здесь — только обходные пути, ради которых сигналы и завелись.
"""

from django.urls import reverse

from core import data
from core.models import ChapterReactionVote, Follow, Story, User
from core.tests import factories
from core.tests.base import TestCase


class AdminBulkDeleteKeepsTheCounterHonest(TestCase):
    """Модерация комментариев в MVP — штатное удаление списком в админке
    (`core/admin.py`), не вызов `data.delete_comment`. `queryset.delete()`
    раньше уходил в обход счётчика и оставлял `Story.comments` на старом
    значении."""

    def setUp(self):
        self.moderator = User.objects.create_superuser('moderator', password='x')
        self.client.force_login(self.moderator)
        self.story = factories.story()
        reader = factories.user()
        self.c1 = factories.comment(self.story, author=reader)
        self.c2 = factories.comment(self.story, author=reader)

    def test_delete_selected_action_decrements_the_story_counter(self):
        self.story.refresh_from_db()
        self.assertEqual(self.story.comments, 2)

        url = reverse('admin:core_storycomment_changelist')
        payload = {'action': 'delete_selected',
                   '_selected_action': [self.c1.pk, self.c2.pk]}
        self.client.post(url, payload)  # страница подтверждения, ничего не удаляет
        self.client.post(url, {**payload, 'post': 'yes'})  # подтверждено

        self.story.refresh_from_db()
        self.assertEqual(self.story.comments, 0)


class UserDeletionCascadesWithoutLeavingCountersStale(TestCase):
    """Удаление аккаунта уносит его комментарии, голоса реакций и подписки
    каскадом (`on_delete=CASCADE`) в обход любой доменной функции —
    единственное, что может это заметить, это сигнал на самой модели-
    источнике."""

    def test_deleting_the_author_of_a_comment_decrements_story_comments(self):
        story = factories.story()
        author = factories.user()
        factories.comment(story, author=author)
        story.refresh_from_db()
        self.assertEqual(story.comments, 1)

        author.delete()
        story.refresh_from_db()
        self.assertEqual(story.comments, 0)

    def test_deleting_a_voter_decrements_story_likes_and_the_reaction_count(self):
        story = factories.story(chapters=1)
        chapter = story.chapter_set.get()
        voter = factories.user()
        ChapterReactionVote.objects.create(chapter=chapter, user=voter, kind='kuldim')
        story.refresh_from_db()
        self.assertEqual(story.likes, 1)
        self.assertEqual(chapter.reactions.get(kind='kuldim').count, 1)

        voter.delete()
        story.refresh_from_db()
        self.assertEqual(story.likes, 0)
        self.assertEqual(chapter.reactions.get(kind='kuldim').count, 0)

    def test_deleting_a_follower_decrements_the_followed_users_count(self):
        author = factories.user()
        follower = factories.user()
        Follow.objects.create(follower=follower, following=author)
        author.refresh_from_db()
        self.assertEqual(author.followers, 1)

        follower.delete()
        author.refresh_from_db()
        self.assertEqual(author.followers, 0)


class ReconciliationFixesWhateverTheSignalCouldNotSee(TestCase):
    """`recount_engagement` — не механизм движения счётчика, а страховка
    поверх него: чинит то, что сигнал в принципе не мог увидеть —
    `bulk_update`, ручную правку в базе, восстановленный бэкап."""

    def test_a_hand_corrupted_counter_is_restored_from_real_rows(self):
        story = factories.story()
        factories.comment(story)
        Story.objects.filter(pk=story.pk).update(comments=999)  # мимо сигнала

        data.recount_engagement()

        story.refresh_from_db()
        self.assertEqual(story.comments, 1)
