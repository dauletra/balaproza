"""AUTH-полировка (login/signup/success) + LINKS (Авторлар мектебі)."""

from core.tests.base import TestCase, login_as, login_as_newcomer
from django.urls import reverse

from core import data


# ════════════════════════════ AUTH · Login ═════════════════════════════════

class LoginPage(TestCase):

    def test_renders(self):
        r = self.client.get(reverse('core:login'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Balaproza-ға кіру')

    def test_telegram_cta_present(self):
        r = self.client.get(reverse('core:login'))
        # Кнопка Telegram-входа (FR-AUTH-01)
        self.assertContains(r, 'Сайтқа кіру')
        self.assertContains(r, '#icon-telegram')

    def test_link_to_signup(self):
        r = self.client.get(reverse('core:login'))
        self.assertContains(r, reverse('core:signup'))
        self.assertContains(r, 'Тіркелу')

    def test_back_to_home_link(self):
        r = self.client.get(reverse('core:login'))
        self.assertContains(r, 'Кірмей-ақ оқуды бастаймын')

    def test_next_param_persisted_in_form(self):
        r = self.client.get(reverse('core:login') + '?next=/library/')
        # Hidden input с next или query в action
        self.assertContains(r, '/library/')


# ════════════════════════════ AUTH · Signup ════════════════════════════════

class SignupPage(TestCase):

    def setUp(self):
        self.response = self.client.get(reverse('core:signup'))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_has_name_input(self):
        self.assertContains(self.response, 'name="name"')
        self.assertContains(self.response, 'Авторлық атың')

    def test_gender_radios(self):
        self.assertContains(self.response, 'name="gender"')
        self.assertContains(self.response, 'value="boy"')
        self.assertContains(self.response, 'value="girl"')

    def test_age_field_asks_without_naming_a_bracket(self):
        """Возраст спрашиваем, аудиторию не объявляем (BR-48, DEC-47).

        Подсказка поля говорила «Байқауға қатысу үшін 14-18 жас керек» —
        платформа представлялась как «для 14-18» каждому, кто дошёл до
        регистрации, ещё до всякого конкурса. Ценза у платформы нет,
        вилку ставит конкурс.
        """
        self.assertContains(self.response, 'name="age"')
        self.assertNotContains(self.response, '14-18')
        # Поле объясняет, зачем спрашивает, — иначе оно выглядит как
        # сбор личных данных без причины.
        self.assertContains(self.response, 'байқаулар')

    def test_bio_textarea(self):
        self.assertContains(self.response, 'name="bio"')

    def test_consent_checkbox_required(self):
        # FR-AUTH-05
        self.assertContains(self.response, 'name="agree"')
        self.assertContains(self.response, 'келісемін')

    def test_signup_post_redirects_to_success(self):
        r = self.client.post(reverse('core:signup'), data={'name': 'Тест'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse('core:signup_success'))


# ════════════════════════════ AUTH · SignupSuccess ═════════════════════════

class SignupSuccessPage(TestCase):

    def setUp(self):
        # человек, только что прошедший регистрацию: в корпусе его нет
        login_as_newcomer(self.client, 'erzhan', name='Ержан Сапаров')
        self.response = self.client.get(reverse('core:signup_success'))

    def test_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_greets_by_name(self):
        self.assertContains(self.response, 'Ержан')
        self.assertContains(self.response, 'Қош келдің')

    def test_has_all_four_onboarding_cards(self):
        # FR-AUTH-03 → онбординг с 4 направлениями
        self.assertContains(self.response, reverse('core:new_story'))
        self.assertContains(self.response, reverse('core:catalog'))
        self.assertContains(self.response, reverse('core:profile_me'))
        self.assertContains(self.response, reverse('core:contest_list'))


# ════════════════════════════ LINKS · SchoolLinks ══════════════════════════

class SchoolLinksData(TestCase):

    def test_school_links_dataclass_fields(self):
        for l in data.school_links():
            with self.subTest(channel=l.channel):
                self.assertTrue(l.channel)
                self.assertTrue(l.title)
                self.assertTrue(l.subtitle)
                self.assertTrue(l.url)

    def test_all_four_channels_present(self):
        channels = {l.channel for l in data.school_links()}
        self.assertEqual(channels, {'youtube', 'instagram', 'tiktok', 'telegram'})


class SchoolLinksInRightRail(TestCase):
    """Главная страница: рейл с блоком SchoolLinks."""

    def test_present_for_guest(self):
        r = self.client.get(reverse('core:home'))
        self.assertContains(r, 'Авторлар мектебі')
        # все 4 названия каналов
        for l in data.school_links():
            with self.subTest(channel=l.channel):
                self.assertContains(r, l.title)

    def test_links_open_in_new_tab(self):
        # FR-LINKS-03
        r = self.client.get(reverse('core:home'))
        self.assertContains(r, 'target="_blank"')
        self.assertContains(r, 'rel="noopener noreferrer"')


class SchoolLinksInFooter(TestCase):
    """Inline-вариант в footer — должен присутствовать на ВСЕХ страницах."""

    def test_footer_has_school_links_on_home(self):
        r = self.client.get(reverse('core:home'))
        # Заголовок секции в футере
        self.assertContains(r, 'Авторлар мектебі')

    def test_footer_has_school_links_on_library(self):
        # Глобальный context processor → school_links_global доступен везде
        login_as(self.client)
        r = self.client.get(reverse('core:library'))
        self.assertContains(r, 'Авторлар мектебі')

    def test_footer_has_school_links_for_guest(self):
        # FR-LINKS-04 — гостю тоже доступны
        r = self.client.get(reverse('core:contest_list'))
        self.assertContains(r, 'Авторлар мектебі')


class SchoolLinksGlobalContextProcessor(TestCase):

    def test_school_links_global_in_context(self):
        r = self.client.get(reverse('core:home'))
        # Проверяем что контекст-процессор отдаёт ссылки
        self.assertEqual(
            [l.channel for l in r.context['school_links_global']],
            [l.channel for l in data.school_links()],
        )


class AuthGateIsOneComponent(TestCase):
    """Гейт гостя — один компонент, а не девять копий.

    Блок «войди, чтобы посмотреть» был скопирован в девяти шаблонах слово в
    слово и расходился только поводом; `new_story` вдобавок несла свою
    формулировку с обратным порядком слов и без единого класса типографики.
    Проверяем оба конца: повод на месте и ссылка возвращает на ту же страницу.
    """

    def _gated(self):
        contest = data.accepting_contests()[0].slug
        return [
            ('core:my_stories',     {},                  'Шығармаларыңды басқару үшін'),
            ('core:new_story',      {},                  'Жаңа шығарма жариялау үшін'),
            ('core:library',        {},                  'Кітапхананы көру үшін'),
            ('core:notifications',  {},                  'Хабарламаларды көру үшін'),
            ('core:profile_me',     {},                  'Профильді көру үшін'),
            ('core:profile_me_edit', {},                 'Профильді өңдеу үшін'),
            ('core:my_submissions', {},                  'Өтінімдеріңді көру үшін'),
            ('core:contest_submit', {'slug': contest},   'Қатысу үшін'),
        ]

    def test_every_gated_page_states_its_reason(self):
        for name, kwargs, reason in self._gated():
            with self.subTest(page=name):
                self.assertContains(self.client.get(reverse(name, kwargs=kwargs)), reason)

    def test_login_link_returns_to_the_same_page(self):
        for name, kwargs, _ in self._gated():
            url = reverse(name, kwargs=kwargs)
            with self.subTest(page=name):
                self.assertContains(
                    self.client.get(url), f"{reverse('core:login')}?next={url}")

    def test_the_gate_disappears_once_signed_in(self):
        login_as(self.client)
        for name, kwargs, reason in self._gated():
            with self.subTest(page=name):
                self.assertNotContains(self.client.get(reverse(name, kwargs=kwargs)), reason)
