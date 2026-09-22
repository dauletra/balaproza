"""MOD — модерация как раздел (FR-MOD-*, BR-82, DEC-71).

Раньше это были действия в списке админки: решение они принимали, но
работу модератора не поддерживали. Здесь проверяется не «страница
открылась», а то, ради чего раздел заведён — что решение принимается по
тексту, что двое не читают одно и то же вслепую и что след решения
остаётся с именем того, кто его принял.
"""

from datetime import datetime, time, timedelta

from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core import data
from core.domain.moderation import diff_summary, overdue_label, paragraph_diff
from core.models import (
    ModerationClaim,
    ModerationDecision,
    PortalDay,
    StoryView,
)
from core.tests import factories as make
from core.tests.base import TestCase, login_as_newcomer


def _moderator(client, username='mod_one'):
    user = make.user(username=username)
    user.is_staff = True
    user.save(update_fields=['is_staff'])
    client.force_login(user)
    return user


class TheSectionExistsOnlyForModerators(TestCase):
    """404, а не 403 (BR-82): «нельзя» подтверждало бы, что раздел есть."""

    def setUp(self):
        super().setUp()
        self.story = make.story(chapters=1, published=False,
                                slug='mod-access')
        make.submit(self.story)

    def test_a_guest_and_an_author_get_404(self):
        author_client = Client()
        login_as_newcomer(author_client, 'plain_author')
        for client, who in ((Client(), 'қонақ'), (author_client, 'автор')):
            for url in (reverse('core:moderation_queue'),
                        reverse('core:moderation_detail',
                                kwargs={'slug': self.story.slug})):
                with self.subTest(who=who, url=url):
                    self.assertEqual(client.get(url).status_code, 404)

    def test_a_moderator_gets_the_section(self):
        _moderator(self.client)
        self.assertEqual(
            self.client.get(reverse('core:moderation_queue')).status_code, 200)

    def test_the_link_shows_up_only_for_staff(self):
        reader = Client()
        login_as_newcomer(reader, 'plain_reader')
        # По ссылке целиком: и слово «Модерация», и подстрока
        # `/moderation/` есть у всех — в подвале стоят правила модерации
        # (`/legal/moderation/`), а это не раздел.
        section = f'href="{reverse("core:moderation_queue")}"' 
        self.assertNotContains(reader.get(reverse('core:home')), section)
        _moderator(self.client, 'mod_link')
        self.assertContains(self.client.get(reverse('core:home')), section)


class TheQueueIsBuiltFromSubmittedText(TestCase):
    """Очередь — работы с поданными ревизиями, а не работы в статусе: с
    BR-79 публичный сериал остаётся публичным, пока его новая глава ждёт
    проверки, и фильтр по статусу прятал бы её от модератора."""

    def setUp(self):
        super().setUp()
        self.moderator = _moderator(self.client)
        self.url = reverse('core:moderation_queue')

    def test_only_works_with_something_to_decide(self):
        waiting = make.story(chapters=1, published=False, slug='mod-waiting')
        make.submit(waiting)
        quiet = make.story(chapters=1, published=False, slug='mod-quiet')

        body = self.client.get(self.url).content.decode()
        self.assertIn(waiting.title, body)
        self.assertNotIn(quiet.title, body)

    def test_a_public_serial_with_a_new_chapter_is_in_the_queue(self):
        serial = make.story(chapters=1, format='serial', status='OnProcess',
                            slug='mod-serial')
        make.chapter(serial, number=2, chars=200)
        make.submit(serial)
        self.assertContains(self.client.get(self.url), serial.title)

    def test_the_longest_wait_comes_first(self):
        """Порядок не настраивается: сортировка «по новизне» означала бы,
        что забытая заявка забыта навсегда."""
        first = make.story(chapters=1, published=False, slug='mod-older')
        make.submit(first)
        second = make.story(chapters=1, published=False, slug='mod-newer')
        make.submit(second)

        body = self.client.get(self.url).content.decode()
        self.assertLess(body.index(first.title), body.index(second.title))

    def test_the_axes_answer_different_questions(self):
        fresh = make.story(chapters=1, published=False, slug='mod-first-time')
        make.submit(fresh)
        repeat = make.story(chapters=1, published=False, slug='mod-repeat')
        make.submit(repeat)
        repeat.apply_moderation('needs_work', 'Түзет.', moderator=self.moderator)
        make.submit(repeat)

        first_only = self.client.get(self.url, {'kind': 'first'})
        self.assertContains(first_only, fresh.title)
        repeat_only = self.client.get(self.url, {'kind': 'repeat'})
        self.assertContains(repeat_only, repeat.title)
        self.assertNotContains(repeat_only, fresh.title)

    def test_an_unknown_axis_falls_back_to_everything(self):
        story = make.story(chapters=1, published=False, slug='mod-junk-axis')
        make.submit(story)
        self.assertContains(self.client.get(self.url, {'kind': 'garbage'}),
                            story.title)


