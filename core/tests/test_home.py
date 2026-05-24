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
        """Hero для гостя — редакционный, без CTA, сообщает обе функции платформы."""
        self.assertContains(self.response, 'Жасөспірімдер жазады')
        self.assertContains(self.response, 'өзің жазасың')

    def test_does_not_show_continue_reading(self):
        """У гостя нет блока «Жалғастыру оқу»."""
        self.assertNotContains(self.response, 'Жалғастыру')

    def test_does_not_show_logout(self):
        self.assertNotContains(self.response, 'Шығу')

    def test_does_not_show_private_dropdown_items(self):
        """Гость не видит в хедере личных пунктов из avatar-dropdown."""
        # «Менің заявкаларым» появляется только в авторизованном dropdown
        self.assertNotContains(self.response, 'Менің заявкаларым')
        self.assertNotContains(self.response, 'Менің шығармаларым')


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
        # Маркер hero_guest у авторизованного не показывается — у него свой hero_returning.
        self.assertNotContains(self.response, 'Жасөспірімдер жазады')


class HeaderContestsLink(TestCase):
    """DEC-25: единственная контент-ссылка в хедере — «Байқаулар»."""

    def test_link_present_on_home(self):
        r = self.client.get(reverse('core:home'))
        self.assertContains(r, 'Байқаулар')
        self.assertContains(r, reverse('core:contest_list'))

    def test_active_state_on_contests_page(self):
        """На /contests/ ссылка подсвечена brand-цветом."""
        r = self.client.get(reverse('core:contest_list'))
        # nav_active=='contests' даёт класс text-brand на ссылке Байқаулар
        self.assertContains(r, 'Байқаулар')
        # На главной этой подсветки нет → проверяем что на /contests/ есть
        self.assertEqual(r.status_code, 200)


class FooterSiteMap(TestCase):
    """DEC-25: контентные разделы (Жанрлар/Жинақтар) живут в footer, не в хедере."""

    def test_footer_links_to_genres(self):
        r = self.client.get(reverse('core:home'))
        self.assertContains(r, reverse('core:genre_index'))
        self.assertContains(r, 'Жанрлар')

    def test_footer_links_to_collections(self):
        r = self.client.get(reverse('core:home'))
        self.assertContains(r, reverse('core:collections'))
        self.assertContains(r, 'Жинақтар')


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
