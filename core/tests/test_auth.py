"""Вход и выход (`core/views/auth.py`).

Вход настоящий: сессию собирает `django.contrib.auth`, отвечает на «кто
это» база. Провайдера личности пока нет — до Telegram (FR-AUTH-01, NFR-25)
кнопка подписывает в демо-аккаунт, — поэтому проверяется не «какой пароль
подошёл», а то, что вход и выход честно меняют `request.user`, и то, что
переживает смену механизма: защита от open-redirect и идемпотентный выход.
"""

from unittest import mock

from django.contrib.auth import get_user
from django.urls import reverse

from core.tests.base import TestCase
from core.views import DEMO_USERNAME


class LoginFlow(TestCase):

    def test_get_login_renders_form(self):
        response = self.client.get(reverse('core:login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Кіру', status_code=200)

    def test_post_login_authenticates_and_redirects_home(self):
        response = self.client.post(reverse('core:login'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('core:home'))
        user = get_user(self.client)
        self.assertTrue(user.is_authenticated)
        self.assertEqual(user.username, DEMO_USERNAME)

    def test_login_rotates_the_session_key(self):
        """Вход обязан менять ключ сессии (session fixation).

        Session-флаг этого не делал: ключ, выданный гостю, оставался при
        нём и после входа — то есть подсунутый до входа ключ становился
        ключом вошедшего.
        """
        session = self.client.session
        session['seen_before'] = True
        session.save()
        before = session.session_key

        self.client.post(reverse('core:login'))
        self.assertNotEqual(self.client.session.session_key, before)

    def test_post_login_honours_safe_next(self):
        target = reverse('core:library')
        response = self.client.post(f"{reverse('core:login')}?next={target}")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, target)

    def test_post_login_ignores_unsafe_next(self):
        """Open-redirect защита: внешние URL отбрасываются → редирект на /."""
        for evil in [
            'http://evil.example.com/',
            'https://evil.example.com/login',
            '//evil.example.com/',
        ]:
            with self.subTest(evil=evil):
                response = self.client.post(f"{reverse('core:login')}?next={evil}")
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, reverse('core:home'))

    @mock.patch('core.views.auth.DEMO_USERNAME', 'no-such-account')
    def test_login_without_the_demo_account_says_so_and_stays_out(self):
        """Пустая база — не 500 и не «вошёл никем».

        Причина («нет пользователя, выполни seed_demo») уходит в лог: она
        адресована тому, кто разворачивал портал, а не тому, кто нажал
        кнопку.
        """
        with self.assertLogs('core.views', level='WARNING'):
            response = self.client.post(reverse('core:login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Кіру уақытша мүмкін емес')
        self.assertFalse(get_user(self.client).is_authenticated)

    @mock.patch('core.views.auth.DEMO_USERNAME', 'no-such-account')
    def test_failed_login_keeps_the_next_target(self):
        """`next` не теряется при неудаче — иначе повтор уводит не туда."""
        target = reverse('core:library')
        with self.assertLogs('core.views', level='WARNING'):
            response = self.client.post(reverse('core:login'), {'next': target})
        self.assertEqual(response.context['next'], target)


class LogoutFlow(TestCase):

    def test_post_logout_ends_the_session(self):
        self.client.post(reverse('core:login'))
        response = self.client.post(reverse('core:logout'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('core:home'))
        self.assertFalse(get_user(self.client).is_authenticated)

    def test_get_logout_is_405(self):
        """Logout доступен только POST (require_POST)."""
        response = self.client.get(reverse('core:logout'))
        self.assertEqual(response.status_code, 405)

    def test_logout_is_idempotent(self):
        """Logout без активной сессии — тоже редирект на /, без ошибки."""
        response = self.client.post(reverse('core:logout'))
        self.assertEqual(response.status_code, 302)


class SignupFlow(TestCase):

    def test_get_signup_renders_form(self):
        response = self.client.get(reverse('core:signup'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Тіркелу')

    def test_post_signup_signs_in_and_redirects_to_success(self):
        response = self.client.post(reverse('core:signup'), {'name': 'Айгерім'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('core:signup_success'))
        self.assertTrue(get_user(self.client).is_authenticated)

    def test_signup_creates_no_account(self):
        """Форма ничего не записывает: аккаунт заводит Telegram (FR-AUTH-03).

        Пока провайдера нет, придуманный ник некуда деть — и вписывать его
        в чужой аккаунт нельзя. Раньше он попадал в сессию и здоровался с
        человеком, которого в базе не существовало.
        """
        from core.models import User

        before = User.objects.count()
        self.client.post(reverse('core:signup'), {'name': 'Айгерім'})
        self.assertEqual(User.objects.count(), before)
        self.assertEqual(get_user(self.client).username, DEMO_USERNAME)