class TheCardCarriesWhatTheDecisionIsMadeOn(TestCase):
    """FR-MOD-02/03/05. В админке текста среди страниц решения не было
    вовсе — только номера глав."""

    def setUp(self):
        super().setUp()
        self.moderator = _moderator(self.client)
        self.story = make.story(chapters=1, format='single', slug='mod-card')
        self.chapter = self.story.chapter_set.first()

    def _card(self):
        return self.client.get(reverse('core:moderation_detail',
                                       kwargs={'slug': self.story.slug}))

    def test_the_submitted_text_is_on_the_page(self):
        self.chapter.body = 'ТЕКСЕРУГЕ ЖІБЕРІЛГЕН МӘТІН.'
        self.chapter.save()
        data.submit_story_for_review(self.story)
        self.assertContains(self._card(), 'ТЕКСЕРУГЕ ЖІБЕРІЛГЕН МӘТІН.')

    def test_a_repeat_submission_shows_what_changed(self):
        self.chapter.body += '\n\nАвтор жаңа абзац қосты.'
        self.chapter.save()
        data.submit_story_for_review(self.story)

        card = self._card()
        self.assertContains(card, 'Өзгерісті көрсету')
        self.assertContains(card, 'Автор жаңа абзац қосты.')

    def test_a_first_publication_has_nothing_to_compare_with(self):
        fresh = make.story(chapters=1, published=False, slug='mod-fresh-card')
        make.submit(fresh)
        card = self.client.get(reverse('core:moderation_detail',
                                       kwargs={'slug': fresh.slug}))
        self.assertContains(card, 'алғаш рет')
        self.assertNotContains(card, 'Өзгерісті көрсету')

    def test_past_decisions_are_on_the_card(self):
        """Без них повторная подача читается вслепую: неизвестно, что уже
        просили исправить."""
        data.submit_story_for_review(self.story) if False else None
        self.chapter.body += ' Тағы бір сөйлем.'
        self.chapter.save()
        data.submit_story_for_review(self.story)
        self.story.apply_moderation('needs_work', 'Диалог үзілген.',
                                    moderator=self.moderator)
        self.chapter.body += ' Түзетілді.'
        self.chapter.save()
        data.submit_story_for_review(self.story)

        card = self._card()
        self.assertContains(card, 'Бұрынғы шешімдер')
        self.assertContains(card, 'Диалог үзілген.')

    def test_a_withdrawn_submission_leaves_nothing_to_decide(self):
        """Автор мог отозвать заявку, пока модератор читал (BR-80): три
        кнопки об этом молчали бы."""
        self.chapter.body += ' Өзгеріс.'
        self.chapter.save()
        data.submit_story_for_review(self.story)
        data.withdraw_story_from_review(self.story)

        card = self._card()
        self.assertContains(card, 'Шешетін нәрсе жоқ')
        self.assertNotContains(card, 'name="outcome"')


class TakingAWorkInHandIsAWarningNotALock(TestCase):
    """BR-82. Двое, открывшие одну работу, до этого узнавали друг о друге
    только по результату — второй читал уже решённое."""

    def setUp(self):
        super().setUp()
        self.moderator = _moderator(self.client)
        self.story = make.story(chapters=1, published=False, slug='mod-claim')
        make.submit(self.story)
        self.url = reverse('core:moderation_claim',
                           kwargs={'slug': self.story.slug})

    def test_claiming_and_releasing(self):
        self.client.post(self.url, {'action': 'claim'})
        self.assertTrue(ModerationClaim.objects.filter(
            story=self.story, moderator=self.moderator).exists())

        self.client.post(self.url, {'action': 'release'})
        self.assertFalse(ModerationClaim.objects.filter(
            story=self.story).exists())

    def test_a_foreign_claim_is_not_overwritten_but_named(self):
        other = Client()
        first = _moderator(other, 'mod_first')
        other.post(self.url, {'action': 'claim'})

        response = self.client.post(self.url, {'action': 'claim'}, follow=True)
        self.assertContains(response, first.public_name)
        claim = ModerationClaim.objects.get(story=self.story)
        self.assertEqual(claim.moderator_id, first.pk)

    def test_a_foreign_claim_cannot_be_released(self):
        other = Client()
        _moderator(other, 'mod_second')
        other.post(self.url, {'action': 'claim'})

        self.client.post(self.url, {'action': 'release'})
        self.assertTrue(ModerationClaim.objects.filter(story=self.story).exists())

    def test_the_decision_takes_the_mark_off(self):
        self.client.post(self.url, {'action': 'claim'})
        self.story.apply_moderation('approved', moderator=self.moderator)
        self.assertFalse(ModerationClaim.objects.filter(story=self.story).exists())


