"""Тесты фейковой сессионной авторизации (core.views.login_view/logout_view).

В дизайн-фазе нет настоящего User-модели — только session-флаг.
Важно проверить open-redirect защиту и идемпотентность logout.
"""

from core.tests.base import TestCase
from django.urls import reverse


class LoginFlow(TestCase):

    def test_get_login_renders_form(self):
        response = self.client.get(reverse('core:login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Кіру', status_code=200)

    def test_post_login_sets_session_and_redirects_home(self):
        response = self.client.post(reverse('core:login'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('core:home'))
        self.assertTrue(self.client.session.get('signed_in'))
        # user_name дефолтится в 'Айдана'
        self.assertEqual(self.client.session.get('user_name'), 'Айдана')

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


class LogoutFlow(TestCase):

    def _login(self):
        session = self.client.session
        session['signed_in'] = True
        session['user_name'] = 'Test'
        session.save()

    def test_post_logout_clears_session(self):
        self._login()
        response = self.client.post(reverse('core:logout'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('core:home'))
        self.assertFalse(self.client.session.get('signed_in'))
        self.assertIsNone(self.client.session.get('user_name'))

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

    def test_post_signup_logs_in_and_redirects_to_success(self):
        response = self.client.post(reverse('core:signup'), {'name': 'Айгерім'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('core:signup_success'))
        self.assertTrue(self.client.session.get('signed_in'))
        self.assertEqual(self.client.session.get('user_name'), 'Айгерім')

    def test_post_signup_uses_default_name_when_missing(self):
        response = self.client.post(reverse('core:signup'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session.get('user_name'), 'Айдана')
