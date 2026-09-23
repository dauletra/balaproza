"""Жалоба на опубликованный контент.

Не про очередь ревизий (`test_moderation.py`) — цель здесь уже видна
читателю: история или комментарий. Проверяется создание жалобы (и что
сервер не верит форме про «не на своё»), видимость очереди только
персоналу и оба исхода решения — «бұзушылық жоқ» и снятие контента.
"""

from django.test import Client
from django.urls import reverse

from core import data
from core.models import Chapter, Notification, Report, StoryComment
from core.tests import factories as make
from core.tests.base import TestCase, login_as_newcomer


def _moderator(client, username='mod_reports'):
    user = make.user(username=username)
    user.is_staff = True
    user.save(update_fields=['is_staff'])
    client.force_login(user)
    return user


class CreatingAReport(TestCase):
    def setUp(self):
        super().setUp()
        self.author = make.user(username='rep_author')
        self.story = make.story(author=self.author, chapters=1)
        self.reporter = login_as_newcomer(self.client, 'rep_reporter')

    def test_reports_the_story(self):
        response = self.client.post(
            reverse('core:story_report', kwargs={'slug': self.story.slug}),
            {'reason': 'spam', 'comment': 'Жарнама секілді.'})
        self.assertRedirects(response, reverse(
            'core:story_detail', kwargs={'slug': self.story.slug}))
        report = Report.objects.get(story=self.story)
        self.assertEqual(report.reporter_id, self.reporter.pk)
        self.assertEqual(report.reason, 'spam')
        self.assertEqual(report.note, 'Жарнама секілді.')
        self.assertTrue(report.is_open)

    def test_reports_a_comment(self):
        comment = make.comment(self.story, author=self.author)
        response = self.client.post(
            reverse('core:comment_report',
                   kwargs={'slug': self.story.slug, 'comment_id': comment.pk}),
            {'reason': 'offensive'})
        self.assertEqual(response.status_code, 302)
        report = Report.objects.get(comment=comment)
        self.assertEqual(report.reason, 'offensive')
        self.assertIsNone(report.story_id)

    def test_reporting_your_own_story_creates_nothing(self):
        own = make.story(author=self.reporter, chapters=1)
        self.client.post(
            reverse('core:story_report', kwargs={'slug': own.slug}),
            {'reason': 'spam'})
        self.assertFalse(Report.objects.filter(story=own).exists())

    def test_reporting_your_own_comment_creates_nothing(self):
        own_comment = make.comment(self.story, author=self.reporter)
        self.client.post(
            reverse('core:comment_report',
                   kwargs={'slug': self.story.slug, 'comment_id': own_comment.pk}),
            {'reason': 'spam'})
        self.assertFalse(Report.objects.filter(comment=own_comment).exists())

    def test_an_unknown_reason_creates_nothing(self):
        self.client.post(
            reverse('core:story_report', kwargs={'slug': self.story.slug}),
            {'reason': 'because-i-said-so'})
        self.assertFalse(Report.objects.filter(story=self.story).exists())

    def test_a_guest_is_sent_to_login_and_files_nothing(self):
        guest = Client()
        response = guest.post(
            reverse('core:story_report', kwargs={'slug': self.story.slug}),
            {'reason': 'spam'})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('core:login'), response.url)
        self.assertFalse(Report.objects.filter(story=self.story).exists())


class TheReportsQueue(TestCase):
    def setUp(self):
        super().setUp()
        self.author = make.user(username='rq_author')
        self.story = make.story(author=self.author, chapters=1)
        self.reporter = make.user(username='rq_reporter')
        self.report = data.create_report(
            self.reporter, story=self.story, reason='spam')

    def test_a_guest_and_a_plain_reader_get_404(self):
        reader = Client()
        login_as_newcomer(reader, 'rq_plain_reader')
        for client in (Client(), reader):
            self.assertEqual(
                client.get(reverse('core:moderation_reports')).status_code, 404)

    def test_a_moderator_sees_the_open_report(self):
        _moderator(self.client)
        response = self.client.get(reverse('core:moderation_reports'))
        self.assertContains(response, self.story.title)

    def test_a_resolved_report_drops_out_of_the_queue(self):
        data.resolve_report(self.report, _moderator(self.client), action='dismiss')
        response = self.client.get(reverse('core:moderation_reports'))
        self.assertNotContains(response, self.story.title)


