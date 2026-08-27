"""Каркас портала: маршруты, вход, контекст, гейты, состояния DEC-17.

Пять файлов сошлись сюда потому, что отвечают на один вопрос — **держится
ли обвязка**. Ни один из них не про раздел: сломанный `{% url %}`,
потерянный `{% include %}`, гейт без причины и мост сообщений ломаются
одинаково на любой странице и одинаково незаметно.

Смоук идёт по корпусу намеренно: он отвечает на «страница рендерится», а
страница, на которой ничего нет, рендерится и будучи сломанной.
"""

from unittest import mock

from django.contrib import messages
from django.contrib.auth import get_user
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.template.loader import render_to_string
from django.test import RequestFactory, override_settings
from django.urls import reverse

from core import data
from core.context_processors import auth_state, nav_state
from core.models import User
from core.tests.base import TestCase, login_as, login_as_newcomer
from core.views import DEMO_USERNAME

# (имя маршрута, kwargs, подпись для subTest)
PUBLIC_URLS = [
    ('core:home',              {},                                'home'),
    ('core:login',             {},                                'auth/login'),
    ('core:signup',            {},                                'auth/signup'),
    ('core:signup_success',    {},                                'auth/signup-success'),
    ('core:catalog',           {},                                'catalog'),
    ('core:search_results',    {},                                'search-results'),
    ('core:genre_index',       {},                                'genre-index'),
    ('core:genre_detail',      {'slug': 'fantastika'},            'genre-detail'),
    ('core:tag_detail',        {'slug': 'mektep'},                'tag-detail'),
    ('core:collections',       {},                                'collections'),
    ('core:collection_detail', {'slug': 'zhas-zhurek'},           'collection-detail'),
    ('core:story_detail',      {'slug': 'dalney-berega'},         'story-detail'),
    ('core:my_stories',        {},                                'my-stories'),
    ('core:new_story',         {},                                'new-story'),
    ('core:manage_story',      {'slug': 'sample'},                'manage-story'),
    ('core:story_settings',    {'slug': 'sample'},                'story-settings'),
    ('core:chapter_new',       {'slug': 'sample'},                'chapter-new'),
    ('core:chapter_edit',      {'slug': 'sample', 'chapter': 1},  'chapter-edit'),
    ('core:profile_me',        {},                                'profile-me'),
    ('core:profile_other',     {'username': 'rudazov'},           'profile-other'),
    ('core:profile_people',    {'username': 'aidana', 'kind': 'followers'}, 'profile-followers'),
    ('core:profile_people',    {'username': 'aidana', 'kind': 'following'}, 'profile-following'),
    ('core:library',           {},                                'library'),
    ('core:notifications',     {},                                'notifications'),
    ('core:contest_list',      {},                                'contest-list'),
    ('core:contest_detail',    {'slug': 'altyn-qalam'},           'contest-detail'),
    ('core:contest_submit',    {'slug': 'altyn-qalam'},           'contest-submit'),
    ('core:my_submissions',    {},                                'my-submissions'),
]

DEBUG_ONLY_URLS = ['core:design_tokens', 'core:design_components', 'core:design_states']


class EveryRouteRenders(TestCase):
    """Самая дешёвая защита от типовых поломок: сломанный `{% url %}`,
    потерянный `{% include %}`, запрещённое имя переменной, зацикленный
    include, упавший фильтр. Всё это валит страницу целиком и ловится
    только заходом на неё."""

    def _walk(self, label):
        for name, kwargs, url_label in PUBLIC_URLS:
            with self.subTest(mode=label, url=url_label):
                url = reverse(name, kwargs=kwargs)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200,
                                 msg=f'GET {url} ({label}) -> {response.status_code}')

    def test_as_a_guest(self):
        self._walk('guest')

    def test_as_a_newcomer_with_nothing_of_their_own(self):
        """Вошедший без единой строки контента: смоук отвечает на «страница
        рендерится», а не «у автора есть что показать»."""
        login_as_newcomer(self.client, 'tester', name='Test User')
        self._walk('authed')

    def test_as_an_author_with_a_full_shelf(self):
        """Второй вошедший нужен потому, что половина веток шаблона живёт
        только при непустых данных: полки, полоса внимания, заявки."""
        login_as(self.client)
        self._walk('authored')


