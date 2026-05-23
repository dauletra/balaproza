"""Home: ветвление hero_guest vs hero_returning, контент режимов в шапке/сайдбаре.

Не утверждаем DOM-классы (хрупко), только наличие текстовых маркеров,
которые специфичны для каждого режима.
"""

from django.test import TestCase
from django.urls import reverse


class HomeGuestMode(TestCase):

    def setUp(self):
        self.response = self.client.get(reverse('core:home'))

    def test_returns_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_shows_login_button_in_header(self):
        """Гость в шапке видит «Кіру», а не аватар."""
        self.assertContains(self.response, 'Кіру')

    def test_shows_guest_hero_marker(self):
        """Hero для гостя содержит «Balaproza-ға қош келдіңіз»."""
        self.assertContains(self.response, 'Balaproza-ға')

    def test_does_not_show_continue_reading(self):
        """У гостя нет блока «Жалғастыру оқу»."""
        self.assertNotContains(self.response, 'Жалғастыру')

    def test_does_not_show_logout(self):
        self.assertNotContains(self.response, 'Шығу')

    def test_does_not_show_private_sidebar_items(self):
        """Гостю в sidebar не должно быть «Жазу» (написать)."""
        # «Кітапхана» в footer присутствует как ссылка — проверим уникальный сайдбаровский «Жазу»
        self.assertNotContains(self.response, '>Жазу<')


class HomeAuthedMode(TestCase):

    def setUp(self):
        session = self.client.session
        session['signed_in'] = True
        session['user_name'] = 'Айдана'
        session['user_username'] = 'aidana'
        session.save()
        self.response = self.client.get(reverse('core:home'))

    def test_returns_200(self):
        self.assertEqual(self.response.status_code, 200)

    def test_shows_logout_in_menu(self):
        self.assertContains(self.response, 'Шығу')

    def test_shows_returning_hero_continue_reading(self):
        """Авторизованный возвращающийся видит «Жалғастыру оқу»."""
        self.assertContains(self.response, 'Жалғастыру')

    def test_shows_private_sidebar_items(self):
        # Хотя бы один из приватных пунктов должен присутствовать как ссылка.
        self.assertContains(self.response, 'Хабарламалар')

    def test_no_guest_hero_welcome(self):
        # Текст «Қош келдіңіз» из hero_guest не должен попасть к авторизованному.
        # (Может встретиться в других местах — поэтому проверим точную форму hero.)
        self.assertNotContains(self.response, 'Balaproza-ға қош келдіңіз')


class StoryDetailHasGate(TestCase):
    """FR-STORY-05: гость на странице произведения видит CommentLoginGate."""

    # Реальный slug из stub_data — иначе попадаем в ветку «Шығарма табылмады»,
    # где gate не рендерится.
    STORY_SLUG = 'dalney-berega'

    def test_guest_sees_login_gate_text(self):
        response = self.client.get(reverse('core:story_detail', kwargs={'slug': self.STORY_SLUG}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Пікір қалдыру үшін')

    def test_authed_does_not_see_login_gate(self):
        session = self.client.session
        session['signed_in'] = True
        session.save()
        response = self.client.get(reverse('core:story_detail', kwargs={'slug': self.STORY_SLUG}))
        self.assertNotContains(response, 'Пікір қалдыру үшін')
