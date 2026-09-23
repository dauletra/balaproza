"""Роль модератора: кто это и что он может в админке.

Модератор — сотрудник в группе с правами из
`domain.moderation.MODERATOR_PERMISSIONS`. Проверяется не список сам по
себе (он и есть решение), а три вещи вокруг него: команда приводит группу
ровно к списку, модератор может то, что ему обещано, и не может того, что
у него забрали, — и снятие роли не оставляет хвостов.
"""

from io import StringIO

from django.contrib import admin as django_admin
from django.contrib.auth.models import Permission
from django.core.management import CommandError, call_command
from django.urls import reverse

from core import data
from core.domain.moderation import MODERATOR_GROUP, moderator_codenames
from core.models import Genre, ModerationClaim, Story, User
from core.tests import factories
from core.tests.base import TestCase


def _codenames(group):
    return set(group.permissions.values_list('codename', flat=True))


class TheGroupIsTheListInCode(TestCase):

    def test_the_group_holds_exactly_the_listed_rights(self):
        self.assertEqual(_codenames(data.moderator_group()),
                         moderator_codenames())

    def test_a_right_added_by_hand_is_taken_back(self):
        """Группа, собранная руками или прошлой версией списка, при
        следующем вызове приводится к нынешнему."""
        group = data.moderator_group()
        group.permissions.add(Permission.objects.get(codename='delete_user'))
        self.assertNotIn('delete_user', _codenames(data.moderator_group()))

    def test_the_forbidden_stays_forbidden(self):
        for codename in ('change_user', 'delete_user', 'delete_story',
                         'change_genre', 'delete_chapter', 'add_submission',
                         'change_group'):
            with self.subTest(codename=codename):
                self.assertNotIn(codename, moderator_codenames())


class GrantingAndRevoking(TestCase):

    def setUp(self):
        self.person = factories.user()

    def test_granting_makes_a_staff_member_of_the_group(self):
        data.grant_moderator(self.person)
        self.person.refresh_from_db()
        self.assertTrue(self.person.is_staff)
        self.assertFalse(self.person.is_superuser)
        self.assertTrue(self.person.groups.filter(name=MODERATOR_GROUP).exists())
        self.assertIn(self.person, data.moderators())

    def test_revoking_leaves_no_tail(self):
        data.grant_moderator(self.person)
        ModerationClaim.objects.create(story=Story.objects.first(),
                                       moderator=self.person)
        data.revoke_moderator(self.person)
        self.person.refresh_from_db()
        self.assertFalse(self.person.is_staff)
        self.assertFalse(self.person.groups.exists())
        self.assertFalse(ModerationClaim.objects.filter(
            moderator=self.person).exists())
        self.assertNotIn(self.person, data.moderators())

    def test_revoking_does_not_lock_out_a_superuser(self):
        boss = User.objects.create_superuser('boss', password='x')
        data.grant_moderator(boss)
        data.revoke_moderator(boss)
        boss.refresh_from_db()
        self.assertTrue(boss.is_staff)


class TheCommand(TestCase):

    def _run(self, *args):
        out = StringIO()
        call_command('make_moderator', *args, stdout=out)
        return out.getvalue()

    def test_grant_list_and_revoke(self):
        person = factories.user(username='mod_candidate')
        self.assertIn('granted', self._run('@mod_candidate'))
        self.assertIn('mod_candidate', self._run('--list'))
        self.assertIn('revoked', self._run('mod_candidate', '--revoke'))
        person.refresh_from_db()
        self.assertFalse(person.is_staff)

    def test_an_unknown_or_missing_name_is_refused(self):
        with self.assertRaises(CommandError):
            self._run('nobody_here')
        with self.assertRaises(CommandError):
            self._run()


class WhatAModeratorCanDoInTheAdmin(TestCase):
    """Модератор входит тем же Telegram — здесь `force_login`, как в
    остальных тестах сессии."""

    def setUp(self):
        self.moderator = data.grant_moderator(factories.user())
        self.client.force_login(self.moderator)

    def test_every_page_he_may_see_opens(self):
        """Список и карточка. Карточку открывают отдельно: у того, кто
        только смотрит, форма без полей, и код, ждущий поле, падает
        только там — так упала форма иконки жанра."""
        for model in django_admin.site._registry:
            opts = model._meta
            prefix = f'admin:{opts.app_label}_{opts.model_name}'
            may_view = self.moderator.has_perm(
                f'{opts.app_label}.view_{opts.model_name}')
            with self.subTest(model=opts.model_name):
                self.assertEqual(
                    self.client.get(reverse(f'{prefix}_changelist')).status_code,
                    200 if may_view else 403)
                first = model._default_manager.order_by('pk').first()
                if may_view and first is not None:
                    self.assertEqual(self.client.get(reverse(
                        f'{prefix}_change', args=[first.pk])).status_code, 200)

    def test_the_moderation_section_is_open(self):
        self.assertEqual(
            self.client.get(reverse('core:moderation_queue')).status_code, 200)

    def test_he_decides_a_tag(self):
        tag = factories.tag(status='pending')
        page = self.client.get(reverse('admin:core_tag_changelist')).content.decode()
        self.assertIn('value="reject"', page)
        self.client.post(reverse('admin:core_tag_changelist'), {
            'action': 'accept', '_selected_action': [tag.pk]})
        tag.refresh_from_db()
        self.assertEqual(tag.status, 'accepted')

    def test_he_reads_people_but_does_not_edit_them(self):
        person = factories.user()
        url = reverse('admin:core_user_change', args=[person.pk])
        self.assertNotContains(self.client.get(url), 'name="_save"')
        self.client.post(url, {'username': 'renamed'})
        person.refresh_from_db()
        self.assertNotEqual(person.username, 'renamed')

    def test_he_cannot_delete_a_person_or_a_work(self):
        for name, pk in (('core_user_delete', factories.user().pk),
                         ('core_story_delete', Story.objects.first().pk)):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(
                    reverse(f'admin:{name}', args=[pk])).status_code, 403)

    def test_the_genre_list_is_read_only(self):
        genre = Genre.objects.first()
        self.assertNotContains(self.client.get(
            reverse('admin:core_genre_change', args=[genre.pk])),
            'name="_save"')

    def test_he_removes_a_comment(self):
        comment = factories.comment(Story.objects.first())
        response = self.client.post(
            reverse('admin:core_storycomment_delete', args=[comment.pk]),
            {'post': 'yes'})
        self.assertEqual(response.status_code, 302)

    def test_a_staff_member_without_the_group_sees_an_empty_tool(self):
        """Ради этого группа и заведена: одного `is_staff` хватает на
        `/moderation/`, но не на админку."""
        bare = factories.user(is_staff=True)
        self.client.force_login(bare)
        self.assertEqual(self.client.get(
            reverse('admin:core_tag_changelist')).status_code, 403)
