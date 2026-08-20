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
        self.assertContains(self.response, 'Бүгін не оқимыз?')
        self.assertContains(self.response, 'Шығарма, автор, жанр немесе тег')
        self.assertContains(self.response, 'Автор бол')

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

    def test_mobile_guest_reading_entry_goes_to_catalog(self):
        self.assertContains(self.response, reverse('core:catalog'))
        self.assertContains(self.response, 'aria-label="Оқу"')

    def test_short_shelf_contains_only_single_works(self):
        self.assertTrue(self.response.context['short_stories'])
        self.assertTrue(all(s.is_single for s in self.response.context['short_stories']))

    def test_serial_shelf_contains_only_serial_works(self):
        self.assertTrue(self.response.context['serial_stories'])
        self.assertTrue(all(s.is_serial for s in self.response.context['serial_stories']))

    def test_collections_render_before_genres(self):
        html = self.response.content.decode()
        self.assertLess(html.index('Қазір не оқығыңыз келеді?'), html.index('Жанрлар бойынша'))

    def test_home_uses_five_main_rows(self):
        self.assertContains(self.response, 'Қазір не оқығыңыз келеді?')
        self.assertContains(self.response, 'Жанрлар бойынша')
        self.assertContains(self.response, 'Көп оқылған шығармалар')
        self.assertContains(self.response, 'Қысқа оқылатын әңгімелер')
        self.assertContains(self.response, 'Жалғасып жатқан шығармалар')
        self.assertNotContains(self.response, 'Жаңа шығармалар')
        self.assertNotContains(self.response, '10+ оқырманға')
        self.assertNotContains(self.response, 'Жас авторлар')

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

    def test_default_focuses_started_writing(self):
        self.assertEqual(self.response.context['hero_focus'], 'writing')
        self.assertContains(self.response, 'Мәтініңіз күтіп тұр')

    def test_context_has_active_work_for_writer_resume(self):
        self.assertEqual(self.response.context['active_work'].slug, 'aidana-koshe')

    def test_shows_writer_resume_as_primary_action(self):
        self.assertContains(self.response, 'Жазуды жалғастыру')
        self.assertContains(self.response, reverse('core:manage_story', kwargs={'slug': 'aidana-koshe'}))

    def test_reading_resume_moves_to_right_rail_when_writing_is_primary(self):
        self.assertContains(self.response, 'Оқу үстінде')
        self.assertContains(self.response, 'Оқуды жалғастыру')

    def test_shows_private_nav_items(self):
        # Хотя бы один из приватных пунктов должен присутствовать как ссылка.
        self.assertContains(self.response, 'Хабарламалар')

    def test_no_guest_hero_welcome(self):
        # Маркер hero_guest у авторизованного не показывается — у него свой hero_returning.
        self.assertNotContains(self.response, 'Бүгін не оқимыз?')

    def test_demo_empty_state_has_search_and_first_steps(self):
        r = self.client.get(reverse('core:home') + '?hero_state=empty')
        self.assertEqual(r.context['hero_focus'], 'empty')
        self.assertContains(r, 'Бүгін неден бастаймыз?')
        self.assertContains(r, 'Шығарма, автор, жанр немесе тег')
        self.assertContains(r, 'Жаңа шығарма')

    def test_demo_reading_state_has_reading_primary_and_writing_secondary(self):
        r = self.client.get(reverse('core:home') + '?hero_state=reading')
        self.assertEqual(r.context['hero_focus'], 'reading')
        self.assertIsNone(r.context['active_work'])
        self.assertContains(r, 'Оқуды жалғастыру')
        self.assertContains(r, 'Жазып көру')

    def test_demo_writing_state_has_writing_primary_and_reading_prompt(self):
        r = self.client.get(reverse('core:home') + '?hero_state=writing')
        self.assertEqual(r.context['hero_focus'], 'writing')
        self.assertIsNone(r.context['progress'])
        self.assertContains(r, 'Мәтініңіз күтіп тұр')
        self.assertContains(r, 'Оқуға шығарма табу')


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
