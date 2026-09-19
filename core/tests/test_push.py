"""Доставка уведомлений в Telegram: очередь, сообщение, отказы.

Сети здесь нет ни в одном тесте. Отправка подменяется на месте вызова
(`core.management.commands.push_notifications.send_telegram_message`), а
сама она проверяется отдельно — подменой `urlopen`: её работа не «сходить
в Telegram», а правильно понять, что он ответил, и разница между «повторим
через минуту» и «не повторим никогда» стоит своего теста.

Что здесь проверяется по существу: событие уходит один раз, не уходит
дважды, не уходит тому, кому некуда, и не крутится в очереди вечно.
"""

import json
import urllib.error
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core import data
from core.domain.telegram import (
    PUSH_BLOCKED,
    PUSH_FAILED,
    PUSH_OK,
    send_telegram_message,
)
from core.links import push_message
from core.models import Notification, User
from core.tests import factories as f
from core.tests.base import TestCase, login_as

# Токен обязателен, иначе команда честно отказывается работать. Значение
# любое: сама отправка подменена.
TOKEN = override_settings(TELEGRAM_BOT_TOKEN='test-token',
                          SITE_URL='https://qazaqnovel.test')

# Паузы между сообщениями в тестах не нужны — без подмены двести строк
# спали бы восемь секунд на каждом прогоне.
NO_PAUSE = patch('core.management.commands.push_notifications.PAUSE_SECONDS', 0)


def _telegram(*answers):
    """Подменённая отправка, отвечающая по очереди. Один ответ — на все
    вызовы: так читается «в этом тесте Telegram ведёт себя вот так»."""
    replies = list(answers)
    sent = []

    def fake(token, chat_id, text, **kwargs):
        sent.append((chat_id, text))
        return replies.pop(0) if len(replies) > 1 else replies[0]

    fake.sent = sent
    return fake


def _reader(**over):
    """Автор с подключённым Telegram — иначе слать некуда."""
    over.setdefault('telegram_id', f.next_telegram_id())
    return f.user(**over)


@TOKEN
@NO_PAUSE
class TheQueueSendsEachEventOnce(TestCase):

    def setUp(self):
        super().setUp()
        self.author = _reader()
        self.story = f.story(author=self.author, chapters=1)
        data.add_comment(self.story, f.user(), text='Оқыдым.')
        self.note = Notification.objects.get(user=self.author, kind='comment')

    def _run(self, telegram):
        with patch('core.management.commands.push_notifications'
                   '.send_telegram_message', telegram):
            call_command('push_notifications', '--quiet')
        return telegram

    def test_it_goes_out_and_gets_marked(self):
        telegram = self._run(_telegram(PUSH_OK))

        self.assertEqual(len(telegram.sent), 1)
        chat_id, text = telegram.sent[0]
        self.assertEqual(chat_id, self.author.telegram_id)
        self.assertIn('пікір қалдырды', text)

        self.note.refresh_from_db()
        self.assertIsNotNone(self.note.pushed_at)

    def test_the_second_run_sends_nothing(self):
        """Отметка — единственное, что стоит между читателем и вторым
        сообщением о том же событии."""
        self._run(_telegram(PUSH_OK))
        telegram = self._run(_telegram(PUSH_OK))

        self.assertEqual(telegram.sent, [])

    def test_a_failure_leaves_it_for_the_next_run(self):
        """Недоступный Telegram не теряет событие: отметка не ставится."""
        self._run(_telegram(PUSH_FAILED))

        self.note.refresh_from_db()
        self.assertIsNone(self.note.pushed_at)

        telegram = self._run(_telegram(PUSH_OK))
        self.assertEqual(len(telegram.sent), 1)
        self.note.refresh_from_db()
        self.assertIsNotNone(self.note.pushed_at)

    def test_events_go_out_in_the_order_they_happened(self):
        """Иначе решение модератора обгоняет комментарий, на который
        отвечает."""
        data.notify_follow(f.user(), self.author)
        telegram = self._run(_telegram(PUSH_OK))

        kinds = [text.split()[0] for _chat, text in telegram.sent]
        self.assertEqual(len(kinds), 2)
        self.assertIn('пікір қалдырды', telegram.sent[0][1])
        self.assertIn('саған жазылды', telegram.sent[1][1])

    def test_nothing_is_sent_without_a_token(self):
        """В разработке бота нет, и это не ошибка: событие уже на сайте.

        Молчать команда при этом не должна — предупреждение ловится в
        буфер, иначе оно садится в вывод прогона как настоящая жалоба.
        """
        telegram = _telegram(PUSH_OK)
        warning = StringIO()
        with override_settings(TELEGRAM_BOT_TOKEN=''):
            with patch('core.management.commands.push_notifications'
                       '.send_telegram_message', telegram):
                call_command('push_notifications', '--quiet', stderr=warning)
        self.assertIn('TELEGRAM_BOT_TOKEN', warning.getvalue())

        self.assertEqual(telegram.sent, [])
        self.note.refresh_from_db()
        self.assertIsNone(self.note.pushed_at)