class ADecisionLeavesAnActWithItsAuthor(TestCase):
    """BR-82. След решения был один — `Notification`, адресованное автору;
    у него нет автора решения, и вопрос «кто одобрил вот это» ответа не
    имел вовсе."""

    def setUp(self):
        super().setUp()
        self.moderator = _moderator(self.client)
        self.story = make.story(chapters=2, format='serial', published=False,
                                slug='mod-act')
        make.submit(self.story)
        self.url = reverse('core:moderation_decide',
                           kwargs={'slug': self.story.slug})

    def test_the_act_names_the_moderator_and_the_scope(self):
        self.client.post(self.url, {'outcome': 'approved', 'reason': ''})
        decision = ModerationDecision.objects.get(story=self.story)
        self.assertEqual(decision.moderator, self.moderator)
        self.assertEqual(decision.outcome, 'approved')
        self.assertEqual(decision.chapters, 2)

    def test_a_negative_outcome_without_a_reason_changes_nothing(self):
        response = self.client.post(
            self.url, {'outcome': 'needs_work', 'reason': '   '}, follow=True)
        self.assertContains(response, 'Себепсіз')
        self.assertFalse(ModerationDecision.objects.filter(
            story=self.story).exists())
        self.story.refresh_from_db()
        self.assertEqual(self.story.status, 'OnModeration')

    def test_approval_reaches_the_reader(self):
        self.client.post(self.url, {'outcome': 'approved', 'reason': ''})
        self.assertEqual(len(data.chapters_of(self.story.slug)), 2)
        self.story.refresh_from_db()
        self.assertTrue(self.story.is_public)


class TheDiffReadsAsProseNotAsCharacters(TestCase):
    """Единица сравнения — абзац: посимвольный diff по казахскому тексту
    нечитаем, построчный распадается на обрывки предложений."""

    def test_added_removed_and_untouched(self):
        old = 'Бірінші абзац.\n\nЕкінші абзац.\n\nҮшінші абзац.'
        new = 'Бірінші абзац.\n\nЕкінші абзац өзгерді.\n\nҮшінші абзац.'
        rows = paragraph_diff(old, new)
        kinds = {row['kind'] for row in rows}
        self.assertEqual(kinds, {'same', 'added', 'removed'})
        self.assertIn({'kind': 'added', 'text': 'Екінші абзац өзгерді.'}, rows)
        self.assertIn({'kind': 'removed', 'text': 'Екінші абзац.'}, rows)

    def test_the_summary_counts_both_directions(self):
        summary = diff_summary(paragraph_diff('Бір.\n\nЕкі.', 'Бір.\n\nҮш.'))
        self.assertEqual(summary, {'added': 1, 'removed': 1})

    def test_an_empty_previous_version_is_all_new(self):
        rows = paragraph_diff('', 'Жаңа мәтін.')
        self.assertEqual(rows, [{'kind': 'added', 'text': 'Жаңа мәтін.'}])


