"""Жизненный цикл аккаунта: вход, онбординг, удаление.

`_telegram_payload` подписывает поля независимой реализацией того же
алгоритма — иначе тест на валидную подпись подтверждал бы сам себя, а не
`verify_telegram_auth`.

Удаление стоит здесь, а не в профиле: это конец той же дороги, что
начинается входом, и держит его тот же вопрос — что остаётся в базе
после человека.
"""

import hashlib
import hmac
import time
from unittest import mock
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import data
from core.domain.telegram import MAX_AUTH_AGE, verify_telegram_auth
from core.middleware import _MODERATION_URL_NAMES
from core.models import (
    ChapterReactionVote,
    LibraryEntry,
    Story,
    StoryComment,
    User,
)
from core.tests import factories
from core.urls import urlpatterns as core_urlpatterns
from core.tests.base import TestCase, login_as, login_as_newcomer, user


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

    def test_the_window_is_minutes_and_not_a_day(self):
        """Подписанный адрес равен входу в аккаунт: кто его прочёл, тот
        вошёл. Суток тут не требовалось ничем — виджет редиректит браузер
        сразу, — а ссылка все эти сутки лежала в истории браузера и в
        логах прокси, где запросы пишутся вместе с параметрами."""
        self.assertEqual(MAX_AUTH_AGE, 5 * 60)

        just_in_time = _telegram_payload(
            auth_date=str(int(time.time()) - MAX_AUTH_AGE + 30))
        self.assertIsNone(
            verify_telegram_auth(just_in_time, settings.TELEGRAM_BOT_TOKEN))

        an_hour_old = _telegram_payload(auth_date=str(int(time.time()) - 3600))
        self.assertEqual(
            verify_telegram_auth(an_hour_old, settings.TELEGRAM_BOT_TOKEN),
            'stale')


class TelegramCallback(TestCase):

    def test_first_login_does_not_create_an_account_yet(self):
        """Подпись верна, но анкета не заполнена — аккаунт рано заводить:
        отказ от регистрации не должен оставлять недозаполненную запись
        (см. Onboarding.test_valid_submission_from_a_fresh_telegram_visitor
        и Decline)."""
        payload = _telegram_payload(telegram_id=700111222, first_name='Данияр')
        response = self.client.get(reverse('core:telegram_callback'), payload)

        self.assertRedirects(
            response, f"{reverse('core:onboarding')}?next=%2F")
        self.assertFalse(User.objects.filter(telegram_id=700111222).exists())
        self.assertFalse(get_user(self.client).is_authenticated)
        self.assertEqual(self.client.session['pending_telegram_id'], 700111222)

    def test_returning_user_logs_in_without_a_duplicate_and_honours_next(self):
        existing = User.objects.create_user('existing_tg', telegram_id=800111222,
                                            terms_accepted_at=timezone.now())
        before = User.objects.count()
        target = reverse('core:library')

        payload = _telegram_payload(telegram_id=800111222)
        response = self.client.get(
            reverse('core:telegram_callback'), {**payload, 'next': target})

        self.assertRedirects(response, target)
        self.assertEqual(User.objects.count(), before)
        self.assertEqual(get_user(self.client).pk, existing.pk)

    def test_returning_user_login_rotates_the_session(self):
        """Session fixation: ключ, выданный гостю, не должен оставаться при
        нём после входа — подсунутый заранее ключ стал бы ключом вошедшего."""
        User.objects.create_user('rotates_tg', telegram_id=600111222,
                                 terms_accepted_at=timezone.now())
        session = self.client.session
        session['seen_before'] = True
        session.save()
        before = session.session_key

        payload = _telegram_payload(telegram_id=600111222)
        self.client.get(reverse('core:telegram_callback'), payload)

        self.assertNotEqual(self.client.session.session_key, before)

    def test_first_login_does_not_rotate_the_session_yet(self):
        """Пока аккаунта нет, ротировать нечего — вход (и ротация) случится
        только на сабмите анкеты, см.
        Onboarding.test_valid_submission_from_a_fresh_telegram_visitor_rotates_the_session."""
        session = self.client.session
        session['seen_before'] = True
        session.save()
        before = session.session_key

        payload = _telegram_payload(telegram_id=690111222)
        self.client.get(reverse('core:telegram_callback'), payload)

        self.assertEqual(self.client.session.session_key, before)

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
        with override_settings(TELEGRAM_BOT_USERNAME='qazaqnovel_bot'):
            response = self.client.get(reverse('core:login'))
        self.assertContains(response, 'data-telegram-login="qazaqnovel_bot"')

    def test_already_signed_in_is_sent_to_profile(self):
        """Вошедшему тут делать нечего — виджет и так предложил бы войти
        ещё раз тем же Telegram-аккаунтом."""
        login_as(self.client)
        response = self.client.get(reverse('core:login'))
        self.assertRedirects(response, reverse('core:profile_me'))

    def test_already_signed_in_honours_next(self):
        login_as(self.client)
        response = self.client.get(reverse('core:login') + '?next=/catalog/')
        self.assertRedirects(response, '/catalog/')