@TOKEN
@NO_PAUSE
class TheQueueSkipsWhoCannotBeReached(TestCase):

    def _run(self, telegram):
        with patch('core.management.commands.push_notifications'
                   '.send_telegram_message', telegram):
            call_command('push_notifications', '--quiet')
        return telegram

    def test_an_author_without_telegram_is_not_in_the_queue(self):
        """Сидовые и тестовые аккаунты без `telegram_id` существуют, и
        слать им некуда — не ошибка, а отсутствие адреса."""
        author = f.user()
        story = f.story(author=author, chapters=1)
        data.add_comment(story, f.user(), text='Оқыдым.')

        telegram = self._run(_telegram(PUSH_OK))

        self.assertEqual(telegram.sent, [])

    def test_a_switched_off_channel_is_not_in_the_queue(self):
        author = _reader(telegram_push=False)
        story = f.story(author=author, chapters=1)
        data.add_comment(story, f.user(), text='Оқыдым.')

        telegram = self._run(_telegram(PUSH_OK))

        self.assertEqual(telegram.sent, [])
        # Событие при этом остаётся: выключен канал, а не уведомления.
        self.assertEqual(
            Notification.objects.filter(user=author, kind='comment').count(), 1)

    def test_a_blocked_bot_switches_the_channel_off(self):
        """Иначе очередь ломится в закрытую дверь на каждом проходе."""
        author = _reader()
        story = f.story(author=author, chapters=1)
        data.add_comment(story, f.user(), text='Оқыдым.')

        self._run(_telegram(PUSH_BLOCKED))

        author.refresh_from_db()
        self.assertFalse(author.telegram_push)
        # Строка уходит из очереди вместе с каналом: доставить её уже
        # нечем, и место в очереди она занимать не должна.
        note = Notification.objects.get(user=author, kind='comment')
        self.assertIsNotNone(note.pushed_at)

    def test_the_rest_of_a_blocked_authors_batch_is_not_attempted(self):
        """Выборка сделана до того, как выключатель снялся, — остальные
        его строки в этом же проходе слать уже незачем."""
        author = _reader()
        story = f.story(author=author, chapters=1)
        data.add_comment(story, f.user(), text='Бірінші.')
        data.add_comment(story, f.user(), text='Екінші.')
        data.add_comment(story, f.user(), text='Үшінші.')

        telegram = self._run(_telegram(PUSH_BLOCKED))

        self.assertEqual(len(telegram.sent), 1)
        self.assertEqual(
            Notification.objects.filter(user=author, pushed_at__isnull=True)
            .count(), 0)

    def test_a_stale_event_is_never_sent(self):
        """«Главу одобрили» через сутки после события приходит человеку,
        который давно всё увидел на сайте, и выглядит сбоем. Заодно это
        и конец очереди: просроченное уходит из выборки само."""
        author = _reader()
        story = f.story(author=author, chapters=1)
        data.add_comment(story, f.user(), text='Оқыдым.')
        Notification.objects.filter(user=author).update(
            created_at=timezone.now() - timedelta(hours=5))

        telegram = self._run(_telegram(PUSH_OK))

        self.assertEqual(telegram.sent, [])