class TheModerationPagesStayWithinTheirQueryBudget(TestCase):
    """Новой странице заводится бюджет — он один ловит N+1 при полностью
    зелёной суите."""

    def setUp(self):
        super().setUp()
        self.moderator = _moderator(self.client)
        for n in range(3):
            story = make.story(chapters=2, format='serial', published=False,
                               slug=f'mod-budget-{n}')
            make.submit(story)

    def test_the_queue_does_not_grow_with_the_line(self):
        """Срок ожидания, число глав и метка приезжают выдачей: без этого
        очередь из двадцати работ стоила бы шестьдесят запросов.

        Семь, не шесть: плюс один `COUNT` за бейдж открытых жалоб в шапке
        (BR-33) — тот же счётчик у `/moderation/reports/`.

        Восемь: плюс `COUNT` просроченных заявок (D1). Обещание «әдетте
        тәулік ішінде» стоит у автора на экране отправки, и видно оно
        должно быть там, где его выполняют, — иначе о нарушенном сроке
        узнают из жалобы, то есть позже самого автора. Число не растёт с
        длиной очереди, как и остальные семь.

        Девять: плюс `COUNT` задержанных комментариев (D2) — тот же
        бейдж в шапке, что у жалоб. Именно `COUNT`, а не список: тексты
        задержанного на этой странице не показывают."""
        with self.assertNumQueries(9):
            self.client.get(reverse('core:moderation_queue'))

    def test_the_card_does_not_grow_with_the_chapters(self):
        with self.assertNumQueries(8):
            self.client.get(reverse('core:moderation_detail',
                                    kwargs={'slug': 'mod-budget-0'}))


class ThePortalCountsItself(TestCase):
    """Сводка (D6): пять вопросов, на которые до неё ответа не было.

    Всё считается своей базой. Стороннего счётчика на портале нет
    намеренно: на детской площадке чужой скрипт — это абзац в политике
    конфиденциальности и данные, ушедшие наружу.
    """

    def setUp(self):
        super().setUp()
        _moderator(self.client, 'summary_mod')
        self.url = reverse('core:moderation_summary')

    def test_the_author_funnel_counts_each_step(self):
        """Смысл в разрывах: между «вошёл» и «дозаполнил» видна цена
        анкеты, между «дозаполнил» и «начал писать» — цена пустого
        экрана."""
        before = data.portal_summary()

        newcomer = make.user()
        writer = make.user()
        make.story(author=writer, chapters=1, published=False,
                   status='NotPublished')
        publisher = make.user()
        make.story(author=publisher, chapters=1)

        after = data.portal_summary()

        self.assertEqual(after['signed_up'] - before['signed_up'], 3)
        self.assertEqual(after['wrote'] - before['wrote'], 2)
        self.assertEqual(after['published'] - before['published'], 1)
        self.assertNotIn(newcomer, [])   # заведён, но ничего не написал

    def test_it_names_the_broken_promise(self):
        """Просрочка — единственное число здесь, по которому надо
        действовать сегодня."""
        page = self.client.get(self.url)

        self.assertContains(page, 'Мерзімнен асқан')
        self.assertContains(page, str(data.REVIEW_PROMISE_HOURS))

    def test_the_page_is_closed_to_everyone_else(self):
        reader = Client()
        login_as_newcomer(reader, 'summary_reader')

        self.assertEqual(reader.get(self.url).status_code, 404)


# ── Суточный снимок и возвращаемость читателя (3.1 в PLAN-AUDIT.md) ──────

def _read(story, viewer, day):
    """Засчитанное прочтение в конкретный день, полднем по Алматы —
    чтобы попадание в сутки не зависело от того, когда идёт прогон."""
    moment = timezone.make_aware(
        datetime.combine(day, time.min)) + timedelta(hours=12)
    return StoryView.objects.create(story=story, viewer=viewer,
                                    created_at=moment)


class TheReaderDayCountsWhoCameBack(TestCase):
    """Вопрос, на который портал не мог ответить вовсе: возвращается ли
    человек на второй день.

    Ответ всё это время лежал в базе — журнал оқылым несёт читателя и
    момент, — и просто не спрашивался. Живёт он две недели, поэтому
    снимать это число можно только вовремя.
    """

    def setUp(self):
        super().setUp()
        self.yesterday = timezone.localdate() - timedelta(days=1)
        self.before = self.yesterday - timedelta(days=1)
        self.story = make.story(author=make.user())

    def test_a_reader_of_both_days_counts_as_returning(self):
        loyal = make.user()
        _read(self.story, loyal, self.before)
        _read(self.story, loyal, self.yesterday)

        day = data.reader_day(self.yesterday)

        self.assertEqual(day['readers'], 1)
        self.assertEqual(day['returning_readers'], 1)

    def test_a_reader_who_came_once_does_not(self):
        _read(self.story, make.user(), self.yesterday)

        day = data.reader_day(self.yesterday)

        self.assertEqual(day['readers'], 1)
        self.assertEqual(day['returning_readers'], 0)

    def test_a_guest_is_not_counted_at_all(self):
        """У гостя личности нет, и заводить её ради счётчика значило бы
        следить за ребёнком ровно там, где политика обещает обратное."""
        _read(self.story, None, self.yesterday)

        self.assertEqual(data.reader_day(self.yesterday)['readers'], 0)

    def test_two_visits_in_a_day_are_one_reader(self):
        twice = make.user()
        _read(self.story, twice, self.yesterday)
        _read(self.story, twice, self.yesterday)

        self.assertEqual(data.reader_day(self.yesterday)['readers'], 1)

    def test_an_empty_day_answers_nobody_and_not_a_division_by_zero(self):
        row = PortalDay(day=self.yesterday, readers=0, returning_readers=0)
        self.assertEqual(row.returning_share, 0)


