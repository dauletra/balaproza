"""Предел частоты: сколько раз в минуту человек может это сделать.

Вход через Telegram убирает ботов и не убирает подростка, решившего
пошалить. Предела не было нигде, и самый дешёвый способ испортить
страницу произведения всем сразу — сто комментариев за минуту.

Проверяется не «сколько именно», а то, ради чего предел заведён: поток
останавливается, живой человек его не замечает, и отказ ничего не пишет
в базу.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from core import data
from core.models import Follow, Report, StoryComment
from core.queries.throttle import LIMITS
from core.tests import factories as f
from core.tests.base import TestCase


class TheStreamStops(TestCase):

    def setUp(self):
        super().setUp()
        self.reader = f.user()
        self.client.force_login(self.reader)
        self.story = f.story(chapters=1)
        self.url = reverse('core:comment_create',
                           kwargs={'slug': self.story.slug})

    def _comment(self, text='Оқыдым.'):
        return self.client.post(self.url, {'text': text})

    def test_the_first_ten_go_through_and_the_eleventh_does_not(self):
        limit = LIMITS['comment'][2]
        for number in range(limit):
            self._comment(f'Пікір {number}')

        self._comment('Артығы')

        self.assertEqual(
            StoryComment.objects.filter(author=self.reader).count(), limit)

    def test_the_refusal_says_so_and_writes_nothing(self):
        for number in range(LIMITS['comment'][2]):
            self._comment(f'Пікір {number}')
        before = StoryComment.objects.filter(author=self.reader).count()

        response = self.client.post(self.url, {'text': 'Артығы'}, follow=True)

        self.assertContains(response, 'Тым жиі')
        self.assertEqual(
            StoryComment.objects.filter(author=self.reader).count(), before)

    def test_a_minute_later_the_door_opens_again(self):
        """Окно скользящее: предел — против потока, а не против человека."""
        for number in range(LIMITS['comment'][2]):
            self._comment(f'Пікір {number}')
        StoryComment.objects.filter(author=self.reader).update(
            created_at=timezone.now() - timedelta(minutes=2))

        self._comment('Кейінірек')

        self.assertEqual(
            StoryComment.objects.filter(author=self.reader).count(),
            LIMITS['comment'][2] + 1)

    def test_the_neighbour_is_not_affected(self):
        """Считается по человеку, а не по работе: один болтун не должен
        запирать комментарии всем остальным."""
        for number in range(LIMITS['comment'][2]):
            self._comment(f'Пікір {number}')

        other = f.user()
        self.client.force_login(other)
        self._comment('Менің пікірім')

        self.assertEqual(StoryComment.objects.filter(author=other).count(), 1)


class EveryGuardedActionHasItsLimit(TestCase):
    """Четыре действия, и у каждого свой потолок — но правило одно."""

    def test_reports_stop_flooding_the_moderation_queue(self):
        reporter = f.user()
        self.client.force_login(reporter)
        limit = LIMITS['report'][2]
        for _ in range(limit + 2):
            story = f.story(chapters=1)
            self.client.post(reverse('core:story_report',
                                     kwargs={'slug': story.slug}),
                             {'reason': 'spam', 'comment': 'жарнама'})

        self.assertEqual(Report.objects.filter(reporter=reporter).count(), limit)

    def test_follows_stop(self):
        follower = f.user()
        self.client.force_login(follower)
        limit = LIMITS['follow'][2]
        for _ in range(limit + 2):
            target = f.user()
            self.client.post(reverse('core:follow_toggle',
                                     kwargs={'username': target.username}))

        self.assertEqual(Follow.objects.filter(follower=follower).count(), limit)

    def test_reactions_stop_quietly(self):
        """У реакции нет своей страницы, и тост поверх htmx-перерисовки
        читался бы как поломка: кнопка просто возвращается прежней."""
        reader = f.user()
        self.client.force_login(reader)
        limit = LIMITS['reaction'][2]
        story = f.story(chapters=limit + 2)

        for number in range(1, limit + 3):
            self.client.post(
                reverse('core:chapter_react',
                        kwargs={'slug': story.slug, 'chapter': number}),
                {'kind': 'juregim'})

        self.assertEqual(
            reader.chapter_reaction_votes.count(), limit)

    def test_a_guest_is_never_throttled_by_this(self):
        """Гостю все четыре действия закрыты входом — предел о нём ничего
        не знает и знать не должен."""
        for action in LIMITS:
            with self.subTest(action=action):
                self.assertFalse(data.too_often(action, None))