@TOKEN
class TheMessageCarriesTheSubjectAndTheLink(TestCase):
    """Сообщение — фраза плюс абсолютный адрес предмета. Относительный
    путь в мессенджере не ссылка, а строка."""

    def test_a_comment_names_the_reader_the_work_and_quotes_them(self):
        author = _reader()
        reader = f.user(pen_name='Айгерім')
        story = f.story(author=author, chapters=1, title='Айданың таңы')
        data.add_comment(story, reader, text='Соңы керемет.')
        note = Notification.objects.get(user=author, kind='comment')

        text = push_message(note)

        self.assertIn('Айгерім', text)
        self.assertIn('Айданың таңы', text)
        self.assertIn('«Соңы керемет.»', text)
        self.assertIn(f'https://qazaqnovel.test/story/{story.slug}/', text)

    def test_a_moderation_verdict_leads_into_the_cabinet(self):
        """Работы может не быть в публичном каталоге — решение ведёт туда,
        где автор может что-то сделать."""
        author = _reader()
        story = f.story(author=author, chapters=1, published=False)
        f.submit(story)
        note = story.apply_moderation('needs_work', 'Соңы жоқ.')

        text = push_message(note)

        self.assertIn('Толықтыру қажет', text)
        self.assertIn('Соңы жоқ.', text)
        self.assertIn(f'https://qazaqnovel.test/write/{story.slug}/', text)

    def test_a_title_with_markup_characters_is_not_escaped_away(self):
        """Сообщение уходит без `parse_mode` именно ради этого: `<` и `&`
        в названии не должны ни ломать сообщение, ни требовать
        экранирования."""
        author = _reader()
        story = f.story(author=author, chapters=1, title='Сен & мен <бірге>')
        data.add_comment(story, f.user(), text='Оқыдым.')
        note = Notification.objects.get(user=author, kind='comment')

        self.assertIn('Сен & мен <бірге>', push_message(note))


@TOKEN
@NO_PAUSE
class TheAuthorChoosesWhatArrives(TestCase):
    """Три семьи, а не один выключатель.

    Ради этого этап и заведён: у автора с живым сериалом отклики идут
    потоком, а решение модератора приходит редко и важнее всего
    остального. Общий «выключить» отнимал бы второе вместе с первым — то
    же самое, что блокировка бота, только изнутри продукта.
    """

    def setUp(self):
        super().setUp()
        self.author = _reader()
        self.story = f.story(author=self.author, chapters=1)

    def _queued(self, kind: str) -> Notification:
        return Notification.objects.create(
            user=self.author, kind=kind, story=self.story, text='оқиға')

    def test_a_switched_off_family_stays_out_of_the_queue(self):
        for category in data.PUSH_CATEGORIES:
            with self.subTest(category.field):
                Notification.objects.all().delete()
                for kind in category.kinds:
                    self._queued(kind)
                setattr(self.author, category.field, False)
                self.author.save(update_fields=[category.field])

                self.assertEqual(data.pending_pushes(), [])

                setattr(self.author, category.field, True)
                self.author.save(update_fields=[category.field])

    def test_the_families_are_independent(self):
        """Выключенные отклики не уносят с собой решение модератора — весь
        смысл разделения в этом."""
        self._queued('comment')
        self._queued('moderation')
        self.author.push_response = False
        self.author.save(update_fields=['push_response'])

        kinds = [n.kind for n in data.pending_pushes()]

        self.assertEqual(kinds, ['moderation'])

    def test_the_site_feed_is_untouched(self):
        """Выключается канал, а не события: колокольчик считает своё."""
        self._queued('comment')
        self.author.push_response = False
        self.author.save(update_fields=['push_response'])

        self.assertEqual(data.pending_pushes(), [])
        self.assertEqual(data.unread_count_for_user(self.author), 1)


