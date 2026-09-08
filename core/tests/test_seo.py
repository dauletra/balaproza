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


class RobotsTxt(TestCase):
    def test_disallows_private_sections(self):
        response = self.client.get('/robots.txt')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain')
        self.assertContains(response, 'Disallow: /write/')
        self.assertContains(response, 'Disallow: /moderation/')

    def test_points_to_sitemap(self):
        response = self.client.get('/robots.txt')
        self.assertContains(response, f"Sitemap: http://testserver{reverse('sitemap')}")
