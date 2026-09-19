"""`sitemap.xml` и `robots.txt` (чек-лист README, п. 9)."""

from django.urls import reverse

from core.tests import factories
from core.tests.base import TestCase


class SitemapShowsOnlyPublic(TestCase):
    def test_public_story_is_listed(self):
        story = factories.story()
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, reverse('core:story_detail', kwargs={'slug': story.slug}))

    def test_draft_story_is_not_listed(self):
        draft = factories.story(status='Draft', published=False)
        response = self.client.get('/sitemap.xml')
        self.assertNotContains(
            response, reverse('core:story_detail', kwargs={'slug': draft.slug}))

    def test_static_pages_are_listed(self):
        response = self.client.get('/sitemap.xml')
        self.assertContains(response, reverse('core:home'))
        self.assertContains(response, reverse('core:legal_privacy'))


class SitemapCarriesTheLongTail(TestCase):
    """Людей на литературный портал приводят из поиска не названия
    конкретных работ, которых никто не знает, а жанр, тег, подборка и имя
    автора. Долго ни одной из этих страниц в карте не было."""

    def setUp(self):
        super().setUp()
        self.response = self.client.get('/sitemap.xml')

    def test_genres_tags_collections_and_contests_are_there(self):
        from core import data

        for name, obj in (
            ('core:genre_detail', data.all_genres()[0]),
            ('core:tag_detail', data.sitemap_tags()[0]),
            ('core:collection_detail', data.all_collections()[0]),
            ('core:contest_detail', data.all_contests()[0]),
        ):
            with self.subTest(route=name):
                self.assertContains(
                    self.response, reverse(name, kwargs={'slug': obj.slug}))

    def test_an_author_with_a_public_work_is_there(self):
        author = factories.user()
        factories.story(author=author, chapters=1)

        response = self.client.get('/sitemap.xml')

        self.assertContains(response, reverse(
            'core:profile_other', kwargs={'username': author.username}))

    def test_an_empty_profile_is_not(self):
        """Человек приходит по запросу с именем и попадает туда, где
        читать нечего, — это работает против платформы."""
        lonely = factories.user()

        response = self.client.get('/sitemap.xml')

        self.assertNotContains(response, reverse(
            'core:profile_other', kwargs={'username': lonely.username}))

    def test_a_pending_tag_is_not(self):
        pending = factories.tag(status='pending')

        response = self.client.get('/sitemap.xml')

        self.assertNotContains(
            response, reverse('core:tag_detail', kwargs={'slug': pending.slug}))


class RobotsTxt(TestCase):
    def test_disallows_private_sections(self):
        response = self.client.get('/robots.txt')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain')
        self.assertContains(response, 'Disallow: /write/')
        self.assertContains(response, 'Disallow: /moderation/')
        # Админка тоже, и по фактическому адресу: он настраиваемый.
        from django.conf import settings
        self.assertContains(response, f'Disallow: /{settings.ADMIN_PATH}/')

    def test_points_to_sitemap(self):
        response = self.client.get('/robots.txt')
        self.assertContains(response, f"Sitemap: http://testserver{reverse('sitemap')}")
