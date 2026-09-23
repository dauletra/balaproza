"""Задержанный комментарий: что не доходит до читателя и почему (D2).

Сплошной премодерации комментариев нет и не будет — их на порядок
больше, чем глав, а ответ через сутки перестаёт быть разговором.
Задерживается только то, что задел блок-лист.

Половина тестов — про границы правила: точное совпадение у тега против
подстроки у комментария, список тегов против списка комментариев. Спутать
их значит либо подвесить половину ленты, либо не поймать ничего.
"""

from django.test import Client
from django.urls import reverse

from core import data
from core.counters import recount_engagement
from core.models import BlockedTagPattern, StoryComment
from core.tests import factories as f
from core.tests.base import TestCase


def _blocked(pattern: str, scope: str = 'comment') -> BlockedTagPattern:
    return BlockedTagPattern.objects.create(pattern=pattern, scope=scope)


def _moderator(client, username='held_mod'):
    user = f.user(username=username)
    user.is_staff = True
    user.save(update_fields=['is_staff'])
    client.force_login(user)
    return user


class TheBlockListHoldsAComment(TestCase):

    def setUp(self):
        super().setUp()
        self.author = f.user()
        self.story = f.story(author=self.author, chapters=1)
        self.reader = f.user()
        self.client.force_login(self.reader)
        self.url = reverse('core:comment_create',
                           kwargs={'slug': self.story.slug})
        _blocked('жарнама')

    def _post(self, text):
        return self.client.post(self.url, {'text': text}, follow=True)

    def test_a_clean_comment_goes_straight_through(self):
        self._post('Керемет әңгіме.')

        comment = StoryComment.objects.get(author=self.reader)
        self.assertFalse(comment.held)

    def test_a_blocked_word_holds_it(self):
        self._post('Мына жарнама сайтқа кір.')

        comment = StoryComment.objects.get(author=self.reader)
        self.assertTrue(comment.held)

    def test_the_match_is_a_substring_and_ignores_case(self):
        """У тега совпадение точное — одно имя целиком; у комментария так
        нельзя, он не одно слово."""
        for text in ('ЖАРНАМА деген не?', 'жарнамалап жүрміз'):
            with self.subTest(text=text):
                StoryComment.objects.filter(author=self.reader).delete()
                self._post(text)
                self.assertTrue(
                    StoryComment.objects.get(author=self.reader).held)

    def test_the_reader_is_told_it_is_waiting(self):
        """Молчать нельзя: человек решит, что форма сломалась, и напишет
        ещё раз."""
        response = self._post('Мына жарнама сайтқа кір.')

        self.assertContains(response, 'тексеруге жіберілді')

    def test_nobody_sees_it_meanwhile(self):
        """Включая автора работы: показать одному значит объяснять,
        почему второй его не видит."""
        self._post('Мына жарнама сайтқа кір.')

        for who, client in (('қонақ', Client()), ('оқырман', self.client)):
            with self.subTest(who=who):
                page = client.get(reverse('core:story_detail',
                                          kwargs={'slug': self.story.slug}))
                self.assertNotContains(page, 'Мына жарнама сайтқа кір.')

        author_client = Client()
        author_client.force_login(self.author)
        self.assertNotContains(
            author_client.get(reverse('core:story_detail',
                                      kwargs={'slug': self.story.slug})),
            'Мына жарнама сайтқа кір.')

    def test_the_author_of_the_work_is_not_notified_yet(self):
        """Уведомление о том, чего читателю не существует, обещало бы
        разговор, которого нет."""
        self._post('Мына жарнама сайтқа кір.')

        self.assertFalse(
            self.author.notifications.filter(kind='comment').exists())


class TheTwoListsDoNotMix(TestCase):
    """`scope` разводит два правила, и это не экономия таблицы.

    Образец, заведённый под теги, как подстрока задерживал бы каждый
    комментарий, где эта строка встретилась внутри слова: «тест»
    подвесил бы половину ленты.
    """

    def test_a_tag_pattern_does_not_hold_comments(self):
        _blocked('тест', scope='tag')

        self.assertFalse(data.comment_is_blocked('Бұл тест емес.'))

    def test_a_comment_pattern_does_not_block_tags(self):
        _blocked('жарнама', scope='comment')

        self.assertFalse(data.is_blocked('жарнама'))

    def test_both_means_both(self):
        _blocked('спам', scope='both')

        self.assertTrue(data.comment_is_blocked('бұл спам ғой'))
        self.assertTrue(data.is_blocked('спам'))


