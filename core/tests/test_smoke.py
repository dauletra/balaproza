"""Каркас портала: маршруты, вход, контекст, гейты, демо-состояния.

Пять файлов сошлись сюда потому, что отвечают на один вопрос — **держится
ли обвязка**. Ни один из них не про раздел: сломанный `{% url %}`,
потерянный `{% include %}`, гейт без причины и мост сообщений ломаются
одинаково на любой странице и одинаково незаметно.

Смоук идёт по корпусу намеренно: он отвечает на «страница рендерится», а
страница, на которой ничего нет, рендерится и будучи сломанной.
"""

from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.template.loader import render_to_string
from django.test import RequestFactory, override_settings
from django.urls import reverse

from core import data
from core.context_processors import auth_state, nav_state
from core.models import User
from core.tests.base import TestCase, login_as, login_as_newcomer, user

# (имя маршрута, kwargs, подпись для subTest)
PUBLIC_URLS = [
    ('core:home',              {},                                'home'),
    # `login` не здесь: вошедшему он отвечает 302 (test_auth.LoginPage),
    # гостю — 200, проверено ниже отдельно, test_login_renders_for_a_guest.
    ('core:signup_success',    {},                                'auth/signup-success'),
    ('core:catalog',           {},                                'catalog'),
    # search_results нет в этом списке: это редирект (302), а не
    # страница — свой тест ниже, test_search_results_redirects_to_catalog.
    ('core:genre_index',       {},                                'genre-index'),
    ('core:genre_detail',      {'slug': 'fantastika'},            'genre-detail'),
    ('core:tag_detail',        {'slug': 'mektep'},                'tag-detail'),
    ('core:collections',       {},                                'collections'),
    ('core:collection_detail', {'slug': 'kulki-kerek'},           'collection-detail'),
    ('core:story_detail',      {'slug': 'dalney-berega'},         'story-detail'),
    ('core:my_stories',        {},                                'my-stories'),
    ('core:new_story',         {},                                'new-story'),
    # `manage_story`/`story_settings`/`chapter_new`/`chapter_edit` со
    # слагом 'sample' здесь не стоят: они отвечают по-разному в
    # разных режимах (гостю — auth_gate 200, вошедшему без такой работы —
    # 404), а не одним 200 во всех трёх, — свой обход в
    # `test_write_pages_gate_guests_and_404_the_rest` ниже.
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

    def test_login_renders_for_a_guest(self):
        self.assertEqual(self.client.get(reverse('core:login')).status_code, 200)

    def test_search_results_redirects_to_catalog(self):
        """/search/ — legacy-адрес, не страница. Старая ссылка с
        запросом обязана довести до тех же результатов, а не потеряться."""
        response = self.client.get(reverse('core:search_results') + '?q=шам')
        self.assertRedirects(response, reverse('core:catalog') + '?q=шам')

    def test_as_a_newcomer_with_nothing_of_their_own(self):
        """Вошедший без единой строки контента: смоук отвечает на «страница
        рендерится», а не «у автора есть что показать»."""
        login_as_newcomer(self.client, 'tester')
        self._walk('authed')

    def test_as_an_author_with_a_full_shelf(self):
        """Второй вошедший нужен потому, что половина веток шаблона живёт
        только при непустых данных: полки, полоса внимания, заявки."""
        login_as(self.client)
        self._walk('authored')

    def test_write_pages_gate_guests_and_404_the_rest(self):
        """Кабинет автора отвечает гостю и вошедшему по-разному на
        один и тот же несуществующий слаг — auth_gate (200) против 404,
        а не одним и тем же 200 для всех, как раньше (M4–M8)."""
        urls = [
            reverse('core:manage_story', kwargs={'slug': 'sample'}),
            reverse('core:story_settings', kwargs={'slug': 'sample'}),
            reverse('core:chapter_new', kwargs={'slug': 'sample'}),
            reverse('core:chapter_edit', kwargs={'slug': 'sample', 'chapter': 1}),
        ]
        for url in urls:
            with self.subTest(url=url, mode='guest'):
                self.assertEqual(self.client.get(url).status_code, 200)

        login_as(self.client)
        for url in urls:
            with self.subTest(url=url, mode='authored'):
                self.assertEqual(self.client.get(url).status_code, 404)


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
        """«Қайта қош келдің, aidana»: то же лақап аты, что видит читатель —
        другого имени сайт не хранит."""
        aidana = User.objects.get(username='aidana')
        ctx = auth_state(self._request_as(aidana))
        self.assertTrue(ctx['signed_in'])
        self.assertEqual(ctx['current_user_username'], 'aidana')
        self.assertEqual(ctx['current_user_name'], aidana.public_name)
        # Число не вписывается литералом: вторая копия разъезжалась бы с
        # первой при каждой правке демо-корпуса.
        self.assertEqual(ctx['unread_notifications'],
                         data.unread_count_for_user(user('aidana')))

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
                 ('/story/sample/', 'story'), ('/auth/login/', 'auth')]
        for path, expected in cases:
            with self.subTest(path=path):
                self.assertEqual(nav_state(self._request_as(path=path))['nav_active'],
                                 expected)

    def test_school_links_reach_every_page_globally(self):
        """Ссылки «Авторлар мектебі» отдаёт глобальный контекст-процессор
         — их ждёт подвал на любой странице, в том числе у гостя."""
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


@override_settings(DEBUG=True)
class DesignStatesAreOptIn(TestCase):
    """`?state=loading|error` — леса: пока данные приходят синхронно,
    показать скелетон и ошибку больше нечем. Проверяется, что опт-ин
    работает и что мусорное значение не ломает страницу.

    Весь класс под `DEBUG=True`: параметр закрыт им (A5). Живой сайт
    отвечает на него содержимым, и это проверяет отдельный класс ниже —
    посетитель не должен уметь показать себе «жүктеу мүмкін болмады» там,
    где всё работает.
    """

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


class DesignStatesDoNotExistOnTheLiveSite(TestCase):
    """Леса состояний — только при `DEBUG`.

    Без этой проверки любой посетитель открывал бы главную с
    `?state=error` и видел «Бір нәрсе сәтсіз болды» на работающем сайте:
    жалоба в поддержку на поломку, которой нет, и скриншот, который потом
    ходит по чатам.
    """

    def test_the_live_site_answers_with_its_content(self):
        for state in ('loading', 'error'):
            with self.subTest(state=state):
                response = self.client.get(f"{reverse('core:home')}?state={state}")

                self.assertContains(response, 'Көп оқылған шығармалар')
                self.assertNotContains(response, 'animate-pulse')
                self.assertNotContains(response, 'Бір нәрсе сәтсіз болды')


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

    def test_the_host_stacks_on_the_left_not_over_the_action_bar(self):
        """Справа тост вставал ровно поверх
        «Сақтау»/«Болдырмау» — панели действий по проекту прижаты вправо
        (`justify-end`: new_story, story_settings, contest_submit)."""
        html = self._rendered_base()
        self.assertIn('sm:left-6', html)
        self.assertNotIn('sm:right-6', html)

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