class DesignPagesAreDebugOnly(TestCase):
    """Витрина компонентов не должна открываться в проде."""

    def test_they_are_gone_without_debug(self):
        for name in DEBUG_ONLY_URLS:
            with self.subTest(url=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 404)

    @override_settings(DEBUG=True)
    def test_they_render_with_debug(self):
        for name in DEBUG_ONLY_URLS:
            with self.subTest(url=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)


class SigningIn(TestCase):
    """Провайдера личности пока нет — до Telegram (FR-AUTH-01, NFR-25)
    кнопка подписывает в демо-аккаунт. Поэтому проверяется не «какой
    пароль подошёл», а то, что переживёт смену механизма."""

    def test_login_authenticates_and_rotates_the_session(self):
        """Ключ, выданный гостю, не должен оставаться при нём после входа
        (session fixation): подсунутый до входа ключ стал бы ключом
        вошедшего. Session-флаг этого не делал."""
        session = self.client.session
        session['seen_before'] = True
        session.save()
        before = session.session_key

        response = self.client.post(reverse('core:login'))
        self.assertRedirects(response, reverse('core:home'))
        self.assertEqual(get_user(self.client).username, DEMO_USERNAME)
        self.assertNotEqual(self.client.session.session_key, before)

    def test_next_is_honoured_but_never_leaves_the_site(self):
        target = reverse('core:library')
        self.assertRedirects(
            self.client.post(f"{reverse('core:login')}?next={target}"), target)
        for evil in ('http://evil.example.com/', 'https://evil.example.com/login',
                     '//evil.example.com/'):
            with self.subTest(evil=evil):
                response = self.client.post(f"{reverse('core:login')}?next={evil}")
                self.assertEqual(response.url, reverse('core:home'))

    @mock.patch('core.views.auth.DEMO_USERNAME', 'no-such-account')
    def test_an_empty_database_is_not_a_500(self):
        """Причина («нет пользователя, выполни seed_demo») уходит в лог: она
        адресована тому, кто разворачивал портал, а не тому, кто нажал
        кнопку. `next` при этом не теряется — иначе повтор уводит не туда."""
        target = reverse('core:library')
        with self.assertLogs('core.views', level='WARNING'):
            response = self.client.post(reverse('core:login'), {'next': target})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Кіру уақытша мүмкін емес')
        self.assertFalse(get_user(self.client).is_authenticated)
        self.assertEqual(response.context['next'], target)

    def test_logout_is_post_only_and_idempotent(self):
        self.client.post(reverse('core:login'))
        self.assertEqual(self.client.get(reverse('core:logout')).status_code, 405)
        self.assertRedirects(self.client.post(reverse('core:logout')),
                             reverse('core:home'))
        self.assertFalse(get_user(self.client).is_authenticated)
        self.assertEqual(self.client.post(reverse('core:logout')).status_code, 302)

    def test_signup_signs_in_but_creates_no_account(self):
        """Аккаунт заводит Telegram (FR-AUTH-03). Пока провайдера нет,
        придуманный ник некуда деть — и вписывать его в чужой аккаунт
        нельзя. Раньше он попадал в сессию и здоровался с человеком,
        которого в базе не существовало."""
        before = User.objects.count()
        response = self.client.post(reverse('core:signup'), {'name': 'Айгерім'})
        self.assertRedirects(response, reverse('core:signup_success'))
        self.assertEqual(User.objects.count(), before)
        self.assertEqual(get_user(self.client).username, DEMO_USERNAME)


