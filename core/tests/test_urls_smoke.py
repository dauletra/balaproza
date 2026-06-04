"""Smoke-тесты: каждый маршрут должен отдавать 200 в обоих режимах.

Это самая дешёвая защита от типовых ошибок дизайн-фазы:
- сломанные {% url %} (после переименования),
- отсутствующие partials/components в {% include %},
- запрещённые переменные шаблона (например, начинающиеся с _),
- зацикленные include (как было с page_header.html),
- падающие custom filters/tags.
"""

from django.test import TestCase, override_settings


# (url_name, args_dict, описание для subTest)
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
    ('core:library',           {},                                'library'),
    ('core:notifications',     {},                                'notifications'),
    ('core:contest_list',      {},                                'contest-list'),
    ('core:contest_detail',    {'slug': 'altyn-qalam'},           'contest-detail'),
    ('core:contest_submit',    {'slug': 'altyn-qalam'},           'contest-submit'),
    ('core:my_submissions',    {},                                'my-submissions'),
]

DEBUG_ONLY_URLS = [
    ('core:design_tokens',     {}, 'design-tokens'),
    ('core:design_components', {}, 'design-components'),
]


class SmokeTestsGuest(TestCase):
    """Все публичные URL рендерятся в гостевом режиме."""

    def test_all_public_routes(self):
        from django.urls import reverse
        for name, kwargs, label in PUBLIC_URLS:
            with self.subTest(label=label, url=name):
                url = reverse(name, kwargs=kwargs)
                response = self.client.get(url)
                self.assertEqual(
                    response.status_code, 200,
                    msg=f'GET {url} (guest) returned {response.status_code}',
                )


class SmokeTestsAuthed(TestCase):
    """Все публичные URL рендерятся в авторизованном режиме."""

    def setUp(self):
        session = self.client.session
        session['signed_in'] = True
        session['user_name'] = 'Test User'
        session['user_username'] = 'tester'
        session.save()

    def test_all_routes_authed(self):
        from django.urls import reverse
        for name, kwargs, label in PUBLIC_URLS:
            with self.subTest(label=label, url=name):
                url = reverse(name, kwargs=kwargs)
                response = self.client.get(url)
                self.assertEqual(
                    response.status_code, 200,
                    msg=f'GET {url} (authed) returned {response.status_code}',
                )


@override_settings(DEBUG=True)
class DesignURLsWhenDebug(TestCase):
    """Дизайн-страницы доступны только при DEBUG=True. Тут — что при True они рендерятся."""

    def test_all_design_routes_render(self):
        from django.urls import reverse
        for name, kwargs, label in DEBUG_ONLY_URLS:
            with self.subTest(label=label, url=name):
                url = reverse(name, kwargs=kwargs)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200,
                    msg=f'GET {url} (DEBUG=True) returned {response.status_code}')


class DebugOnlyEnforcement(TestCase):
    """Дизайн-страницы должны быть 404 при DEBUG=False (тестовый раннер ставит False по умолчанию)."""

    def test_tokens_404_when_not_debug(self):
        response = self.client.get('/_design/tokens/')
        self.assertEqual(response.status_code, 404)

    def test_components_404_when_not_debug(self):
        response = self.client.get('/_design/components/')
        self.assertEqual(response.status_code, 404)
