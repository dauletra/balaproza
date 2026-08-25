"""Context processors auth_state и nav_state."""

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from core import data
from core.context_processors import auth_state, nav_state
from core.models import User


def _request_as(user=None, path='/'):
    """GET-запрос от имени пользователя (или гостя), без middleware-стека.

    `request.user` выставляется руками — то же самое делает
    `AuthenticationMiddleware`, только лениво и по сессии.
    """
    request = RequestFactory().get(path)
    request.user = user or AnonymousUser()
    return request


class AuthState(TestCase):

    def test_guest_is_not_signed_in(self):
        ctx = auth_state(_request_as())
        self.assertFalse(ctx['signed_in'])
        self.assertEqual(ctx['current_user_name'], '')
        self.assertEqual(ctx['current_user_username'], '')
        self.assertEqual(ctx['unread_notifications'], 0)

    def test_authed_has_user_and_notifications(self):
        ctx = auth_state(_request_as(User.objects.get(username='aidana')))
        self.assertTrue(ctx['signed_in'])
        self.assertEqual(ctx['current_user_username'], 'aidana')
        # Число не вписывается литералом: непрочитанные считает слой данных,
        # и вторая копия этого числа разъезжалась бы с первой при каждой
        # правке демо-корпуса.
        self.assertEqual(ctx['unread_notifications'],
                         data.unread_count_for_user('aidana'))
        self.assertGreater(ctx['unread_notifications'], 0)

    def test_greeting_uses_the_persons_own_name(self):
        """«Қайта қош келдің, Айдана», а не «, aidana».

        Читателю автор известен под лақап аты, но приветствие обращено к
        нему самому — там уместно имя, а не подпись под произведениями.
        Фамилии в обращении тоже нет: с «сен» (docs/16) она звучит вызовом
        к доске.
        """
        aidana = User.objects.get(username='aidana')
        self.assertEqual(aidana.name, 'Айдана Серікқызы')
        self.assertEqual(auth_state(_request_as(aidana))['current_user_name'],
                         'Айдана')

    def test_greeting_falls_back_to_the_public_name(self):
        """У кого настоящего имени нет — зовут так же, как читатель."""
        nameless = User.objects.create_user('nameless', pen_name='Түнгі жазушы')
        self.assertEqual(auth_state(_request_as(nameless))['current_user_name'],
                         'Түнгі жазушы')


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
        ('/catalog/',               'catalog'),
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
