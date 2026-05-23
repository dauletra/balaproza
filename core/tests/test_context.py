"""Context processors auth_state и nav_state."""

from django.test import RequestFactory, TestCase
from django.contrib.sessions.middleware import SessionMiddleware

from core.context_processors import auth_state, nav_state


def _request_with_session(path='/', session_data=None):
    """Сконструировать GET-запрос с готовой session (без полного middleware-стека)."""
    rf = RequestFactory()
    request = rf.get(path)
    # SessionMiddleware ожидает get_response аргумент — здесь noop достаточно
    middleware = SessionMiddleware(lambda r: None)
    middleware.process_request(request)
    if session_data:
        for k, v in session_data.items():
            request.session[k] = v
    request.session.save()
    return request


class AuthState(TestCase):

    def test_guest_is_not_signed_in(self):
        request = _request_with_session()
        ctx = auth_state(request)
        self.assertFalse(ctx['signed_in'])
        self.assertEqual(ctx['current_user_name'], '')
        self.assertEqual(ctx['unread_notifications'], 0)

    def test_authed_has_user_and_notifications(self):
        request = _request_with_session(session_data={
            'signed_in': True,
            'user_name': 'Айдана',
            'user_username': 'aidana',
        })
        ctx = auth_state(request)
        self.assertTrue(ctx['signed_in'])
        self.assertEqual(ctx['current_user_name'], 'Айдана')
        self.assertEqual(ctx['current_user_username'], 'aidana')
        self.assertEqual(ctx['unread_notifications'], 3)


class NavState(TestCase):

    PATHS = [
        ('/',                       'home'),
        ('/library/',               'library'),
        ('/write/',                 'write'),
        ('/write/sample/',          'write'),
        ('/notifications/',         'notifications'),
        ('/me/',                    'profile'),
        ('/u/rudazov/',             'profile'),
        ('/contests/',              'contests'),
        ('/contests/altyn-qalam/',  'contests'),
        ('/genres/',                'catalog'),
        ('/collections/',           'catalog'),
        ('/search/',                'catalog'),
        ('/story/sample/',          'story'),
        ('/auth/login/',            'auth'),
        ('/_design/tokens/',        ''),  # design-страницы — нет активного пункта меню
    ]

    def test_active_per_path(self):
        rf = RequestFactory()
        for path, expected in self.PATHS:
            with self.subTest(path=path):
                request = rf.get(path)
                ctx = nav_state(request)
                self.assertEqual(
                    ctx['nav_active'], expected,
                    msg=f'{path} → ожидалось {expected!r}, получили {ctx["nav_active"]!r}',
                )