class TemplateContext(TestCase):
    """Что видит каждый шаблон о том, кто на него смотрит."""

    def _request_as(self, user=None, path='/'):
        request = RequestFactory().get(path)
        request.user = user or AnonymousUser()
        return request

    def test_a_guest_carries_nothing(self):
        ctx = auth_state(self._request_as())
        self.assertFalse(ctx['signed_in'])
        self.assertEqual(ctx['current_user_name'], '')
        self.assertEqual(ctx['current_user_username'], '')
        self.assertEqual(ctx['unread_notifications'], 0)

    def test_the_greeting_uses_the_persons_own_name(self):
        """«Қайта қош келдің, Айдана», а не «, aidana»: читателю автор
        известен под лақап аты, но приветствие обращено к нему самому.
        Фамилии тоже нет — с «сен» (docs/16) она звучит вызовом к доске."""
        aidana = User.objects.get(username='aidana')
        ctx = auth_state(self._request_as(aidana))
        self.assertTrue(ctx['signed_in'])
        self.assertEqual(ctx['current_user_username'], 'aidana')
        self.assertEqual(ctx['current_user_name'], 'Айдана')
        # Число не вписывается литералом: вторая копия разъезжалась бы с
        # первой при каждой правке демо-корпуса.
        self.assertEqual(ctx['unread_notifications'],
                         data.unread_count_for_user('aidana'))

        nameless = User.objects.create_user('nameless', pen_name='Түнгі жазушы')
        self.assertEqual(auth_state(self._request_as(nameless))['current_user_name'],
                         'Түнгі жазушы')

    def test_nav_highlights_the_section_by_path(self):
        cases = [('/', 'home'), ('/library/', 'library'), ('/write/', 'write'),
                 ('/write/sample/', 'write'), ('/notifications/', 'notifications'),
                 ('/me/', 'profile'), ('/u/rudazov/', 'profile'),
                 ('/contests/', 'contests'), ('/contests/altyn-qalam/', 'contests'),
                 ('/catalog/', 'catalog'), ('/genres/', 'catalog'),
                 ('/collections/', 'catalog'), ('/search/', 'catalog'),
                 ('/story/sample/', 'story'), ('/auth/login/', 'auth'),
                 ('/_design/tokens/', '')]
        for path, expected in cases:
            with self.subTest(path=path):
                self.assertEqual(nav_state(self._request_as(path=path))['nav_active'],
                                 expected)

    def test_school_links_reach_every_page_globally(self):
        """Ссылки «Авторлар мектебі» отдаёт глобальный контекст-процессор
        (DEC-22) — их ждёт подвал на любой странице, в том числе у гостя."""
        for url in (reverse('core:home'), reverse('core:library')):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertTrue(response.context['school_links_global'])
                for link in data.school_links():
                    self.assertContains(response, link.url)


class GatedPagesExplainThemselves(TestCase):
    """Личный раздел гостю — не пустая страница, а причина и вход.

    Гейт один компонент на все четыре раздела: четыре копии одного текста
    разошлись бы, и одна из них однажды осталась бы без ссылки на вход.
    """

    def _gated(self):
        contest = data.accepting_contests()[0].slug
        return [
            ('core:my_stories',      {},                'Шығармаларыңды басқару үшін'),
            ('core:new_story',       {},                'Жаңа шығарма жариялау үшін'),
            ('core:library',         {},                'Кітапхананы көру үшін'),
            ('core:notifications',   {},                'Хабарламаларды көру үшін'),
            ('core:profile_me',      {},                'Профильді көру үшін'),
            ('core:profile_me_edit', {},                'Профильді өңдеу үшін'),
            ('core:my_submissions',  {},                'Өтінімдеріңді көру үшін'),
            ('core:contest_submit',  {'slug': contest}, 'Қатысу үшін'),
        ]

    def test_a_guest_is_told_why_and_where_to_go(self):
        """Проверяются оба конца: повод на месте и ссылка возвращает на ту
        же страницу. `new_story` когда-то несла свою формулировку с
        обратным порядком слов и без единого класса типографики."""
        for name, kwargs, reason in self._gated():
            url = reverse(name, kwargs=kwargs)
            with self.subTest(page=name):
                response = self.client.get(url)
                self.assertContains(response, reason)
                self.assertContains(response, f"{reverse('core:login')}?next={url}")

    def test_the_gate_disappears_once_signed_in(self):
        login_as(self.client)
        for name, kwargs, reason in self._gated():
            with self.subTest(page=name):
                self.assertNotContains(
                    self.client.get(reverse(name, kwargs=kwargs)), reason)