class TheDailySnapshotKeepsWhatCannotBeRecounted(TestCase):
    """Накопленные счётчики убывают: аккаунт удаляется полностью, работа
    сносится автором. «Сколько нас было в среду» после среды не
    восстанавливается ничем — отсюда строка с датой, а не пересчёт.
    """

    def test_it_freezes_yesterday_by_default(self):
        yesterday = timezone.localdate() - timedelta(days=1)

        row = data.record_portal_day()

        self.assertEqual(row.day, yesterday)
        live = data.portal_summary()
        for field in ('signed_up', 'onboarded', 'wrote', 'published',
                      'drafts', 'public', 'decided_week', 'returned_week',
                      'overdue'):
            with self.subTest(field=field):
                self.assertEqual(getattr(row, field), live[field])

    def test_running_it_twice_rewrites_the_same_day(self):
        data.record_portal_day()
        data.record_portal_day()

        day = timezone.localdate() - timedelta(days=1)
        self.assertEqual(PortalDay.objects.filter(day=day).count(), 1)

    def test_a_missed_day_can_be_caught_up(self):
        day = timezone.localdate() - timedelta(days=4)

        row = data.record_portal_day(day)

        self.assertEqual(row.day, day)

    def test_the_command_writes_the_row(self):
        call_command('snapshot_portal', '--quiet')

        self.assertTrue(PortalDay.objects.filter(
            day=timezone.localdate() - timedelta(days=1)).exists())

    def test_the_command_takes_an_explicit_day(self):
        day = timezone.localdate() - timedelta(days=3)

        call_command('snapshot_portal', '--quiet', f'--day={day.isoformat()}')

        self.assertTrue(PortalDay.objects.filter(day=day).exists())


class TheSummaryShowsWhereItIsGoing(TestCase):
    """Страница отвечала «сколько сейчас» и не умела ответить «растёт или
    падает»: в базе лежали только текущие числа."""

    def setUp(self):
        super().setUp()
        _moderator(self.client, 'trend_mod')
        self.url = reverse('core:moderation_summary')

    def test_without_a_week_of_snapshots_it_says_so_instead_of_guessing(self):
        """Ближайшей строки вместо отсутствующей не подставляем: «неделю
        назад» должно значить неделю назад."""
        page = self.client.get(self.url)

        self.assertIsNone(page.context['week_ago'])
        self.assertContains(page, 'Апталық салыстыру әлі жоқ')
        self.assertNotContains(page, 'апта бұрын')

    def test_with_one_it_puts_the_two_numbers_side_by_side(self):
        data.record_portal_day(timezone.localdate() - timedelta(days=7))

        page = self.client.get(self.url)

        self.assertEqual(page.context['week_ago'].day,
                         timezone.localdate() - timedelta(days=7))
        self.assertContains(page, 'апта бұрын')
        self.assertNotContains(page, 'Апталық салыстыру әлі жоқ')

    def test_a_zero_week_is_shown_and_not_swallowed(self):
        """Ноль — законное значение, и `if was` спрятал бы честную неделю
        без единого читателя так же, как отсутствующую строку."""
        row = data.record_portal_day(timezone.localdate() - timedelta(days=7))
        PortalDay.objects.filter(pk=row.pk).update(readers=0, signed_up=0)

        self.assertContains(self.client.get(self.url), 'апта бұрын: 0')

    def test_the_overdue_caption_carries_the_promise(self):
        self.assertContains(self.client.get(self.url), overdue_label())

    def test_the_page_does_not_grow_with_the_portal(self):
        """Бюджет: сводка считает полтора десятка чисел, и ни одно из них
        не должно стоить запроса на строку."""
        data.record_portal_day(timezone.localdate() - timedelta(days=7))
        with self.assertNumQueries(16):
            self.client.get(self.url)