class Onboarding(TestCase):

    def test_guest_is_sent_to_login(self):
        response = self.client.get(reverse('core:onboarding'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('core:login'), response.url)

    def test_already_onboarded_author_is_sent_to_profile(self):
        login_as_newcomer(self.client, 'onboarded_already')

        response = self.client.get(reverse('core:onboarding'))
        self.assertRedirects(response, reverse('core:profile_me'))

    def test_rejected_form_returns_what_was_typed_and_saves_nothing(self):
        login_as_newcomer(self.client, 'typed_but_invalid', onboarded=False)
        response = self.client.post(reverse('core:onboarding'), {
            'pen_name': '',
            'bio': 'Кітап оқығанды жақсы көремін',
            'agree_rules': 'on',
            'agree_privacy': 'on',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Кітап оқығанды жақсы көремін')

        u = User.objects.get(username='typed_but_invalid')
        self.assertEqual(u.bio, '')
        self.assertIsNone(u.terms_accepted_at)

    def test_missing_agreement_is_rejected(self):
        login_as_newcomer(self.client, 'no_agreement', onboarded=False)
        response = self.client.post(reverse('core:onboarding'), {
            'pen_name': 'Мадина', 'agree_rules': '', 'agree_privacy': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'келісу қажет')
        self.assertIsNone(User.objects.get(username='no_agreement').terms_accepted_at)

    def test_valid_submission_completes_registration(self):
        login_as_newcomer(self.client, 'finishing_up', onboarded=False)
        response = self.client.post(reverse('core:onboarding'), {
            'pen_name': 'Дана Серікқызы', 'bio': '',
            'agree_rules': 'on', 'agree_privacy': 'on',
        })
        self.assertRedirects(response, reverse('core:signup_success'))

        u = User.objects.get(username='finishing_up')
        self.assertEqual(u.pen_name, 'Дана Серікқызы')
        self.assertIsNotNone(u.terms_accepted_at)

    def test_the_form_asks_for_two_things_and_no_more(self):
        """Анкета из пяти полей стала анкетой из трёх (D4/D5): имя и два
        согласия. Пола и даты рождения не спрашивают вовсе — ни то, ни
        другое нигде не использовалось, а площадка детская.

        Проверяется с обеих сторон: без имени не пройти, а без снятых
        полей — пройти.
        """
        login_as_newcomer(self.client, 'short_form', onboarded=False)

        refused = self.client.post(reverse('core:onboarding'), {
            'pen_name': '', 'bio': '',
            'agree_rules': 'on', 'agree_privacy': 'on',
        })
        self.assertEqual(refused.status_code, 200)
        self.assertContains(refused, 'Авторлық атыңды жаз.')
        self.assertIsNone(
            User.objects.get(username='short_form').terms_accepted_at)

        self.client.post(reverse('core:onboarding'), {
            'pen_name': 'Айгүл', 'bio': '',
            'agree_rules': 'on', 'agree_privacy': 'on',
        })
        self.assertIsNotNone(
            User.objects.get(username='short_form').terms_accepted_at)

    def test_the_page_does_not_ask_for_age_or_gender(self):
        """Поля нет ни в модели, ни на экране: иначе снятое поле вернулось
        бы разметкой и молча ничего не сохраняло."""
        login_as_newcomer(self.client, 'no_extra_fields', onboarded=False)

        page = self.client.get(reverse('core:onboarding'))

        self.assertNotContains(page, 'name="gender"')
        self.assertNotContains(page, 'name="birth_date"')

    # ── Анонимный визит с pending_telegram_id вместо аккаунта ──────────────
    # Ветка `login_as_newcomer(onboarded=False)` выше проверяет уже
    # существующий (но недозаполненный) аккаунт; здесь — первый визит по
    # Telegram, когда аккаунта ещё нет вообще (см. `telegram_callback`).

    def _seed_pending_session(self, telegram_id=750111222):
        session = self.client.session
        session['pending_telegram_id'] = telegram_id
        session.save()
        return telegram_id

    def test_pending_telegram_visitor_reaches_the_form(self):
        self._seed_pending_session()
        response = self.client.get(reverse('core:onboarding'))
        self.assertEqual(response.status_code, 200)

    def test_invalid_submission_from_a_pending_telegram_visitor_creates_nothing(self):
        telegram_id = self._seed_pending_session()
        response = self.client.post(reverse('core:onboarding'), {
            'pen_name': '', 'bio': '',
            'agree_rules': 'on', 'agree_privacy': 'on',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(telegram_id=telegram_id).exists())
        self.assertFalse(get_user(self.client).is_authenticated)
        self.assertEqual(self.client.session['pending_telegram_id'], telegram_id)

    def test_valid_submission_from_a_pending_telegram_visitor_creates_and_logs_in(self):
        telegram_id = self._seed_pending_session()
        response = self.client.post(reverse('core:onboarding'), {
            'pen_name': 'Жаңа автор', 'bio': '',
            'agree_rules': 'on', 'agree_privacy': 'on',
        })
        self.assertRedirects(response, reverse('core:signup_success'))

        u = User.objects.get(telegram_id=telegram_id)
        self.assertEqual(u.pen_name, 'Жаңа автор')
        self.assertIsNotNone(u.terms_accepted_at)
        self.assertEqual(get_user(self.client).pk, u.pk)
        self.assertNotIn('pending_telegram_id', self.client.session)

    def test_valid_submission_from_a_pending_telegram_visitor_rotates_the_session(self):
        self._seed_pending_session()
        session = self.client.session
        session['seen_before'] = True
        session.save()
        before = session.session_key

        self.client.post(reverse('core:onboarding'), {
            'pen_name': 'Тағы бір автор', 'bio': '',
            'agree_rules': 'on', 'agree_privacy': 'on',
        })
        self.assertNotEqual(self.client.session.session_key, before)


class DecliningOnboarding(TestCase):
    """«Тіркеуден бас тарту» — единственный выход с гейтованной анкеты,
    закрывает обе заготовки из `Onboarding` по-разному."""

    def test_is_post_only(self):
        self.assertEqual(self.client.get(reverse('core:decline_onboarding')).status_code, 405)

    def test_pending_telegram_visitor_leaves_no_account_behind(self):
        session = self.client.session
        session['pending_telegram_id'] = 770111222
        session.save()

        response = self.client.post(reverse('core:decline_onboarding'))

        self.assertRedirects(response, reverse('core:home'))
        self.assertFalse(User.objects.filter(telegram_id=770111222).exists())
        self.assertNotIn('pending_telegram_id', self.client.session)
        self.assertFalse(get_user(self.client).is_authenticated)

    def test_unonboarded_account_is_deleted(self):
        """Редирект именно на `home`, а не на `onboarding`, заодно доказывает,
        что `OnboardingGuardMiddleware` пропускает этот POST — иначе гейт
        завернул бы его назад на анкету раньше, чем отработал бы view."""
        newcomer = login_as_newcomer(self.client, 'declines_after_all', onboarded=False)

        response = self.client.post(reverse('core:decline_onboarding'))

        self.assertRedirects(response, reverse('core:home'))
        self.assertFalse(User.objects.filter(pk=newcomer.pk).exists())
        self.assertFalse(get_user(self.client).is_authenticated)

    # ── Уровень защиты по уровню опасности ────────────────────────────────
    #
    # За одной подписью стоят два разных действия. У анонимного в базе нет
    # ничего, и подтверждать нечего. У вошедшего без анкеты аккаунт уже
    # есть, и та же кнопка сносит его каскадом — а удаление одной главы на
    # этом же портале модалку требует. Несоответствие достижимо на первом
    # же деплое: `createsuperuser` заводит аккаунт с пустым согласием.

    def test_the_account_holder_is_asked_to_confirm(self):
        login_as_newcomer(self.client, 'thinks_twice', onboarded=False)

        page = self.client.get(reverse('core:onboarding')).content.decode()

        self.assertIn('open-delete-confirm', page,
                      'удаление аккаунта отсюда идёт без подтверждения')
        self.assertNotIn(
            f'action="{reverse("core:decline_onboarding")}"', page,
            'голый сабмит на удаление остался на странице')

    def test_the_pending_visitor_is_not_asked_to_confirm_nothing(self):
        """У первого визита по Telegram аккаунта ещё нет: отказ стирает
        ключ сессии. Модалка «всё будет удалено» обещала бы потерю того,
        чего не существует."""
        session = self.client.session
        session['pending_telegram_id'] = 770333444
        session.save()

        page = self.client.get(reverse('core:onboarding')).content.decode()

        self.assertIn(f'action="{reverse("core:decline_onboarding")}"', page)


class OnboardingGuardMiddleware(TestCase):
    """Анкета гейтит весь сайт, а не только редирект после входа:
    без завершённого `terms_accepted_at` любой прямой переход
    подальше от `/auth/onboarding/` возвращает туда же, а не открывает
    страницу."""

    def test_unonboarded_user_is_bounced_back_to_onboarding(self):
        newcomer = login_as_newcomer(self.client, 'wanders_off', onboarded=False)
        for name in ('home', 'catalog', 'my_stories', 'library', 'profile_me'):
            with self.subTest(name=name):
                target = reverse(f'core:{name}')
                response = self.client.get(target)
                self.assertRedirects(
                    response,
                    f"{reverse('core:onboarding')}?{urlencode({'next': target})}")
        self.assertIsNone(newcomer.terms_accepted_at)

    def test_unonboarded_user_still_reaches_consent_and_auth_pages(self):
        login_as_newcomer(self.client, 'reads_before_agreeing', onboarded=False)
        for name in ('legal_terms', 'legal_privacy', 'legal_publishing',
                     'legal_moderation', 'legal_about', 'onboarding'):
            with self.subTest(name=name):
                response = self.client.get(reverse(f'core:{name}'))
                self.assertEqual(response.status_code, 200)

    def test_onboarded_user_is_not_gated(self):
        login_as_newcomer(self.client, 'already_settled_in')
        self.assertEqual(self.client.get(reverse('core:my_stories')).status_code, 200)

    def test_guest_is_not_gated(self):
        self.assertEqual(self.client.get(reverse('core:catalog')).status_code, 200)

    def test_the_admin_is_exempt_at_whatever_path_it_is_mounted(self):
        """Согласия у `createsuperuser` нет по построению, а адрес админки
        настраивается. Литеральный `/admin/` в исключениях совпадал бы с
        маршрутом только при умолчании: сменили адрес — и модератор
        уезжает из админки на анкету портала.

        Проверяется отсутствие редиректа на анкету, а не код ответа:
        маршруты собираются при импорте, и подменённый в тесте адрес
        админки никуда не ведёт — важно, что гейт его пропустил.
        """
        login_as_newcomer(self.client, 'staff_without_consent', onboarded=False)
        with self.settings(ADMIN_PATH='secret-door'):
            response = self.client.get('/secret-door/')
        self.assertNotEqual(response.status_code, 302)


# ───────────────────────────────────────────────────────────────────────
# Удаление аккаунта — немедленное и полное,
# каскад собран в моделях (Story.author → CASCADE и далее)
# ───────────────────────────────────────────────────────────────────────
class DeletingYourAccount(TestCase):

    def test_guest_is_sent_to_login(self):
        response = self.client.post(reverse('core:delete_account'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('core:login'), response.url)

    def test_get_is_not_allowed(self):
        login_as(self.client)
        self.assertEqual(self.client.get(reverse('core:delete_account')).status_code, 405)

    def test_deleting_removes_the_row_and_logs_out(self):
        me = login_as_newcomer(self.client, 'wants_to_leave')
        response = self.client.post(reverse('core:delete_account'))
        self.assertRedirects(response, reverse('core:home'))
        self.assertFalse(get_user(self.client).is_authenticated)
        self.assertFalse(User.objects.filter(pk=me.pk).exists())

    def test_deleting_the_author_takes_the_story_and_others_engagement_with_it(self):
        """Story.author → CASCADE: удаление автора уносит его работу целиком,
        а с ней и чужие данные, оставленные на ней — не просто
        отвязывает их от удалённого аккаунта."""
        author = login_as_newcomer(self.client, 'author_who_leaves')
        story = factories.story(author=author, chapters=1)
        chapter = story.chapter_set.first()
        reader = factories.user(username='stays_behind')
        comment = factories.comment(story, author=reader)
        data.toggle_chapter_reaction(chapter, reader, 'kuldim')
        data.toggle_library_entry(reader, story)

        self.client.post(reverse('core:delete_account'))

        self.assertFalse(Story.objects.filter(pk=story.pk).exists())
        self.assertFalse(StoryComment.objects.filter(pk=comment.pk).exists())
        self.assertFalse(ChapterReactionVote.objects
                         .filter(chapter_id=chapter.pk, user=reader).exists())
        self.assertFalse(LibraryEntry.objects.filter(user=reader, story=story).exists())
        # Сам читатель, оставшийся на портале, не пострадал.
        self.assertTrue(User.objects.filter(pk=reader.pk).exists())

    def test_deleting_your_own_engagement_keeps_others_counters_honest(self):
        """post_delete в core/counters.py подписан на затронутые каскадом
        модели и держит счётчики верными даже при удалении не напрямую."""
        me = login_as_newcomer(self.client, 'engaged_elsewhere')
        other_author = factories.user(username='keeps_the_story')
        story = factories.story(author=other_author, chapters=1)
        chapter = story.chapter_set.first()
        data.add_comment(story, me, text='Тамаша!')
        data.toggle_chapter_reaction(chapter, me, 'kuldim')
        data.toggle_follow(me, other_author)

        story.refresh_from_db()
        other_author.refresh_from_db()
        self.assertEqual(story.comments, 1)
        self.assertEqual(story.likes, 1)
        self.assertEqual(other_author.followers, 1)

        self.client.post(reverse('core:delete_account'))

        story.refresh_from_db()
        other_author.refresh_from_db()
        self.assertEqual(story.comments, 0)
        self.assertEqual(story.likes, 0)
        self.assertEqual(other_author.followers, 0)
        self.assertTrue(Story.objects.filter(pk=story.pk).exists())


class TheModerationSectionIsNotGated(TestCase):
    """Раздел модерации — инструмент сотрудника, как и админка, и анкета
    портала его не гейтит. У заведённого `createsuperuser` согласия нет по
    построению, и ссылка «Модерация» из шапки админки уводила его на
    анкету — где рядом стоит «Тіркеуден бас тарту», удаление вошедшего."""

    def test_a_staff_member_without_consent_reaches_the_section(self):
        staff = login_as_newcomer(self.client, 'staff_no_consent',
                                  onboarded=False)
        staff.is_staff = True
        staff.save(update_fields=['is_staff'])
        self.assertEqual(
            self.client.get(reverse('core:moderation_queue')).status_code, 200)

    def test_every_moderation_route_is_exempt(self):
        """Список имён живёт в middleware; новый маршрут раздела,
        забытый в нём, снова уводил бы сотрудника на анкету."""
        routes = {p.name for p in core_urlpatterns
                  if str(p.pattern).startswith('moderation/')}
        self.assertEqual(routes, set(_MODERATION_URL_NAMES))