class TheModeratorDecidesInTwoWays(TestCase):
    """Решений два, не три: править комментарий автор не может, и
    «вернуть на доработку» обещало бы несуществующее действие."""

    def setUp(self):
        super().setUp()
        _blocked('жарнама')
        self.author = f.user()
        self.story = f.story(author=self.author, chapters=1)
        self.reader = f.user()
        reader_client = Client()
        reader_client.force_login(self.reader)
        reader_client.post(
            reverse('core:comment_create', kwargs={'slug': self.story.slug}),
            {'text': 'Мына жарнама сайтқа кір.'})
        self.comment = StoryComment.objects.get(author=self.reader)
        _moderator(self.client)

    def _decide(self, action):
        return self.client.post(
            reverse('core:moderation_comment_decide',
                    kwargs={'pk': self.comment.pk}),
            {'action': action}, follow=True)

    def test_the_queue_shows_it_with_its_full_text(self):
        """Решают по тексту, и обрезка здесь означала бы решение вслепую."""
        page = self.client.get(reverse('core:moderation_comments'))

        self.assertContains(page, 'Мына жарнама сайтқа кір.')
        self.assertContains(page, self.story.title)

    def test_publishing_shows_it_and_tells_the_author(self):
        self._decide('publish')

        self.comment.refresh_from_db()
        self.assertFalse(self.comment.held)
        self.assertContains(
            Client().get(reverse('core:story_detail',
                                 kwargs={'slug': self.story.slug})),
            'Мына жарнама сайтқа кір.')
        # Уведомление уходит здесь, а не при создании: до решения
        # сообщать было не о чем.
        self.assertTrue(
            self.author.notifications.filter(kind='comment').exists())

    def test_deleting_removes_it(self):
        self._decide('delete')

        self.assertFalse(
            StoryComment.objects.filter(pk=self.comment.pk).exists())
        self.assertFalse(
            self.author.notifications.filter(kind='comment').exists())

    def test_an_empty_or_unknown_action_deletes_nothing(self):
        """Удаление — только по явному слову. Раньше им была любая ветка,
        кроме «publish»: пустой запрос безвозвратно стирал реплику."""
        for action in ('', 'whatever'):
            with self.subTest(action=action):
                self._decide(action)
                self.comment.refresh_from_db()
                self.assertTrue(self.comment.held)

    def test_the_confirmation_window_deletes_by_address(self):
        """Окно подтверждения шлёт POST без полей — действие несёт адрес."""
        url = reverse('core:moderation_comment_decide',
                      kwargs={'pk': self.comment.pk})
        page = self.client.get(reverse('core:moderation_comments')).content.decode()
        self.assertIn(f'{url}?action=delete', page)
        self.assertIn("open-delete-confirm", page)
        self.client.post(f'{url}?action=delete')
        self.assertFalse(
            StoryComment.objects.filter(pk=self.comment.pk).exists())

    def test_the_number_is_about_the_whole_queue(self):
        """Число над списком — про всю очередь, а не про страницу в 20."""
        for i in range(21):
            StoryComment.objects.create(story=self.story, author=self.reader,
                                        text=f'Жарнама {i}', held=True)
        page = self.client.get(reverse('core:moderation_comments'))
        self.assertContains(page, '22 пікір шешім күтеді')

    def test_the_section_is_closed_to_everyone_else(self):
        """404, а не 403 — как и весь раздел модерации."""
        reader = Client()
        reader.force_login(f.user())

        for url in (reverse('core:moderation_comments'),
                    reverse('core:moderation_comment_decide',
                            kwargs={'pk': self.comment.pk})):
            with self.subTest(url=url):
                self.assertEqual(reader.get(url).status_code, 404)


class TheCounterCountsWhatTheReaderSees(TestCase):
    """Задержанный блок-листом комментарий не видит никто, включая автора
    работы, — а счётчик его прибавлял: сигнал смотрел на создание строки
    и не смотрел на `held`. Карточка каталога обещала «5 пікір», на
    странице их было четыре.

    Само себя это не чинило: суточная сверка считала по всем строкам и
    потому подтверждала завышенное число.
    """

    def setUp(self):
        super().setUp()
        BlockedTagPattern.objects.get_or_create(
            pattern='счётчик-стоп', defaults={'scope': 'comment'})
        self.story = f.story(author=f.user(), chapters=1)
        self.reader = f.user()

    def _comments(self):
        self.story.refresh_from_db()
        return self.story.comments

    def test_a_held_comment_does_not_touch_the_counter(self):
        before = self._comments()

        held = data.add_comment(self.story, self.reader,
                                text='счётчик-стоп деген сөз', chapter_number=1)

        self.assertTrue(held.held)
        self.assertEqual(self._comments(), before)

    def test_letting_it_through_adds_it(self):
        before = self._comments()
        held = data.add_comment(self.story, self.reader,
                                text='счётчик-стоп деген сөз', chapter_number=1)

        data.publish_held_comment(held)

        self.assertEqual(self._comments(), before + 1)

    def test_deleting_a_held_one_does_not_go_below_the_truth(self):
        before = self._comments()
        held = data.add_comment(self.story, self.reader,
                                text='счётчик-стоп деген сөз', chapter_number=1)

        data.delete_comment(held)

        self.assertEqual(self._comments(), before)

    def test_an_ordinary_comment_still_counts(self):
        before = self._comments()

        data.add_comment(self.story, self.reader, text='Жай пікір',
                         chapter_number=1)

        self.assertEqual(self._comments(), before + 1)

    def test_the_daily_reconciliation_agrees_with_the_signal(self):
        """Сверка обязана считать по тому же правилу: иначе она не чинит
        расхождение, а закрепляет его."""
        data.add_comment(self.story, self.reader, text='Жай пікір',
                         chapter_number=1)
        data.add_comment(self.story, self.reader,
                         text='счётчик-стоп деген сөз', chapter_number=1)
        expected = self._comments()

        recount_engagement()

        self.assertEqual(self._comments(), expected)

    def test_the_number_on_the_page_matches_the_number_on_the_card(self):
        data.add_comment(self.story, self.reader, text='Көрінетін пікір',
                         chapter_number=1)
        data.add_comment(self.story, self.reader,
                         text='счётчик-стоп деген сөз', chapter_number=1)

        page = self.client.get(
            reverse('core:story_detail', kwargs={'slug': self.story.slug})
            + '?chapter=1')

        self.assertEqual(page.context['comments_total'], self._comments())
