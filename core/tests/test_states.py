"""Ф13 · Loading / Error / Empty states (DEC-17)."""

from django.test import TestCase, override_settings
from django.urls import reverse


def _login_as_aidana(client):
    s = client.session
    s['signed_in'] = True
    s['user_name'] = 'Айдана'
    s['user_username'] = 'aidana'
    s.save()


# ════════════════════════════ ?state= opt-in ═══════════════════════════════

class HomeStates(TestCase):

    # Маркер, который рендерится ТОЛЬКО в content-режиме главной
    # (внутри if/else, отсутствует в hero / right_rail / new_authors / footer).
    CONTENT_MARKER = 'Ең көп оқылған'

    def test_default_state_is_content(self):
        r = self.client.get(reverse('core:home'))
        self.assertContains(r, self.CONTENT_MARKER)

    def test_loading_renders_skeletons_not_content(self):
        r = self.client.get(reverse('core:home') + '?state=loading')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'animate-pulse')
        self.assertNotContains(r, self.CONTENT_MARKER)

    def test_error_renders_error_state(self):
        r = self.client.get(reverse('core:home') + '?state=error')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Бір нәрсе сәтсіз болды')
        self.assertContains(r, 'role="alert"')
        self.assertNotContains(r, self.CONTENT_MARKER)

    def test_unknown_state_falls_back_to_content(self):
        r = self.client.get(reverse('core:home') + '?state=garbage')
        self.assertContains(r, self.CONTENT_MARKER)


class LibraryStates(TestCase):

    def setUp(self):
        _login_as_aidana(self.client)

    def test_loading_shows_skeletons(self):
        r = self.client.get(reverse('core:library') + '?state=loading')
        self.assertContains(r, 'animate-pulse')
        # Реальные книги не рендерим
        self.assertNotContains(r, 'Күңгірт мырза')

    def test_error_shows_error_block(self):
        r = self.client.get(reverse('core:library') + '?state=error')
        self.assertContains(r, 'Кітапхана деректерін жүктеу мүмкін болмады')
        self.assertNotContains(r, 'Күңгірт мырза')

    def test_content_default(self):
        r = self.client.get(reverse('core:library'))
        # Saved — содержит «Күңгірт мырза»
        self.assertContains(r, 'Күңгірт мырза')


class NotificationsStates(TestCase):

    def setUp(self):
        _login_as_aidana(self.client)

    def test_loading_skeleton(self):
        r = self.client.get(reverse('core:notifications') + '?state=loading')
        self.assertContains(r, 'animate-pulse')
        # Реальные нотификации не показаны
        self.assertNotContains(r, 'пікір қалдырды')

    def test_error_state(self):
        r = self.client.get(reverse('core:notifications') + '?state=error')
        self.assertContains(r, 'Хабарламаларды жүктеу мүмкін болмады')
        self.assertNotContains(r, 'пікір қалдырды')


class MyStoriesStates(TestCase):

    def setUp(self):
        _login_as_aidana(self.client)

    def test_loading(self):
        r = self.client.get(reverse('core:my_stories') + '?state=loading')
        self.assertContains(r, 'animate-pulse')
        self.assertNotContains(r, 'Таң алдында')

    def test_error(self):
        r = self.client.get(reverse('core:my_stories') + '?state=error')
        self.assertContains(r, 'Шығармалар тізімін жүктеу мүмкін болмады')
        self.assertNotContains(r, 'Таң алдында')


# ════════════════════════════ Component fixtures ═══════════════════════════

class ErrorStateComponent(TestCase):

    def test_default_renders_via_states_showcase(self):
        # /_design/states/ рендерит ErrorState в дефолтном и compact-вариантах
        with override_settings(DEBUG=True):
            r = self.client.get(reverse('core:design_states'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Бір нәрсе сәтсіз болды')
        self.assertContains(r, 'Қайта жүктеу')      # block-вариант
        self.assertContains(r, 'Қайта көру')        # compact-вариант
        # role=alert для a11y
        self.assertContains(r, 'role="alert"')


class SkeletonComponents(TestCase):

    def test_all_skeleton_classes_in_showcase(self):
        with override_settings(DEBUG=True):
            r = self.client.get(reverse('core:design_states'))
        self.assertEqual(r.status_code, 200)
        # animate-pulse + bg-slate-200 — обязательные классы skeleton-примитива
        self.assertContains(r, 'animate-pulse')
        self.assertContains(r, 'bg-slate-200')

    def test_showcase_shows_all_sections(self):
        with override_settings(DEBUG=True):
            r = self.client.get(reverse('core:design_states'))
        self.assertContains(r, 'Skeleton primitives')
        self.assertContains(r, 'BookCardSmall')
        self.assertContains(r, 'DeskBookCardWide')
        self.assertContains(r, 'Notification')
        self.assertContains(r, 'Comment')
        self.assertContains(r, 'Chapter body')
        self.assertContains(r, 'ErrorState')


class DesignStatesGated(TestCase):

    @override_settings(DEBUG=False)
    def test_404_when_debug_false(self):
        r = self.client.get(reverse('core:design_states'))
        self.assertEqual(r.status_code, 404)

    @override_settings(DEBUG=True)
    def test_200_when_debug_true(self):
        r = self.client.get(reverse('core:design_states'))
        self.assertEqual(r.status_code, 200)