class ResolvingAStoryReport(TestCase):
    def setUp(self):
        super().setUp()
        self.author = make.user(username='rr_author')
        self.story = make.story(author=self.author, chapters=2)
        self.reporter = make.user(username='rr_reporter')
        self.report = data.create_report(
            self.reporter, story=self.story, reason='offensive')
        self.mod = _moderator(self.client)

    def _resolve(self, **post):
        return self.client.post(
            reverse('core:moderation_report_resolve',
                   kwargs={'pk': self.report.pk}), post)

    def test_dismiss_closes_the_report_without_touching_the_story(self):
        before = list(Chapter.objects.filter(story=self.story)
                      .values_list('published_revision_id', flat=True))
        self._resolve(action='dismiss')
        self.report.refresh_from_db()
        self.assertFalse(self.report.is_open)
        self.assertEqual(self.report.outcome, 'dismissed')
        self.assertEqual(self.report.resolved_by_id, self.mod.pk)
        after = list(Chapter.objects.filter(story=self.story)
                     .values_list('published_revision_id', flat=True))
        self.assertEqual(before, after)

    def test_uphold_takes_the_story_down_and_notifies_the_author(self):
        self._resolve(action='uphold', reason='Ережені бұзады.')
        self.report.refresh_from_db()
        self.assertEqual(self.report.outcome, 'upheld')
        self.assertFalse(Chapter.objects.filter(
            story=self.story, published_revision__isnull=False).exists())
        self.story.refresh_from_db()
        self.assertEqual(self.story.status, 'NeedsWork')
        note = Notification.objects.filter(
            user=self.author, kind='moderation', story=self.story).latest('pk')
        self.assertEqual(note.outcome, 'rejected')
        self.assertEqual(note.text, 'Ережені бұзады.')
        # Акт в журнале — с тем, кто снял: из него, а не из ленты, статус
        # и замечание автору читаются и через месяц.
        decision = self.story.moderation_decisions.get()
        self.assertEqual((decision.outcome, decision.reason, decision.moderator),
                         ('rejected', 'Ережені бұзады.', self.mod))
        self.assertGreater(decision.chapters, 0)

    def test_uphold_without_a_reason_leaves_the_report_open(self):
        before = list(Chapter.objects.filter(story=self.story)
                      .values_list('published_revision_id', flat=True))
        response = self._resolve(action='uphold', reason='')
        self.assertRedirects(response, reverse('core:moderation_reports'))
        self.report.refresh_from_db()
        self.assertTrue(self.report.is_open)
        after = list(Chapter.objects.filter(story=self.story)
                     .values_list('published_revision_id', flat=True))
        self.assertEqual(before, after)


class ResolvingACommentReport(TestCase):
    def setUp(self):
        super().setUp()
        self.author = make.user(username='rc_author')
        self.story = make.story(author=self.author, chapters=1)
        self.comment = make.comment(self.story, author=self.author)
        self.reporter = make.user(username='rc_reporter')
        self.report = data.create_report(
            self.reporter, comment=self.comment, reason='offensive')
        self.mod = _moderator(self.client)

    def test_uphold_deletes_the_comment(self):
        self.client.post(
            reverse('core:moderation_report_resolve',
                   kwargs={'pk': self.report.pk}),
            {'action': 'uphold', 'reason': 'Жараспайды.'})
        self.assertFalse(StoryComment.objects.filter(pk=self.comment.pk).exists())
        self.report.refresh_from_db()
        self.assertEqual(self.report.outcome, 'upheld')

    def test_dismiss_keeps_the_comment(self):
        self.client.post(
            reverse('core:moderation_report_resolve',
                   kwargs={'pk': self.report.pk}),
            {'action': 'dismiss'})
        self.assertTrue(StoryComment.objects.filter(pk=self.comment.pk).exists())
