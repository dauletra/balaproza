"""Вход и онбординг через Telegram (FR-AUTH-*, NFR-25).

`_telegram_payload` подписывает поля независимой реализацией того же
алгоритма — иначе тест на валидную подпись подтверждал бы сам себя, а не
`verify_telegram_auth`.
"""

import hashlib
import hmac
import time
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import data
from core.domain.telegram import verify_telegram_auth
from core.models import User
from core.tests.base import TestCase, login_as, login_as_newcomer


def _sign(fields: dict, token: str) -> dict:
    check_string = '\n'.join(f'{k}={v}' for k, v in sorted(fields.items()))
    secret = hashlib.sha256(token.encode()).digest()
    signed = dict(fields)
    signed['hash'] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return signed


def _telegram_payload(telegram_id=555000111, **overrides) -> dict:
    fields = {
        'id': str(telegram_id),
        'first_name': 'Аружан',
        'auth_date': str(int(time.time())),
    }
    fields.update(overrides)
    return _sign(fields, settings.TELEGRAM_BOT_TOKEN)


class VerifyingTheSignature(SimpleTestCase):
    """Чистая функция — без БД и Django-контекста."""

    def test_valid_signature_passes(self):
        payload = _telegram_payload()
        self.assertIsNone(verify_telegram_auth(payload, settings.TELEGRAM_BOT_TOKEN))

    def test_tampered_field_is_rejected(self):
        payload = _telegram_payload()
        payload['first_name'] = 'Басқа'
        self.assertEqual(
            verify_telegram_auth(payload, settings.TELEGRAM_BOT_TOKEN), 'bad_signature')

    def test_wrong_token_is_rejected(self):
        payload = _telegram_payload()
        self.assertEqual(
            verify_telegram_auth(payload, 'not-the-real-bot-token'), 'bad_signature')

    def test_missing_hash_is_rejected(self):
        payload = _telegram_payload()
        del payload['hash']
        self.assertEqual(
            verify_telegram_auth(payload, settings.TELEGRAM_BOT_TOKEN), 'missing_hash')

    def test_stale_auth_date_is_rejected(self):
        payload = _telegram_payload(auth_date=str(int(time.time()) - 100_000))
        self.assertEqual(
            verify_telegram_auth(payload, settings.TELEGRAM_BOT_TOKEN), 'stale')