class DesignStatesAreOptIn(TestCase):
    """`?state=loading|error` — леса DEC-17: пока данные приходят синхронно,
    показать скелетон и ошибку больше нечем. Проверяется, что опт-ин
    работает и что мусорное значение не ломает страницу."""

    # (маршрут, маркер контента, текст ошибки). Маркер обязан рендериться
    # ТОЛЬКО в content-режиме — иначе тест не заметит, что состояние не
    # подменило содержимое.
    STATEFUL = [
        ('core:home',          'Көп оқылған шығармалар', 'Бір нәрсе сәтсіз болды'),
        ('core:library',       'Күңгірт мырза',          'Кітапхана деректерін жүктеу мүмкін болмады'),
        ('core:notifications', 'пікір қалдырды',         'Хабарламаларды жүктеу мүмкін болмады'),
        ('core:my_stories',    'Таң алдында',            'Шығармалар тізімін жүктеу мүмкін болмады'),
    ]

    def test_loading_and_error_replace_the_content(self):
        login_as(self.client)
        for name, marker, failure in self.STATEFUL:
            url = reverse(name)
            with self.subTest(url=name):
                self.assertContains(self.client.get(url), marker)

                loading = self.client.get(f'{url}?state=loading')
                self.assertContains(loading, 'animate-pulse')
                self.assertNotContains(loading, marker)

                broken = self.client.get(f'{url}?state=error')
                self.assertContains(broken, failure)
                self.assertContains(broken, 'role="alert"')
                self.assertNotContains(broken, marker)

    def test_garbage_falls_back_to_content(self):
        response = self.client.get(f"{reverse('core:home')}?state=garbage")
        self.assertContains(response, 'Көп оқылған шығармалар')
        self.assertNotContains(response, 'animate-pulse')


class MessagesReachTheToastHost(TestCase):
    """Формы отвечают на POST редиректом и `messages` (PRG); своего
    транспорта тосты не заводят — `base.html` превращает сообщение в то же
    window-событие, которое уже слушает `toast_host`."""

    def _rendered_base(self, request_messages=()):
        request = RequestFactory().get('/')
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda r: None).process_request(request)
        for level, text in request_messages:
            messages.add_message(request, level, text)
        return render_to_string('base.html', {}, request=request)

    def test_no_messages_no_script(self):
        self.assertNotIn('DOMContentLoaded', self._rendered_base())

    def test_each_message_becomes_its_own_event_with_a_matching_kind(self):
        """`message.tags` дословно совпадает со словарём `kind` у
        `toast_host` — своего маппинга уровень → kind не требуется."""
        html = self._rendered_base([(messages.SUCCESS, 'Сақталды'),
                                    (messages.WARNING, 'Екінші'),
                                    (messages.ERROR, 'Қате шықты')])
        self.assertEqual(html.count('dispatchEvent'), 3)
        for kind in ('success', 'warning', 'error'):
            self.assertIn(f"kind: '{kind}'", html)
        self.assertIn("text: 'Сақталды'", html)

    def test_the_text_is_js_escaped(self):
        """Иначе одна форма с апострофом в тексте ошибки ломает весь
        `<script>` на странице."""
        html = self._rendered_base([(messages.INFO, 'It\'s "quoted"')])
        self.assertIn('It\\u0027s \\u0022quoted\\u0022', html)
        self.assertNotIn('It\'s "quoted"', html)
