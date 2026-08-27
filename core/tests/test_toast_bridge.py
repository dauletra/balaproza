"""Ф15, Этап 0 · мост django.contrib.messages -> window-событие 'toast' (base.html).

Формы записи (write/story/contests/profile) начиная с Этапа 1 будут отвечать
на POST редиректом (Post/Redirect/Get) + messages.add_message(...); своего
транспорта тосты не заводят — base.html обязан превратить messages в то же
window-событие 'toast', которое уже слушает components/toast_host.html.
"""

from django.contrib import messages
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.template.loader import render_to_string
from django.test import RequestFactory

from core.tests.base import TestCase


def _rendered_base(request_messages=()):
    """base.html так, как его увидел бы браузер сразу после PRG-редиректа."""
    rf = RequestFactory()
    request = rf.get('/')
    SessionMiddleware(lambda r: None).process_request(request)
    request.session.save()
    MessageMiddleware(lambda r: None).process_request(request)
    for level, text in request_messages:
        messages.add_message(request, level, text)
    return render_to_string('base.html', {}, request=request)


class MessagesToastBridge(TestCase):

    def test_no_messages_renders_no_bridge_script(self):
        html = _rendered_base()
        self.assertNotIn('DOMContentLoaded', html)

    def test_success_message_dispatches_toast_with_matching_kind(self):
        html = _rendered_base([(messages.SUCCESS, 'Сақталды')])
        self.assertIn("kind: 'success'", html)
        self.assertIn("text: 'Сақталды'", html)

    def test_error_message_uses_error_kind(self):
        # message.tags == 'error' дословно совпадает со словарём kind у
        # toast_host — своего маппинга уровень -> kind не требуется.
        html = _rendered_base([(messages.ERROR, 'Қате шықты')])
        self.assertIn("kind: 'error'", html)

    def test_multiple_messages_each_get_their_own_dispatch(self):
        html = _rendered_base([
            (messages.SUCCESS, 'Бірінші'),
            (messages.WARNING, 'Екінші'),
        ])
        self.assertEqual(html.count('dispatchEvent'), 2)
        self.assertIn("kind: 'warning'", html)

    def test_message_text_is_js_escaped(self):
        # Инлайн-скрипт остаётся валидным JS даже если текст сообщения
        # содержит кавычки — иначе одна форма с апострофом в тексте ошибки
        # ломает весь <script> на странице.
        html = _rendered_base([(messages.INFO, 'It\'s "quoted"')])
        self.assertIn('It\\u0027s \\u0022quoted\\u0022', html)
        self.assertNotIn('It\'s "quoted"', html)