class TheSwitchesLiveInTheProfileForm(TestCase):
    """`/me/edit/` — единственное место, где человек их трогает."""

    FIELDS = {'username': 'aidana', 'pen_name': 'Аты',
              'bio': '', 'gender': '', 'birth_date': ''}

    def setUp(self):
        super().setUp()
        self.user = login_as(self.client)

    def _post(self, **overrides):
        payload = dict(self.FIELDS)
        payload.update(overrides)
        return self.client.post(reverse('core:profile_me_edit'), payload)

    def _fresh(self):
        return User.objects.get(pk=self.user.pk)

    def test_the_page_offers_every_family(self):
        page = self.client.get(reverse('core:profile_me_edit'))

        for category in data.PUSH_CATEGORIES:
            self.assertContains(page, category.label)
            self.assertContains(page, f'name="{category.field}"')

    def test_an_unchecked_box_switches_the_family_off(self):
        """Снятая галка браузером не отправляется вовсе — «нет» это
        отсутствие поля, и форма обязана читать его именно так."""
        self._post(push_moderation='on', push_new_chapter='on')

        user = self._fresh()
        self.assertTrue(user.push_moderation)
        self.assertFalse(user.push_response)
        self.assertTrue(user.push_new_chapter)

    def test_saving_reopens_a_channel_the_platform_closed(self):
        """Бот был заблокирован, человек вернулся и подтвердил, что хочет
        получать хотя бы что-то. Держать дверь закрытой после этого значит
        молча игнорировать просьбу; если бота не разблокировали, первая же
        отправка закроет её снова."""
        data.disable_push(self.user)

        self._post(push_moderation='on')

        self.assertTrue(self._fresh().telegram_push)

    def test_saving_everything_off_does_not_reopen_it(self):
        data.disable_push(self.user)

        self._post()

        self.assertFalse(self._fresh().telegram_push)

    def test_a_rejected_form_changes_nothing(self):
        """Ошибка в соседнем поле не должна тихо переписать настройки —
        то же правило, что у остального профиля."""
        self._post(username='!!', push_moderation='on')

        user = self._fresh()
        self.assertEqual(user.username, 'aidana')
        self.assertTrue(user.push_response)


class EveryKindBelongsToExactlyOneFamily(TestCase):
    """Вид события, не попавший ни в одну семью, не дошёл бы никогда —
    и молча: условие выборки собирается по семьям."""

    def test_the_families_cover_all_six_kinds(self):
        self.assertEqual(set(data.PUSH_KIND_FIELD), set(data.NOTIF_KINDS))

    def test_no_kind_is_claimed_twice(self):
        claimed = [kind for c in data.PUSH_CATEGORIES for kind in c.kinds]
        self.assertEqual(len(claimed), len(set(claimed)))


class TheSenderUnderstandsWhatTelegramAnswered(TestCase):
    """Работа отправки — не «сходить в сеть», а понять ответ: разница
    между «повторим» и «не повторим никогда» решает судьбу канала."""

    def _answer(self, status=200, code=None, description=''):
        if code is None:
            response = patch('urllib.request.urlopen')
            mock = response.start()
            self.addCleanup(response.stop)
            mock.return_value.__enter__.return_value.status = status
            return
        body = json.dumps({'ok': False, 'description': description}).encode()
        error = urllib.error.HTTPError(
            'url', code, description, {}, None)
        error.read = lambda: body
        patcher = patch('urllib.request.urlopen', side_effect=error)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_delivered_message(self):
        self._answer(status=200)
        self.assertEqual(send_telegram_message('t', 1, 'сәлем'), PUSH_OK)

    def test_a_blocked_bot_is_permanent(self):
        self._answer(code=403, description='Forbidden: bot was blocked by the user')
        self.assertEqual(send_telegram_message('t', 1, 'сәлем'), PUSH_BLOCKED)

    def test_a_missing_chat_is_permanent(self):
        """Человек не дал права писать — дверь закрыта так же, как и
        блокировкой, и повторять нечего."""
        self._answer(code=400, description='Bad Request: chat not found')
        self.assertEqual(send_telegram_message('t', 1, 'сәлем'), PUSH_BLOCKED)

    def test_a_bad_token_is_not_the_readers_fault(self):
        """Наша ошибка, а не закрытая дверь: выключать канал человеку из-за
        неверного токена значит тихо отписать всех разом."""
        self._answer(code=401, description='Unauthorized')
        self.assertEqual(send_telegram_message('t', 1, 'сәлем'), PUSH_FAILED)

    def test_a_rate_limit_is_temporary(self):
        self._answer(code=429, description='Too Many Requests: retry after 5')
        self.assertEqual(send_telegram_message('t', 1, 'сәлем'), PUSH_FAILED)

    def test_a_dead_network_is_temporary(self):
        patcher = patch('urllib.request.urlopen',
                        side_effect=urllib.error.URLError('no route'))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertEqual(send_telegram_message('t', 1, 'сәлем'), PUSH_FAILED)

    def test_an_unreadable_answer_is_temporary(self):
        """Чужая HTML-страница от прокси не повод закрыть канал навсегда."""
        self._answer(code=502, description='<html>Bad Gateway</html>')
        self.assertEqual(send_telegram_message('t', 1, 'сәлем'), PUSH_FAILED)