class TelegramCallback(TestCase):

    def test_first_login_creates_account_and_leads_to_onboarding(self):
        payload = _telegram_payload(telegram_id=700111222, first_name='Данияр')
        response = self.client.get(reverse('core:telegram_callback'), payload)

        created = User.objects.get(telegram_id=700111222)
        self.assertRedirects(
            response, f"{reverse('core:onboarding')}?next=%2F")
        self.assertEqual(get_user(self.client).pk, created.pk)
        self.assertIsNone(created.terms_accepted_at)
        self.assertTrue(created.username.startswith('id'))

    def test_returning_user_logs_in_without_a_duplicate_and_honours_next(self):
        existing = User.objects.create_user('existing_tg', telegram_id=800111222)
        before = User.objects.count()
        target = reverse('core:library')

        payload = _telegram_payload(telegram_id=800111222)
        response = self.client.get(
            reverse('core:telegram_callback'), {**payload, 'next': target})

        self.assertRedirects(response, target)
        self.assertEqual(User.objects.count(), before)
        self.assertEqual(get_user(self.client).pk, existing.pk)

    def test_login_rotates_the_session(self):
        """Session fixation: ключ, выданный гостю, не должен оставаться при
        нём после входа — подсунутый заранее ключ стал бы ключом вошедшего."""
        session = self.client.session
        session['seen_before'] = True
        session.save()
        before = session.session_key

        payload = _telegram_payload(telegram_id=600111222)
        self.client.get(reverse('core:telegram_callback'), payload)

        self.assertNotEqual(self.client.session.session_key, before)

    def test_next_never_leaves_the_site(self):
        User.objects.create_user('safe_tg', telegram_id=650111222)
        for evil in ('http://evil.example.com/', 'https://evil.example.com/login',
                     '//evil.example.com/'):
            with self.subTest(evil=evil):
                payload = _telegram_payload(telegram_id=650111222)
                response = self.client.get(
                    reverse('core:telegram_callback'), {**payload, 'next': evil})
                self.assertEqual(response.url, reverse('core:home'))

    def test_invalid_signature_does_not_log_in(self):
        payload = _telegram_payload(telegram_id=610111222)
        payload['hash'] = '0' * 64
        with self.assertLogs('core.views.auth', level='WARNING'):
            response = self.client.get(reverse('core:telegram_callback'), payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Кіру сәтсіз аяқталды')
        self.assertFalse(get_user(self.client).is_authenticated)
        self.assertFalse(User.objects.filter(telegram_id=610111222).exists())


class UsernameGeneration(TestCase):

    def test_collision_is_retried_until_a_free_id_is_found(self):
        User.objects.create_user('id111111')
        with mock.patch('core.queries.auth.get_random_string',
                        side_effect=['111111', '222222']):
            user, created = data.get_or_create_telegram_user(999111222)
        self.assertTrue(created)
        self.assertEqual(user.username, 'id222222')


class LoggingOut(TestCase):

    def test_logout_is_post_only_and_idempotent(self):
        login_as(self.client)
        self.assertEqual(self.client.get(reverse('core:logout')).status_code, 405)
        self.assertRedirects(self.client.post(reverse('core:logout')),
                             reverse('core:home'))
        self.assertFalse(get_user(self.client).is_authenticated)
        self.assertEqual(self.client.post(reverse('core:logout')).status_code, 302)


class LoginPage(TestCase):

    def test_shows_placeholder_when_bot_is_not_configured(self):
        with override_settings(TELEGRAM_BOT_USERNAME=''):
            response = self.client.get(reverse('core:login'))
        self.assertContains(response, 'TELEGRAM_BOT_USERNAME')

    def test_shows_the_widget_when_bot_is_configured(self):
        with override_settings(TELEGRAM_BOT_USERNAME='balaproza_bot'):
            response = self.client.get(reverse('core:login'))
        self.assertContains(response, 'data-telegram-login="balaproza_bot"')


class Onboarding(TestCase):

    def test_guest_is_sent_to_login(self):
        response = self.client.get(reverse('core:onboarding'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('core:login'), response.url)

    def test_already_onboarded_author_is_sent_to_profile(self):
        author = login_as_newcomer(self.client, 'onboarded_already')
        author.terms_accepted_at = timezone.now()
        author.save(update_fields=['terms_accepted_at'])

        response = self.client.get(reverse('core:onboarding'))
        self.assertRedirects(response, reverse('core:profile_me'))

    def test_rejected_form_returns_what_was_typed_and_saves_nothing(self):
        login_as_newcomer(self.client, 'typed_but_invalid')
        response = self.client.post(reverse('core:onboarding'), {
            'pen_name': '',
            'bio': 'Кітап оқығанды жақсы көремін',
            'birth_date': '2010-05-01',
            'gender': 'girl',
            'agree_rules': 'on',
            'agree_privacy': 'on',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Кітап оқығанды жақсы көремін')

        u = User.objects.get(username='typed_but_invalid')
        self.assertEqual(u.bio, '')
        self.assertIsNone(u.terms_accepted_at)

    def test_missing_agreement_is_rejected(self):
        login_as_newcomer(self.client, 'no_agreement')
        response = self.client.post(reverse('core:onboarding'), {
            'pen_name': 'Мадина', 'agree_rules': '', 'agree_privacy': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'келісу қажет')
        self.assertIsNone(User.objects.get(username='no_agreement').terms_accepted_at)

    def test_valid_submission_completes_registration(self):
        login_as_newcomer(self.client, 'finishing_up')
        response = self.client.post(reverse('core:onboarding'), {
            'pen_name': 'Дана Серікқызы', 'bio': '', 'birth_date': '', 'gender': '',
            'agree_rules': 'on', 'agree_privacy': 'on',
        })
        self.assertRedirects(response, reverse('core:signup_success'))

        u = User.objects.get(username='finishing_up')
        self.assertEqual(u.pen_name, 'Дана Серікқызы')
        self.assertIsNotNone(u.terms_accepted_at)
