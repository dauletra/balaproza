"""События ленты: кто узнаёт о чём и когда не узнаёт никто.

До этих тестов уведомления создавались ровно в одном месте — решении
модератора, — а остальные пять типов жили литералами демо-корпуса. Из-за
этого суита была зелёной и на неработающей подписке: лента `aidana`
показывала комментарии и новых подписчиков, потому что их положил
`_corpus.py`, а не потому что кто-то подписался.

Поэтому здесь ничего не берётся из корпуса: все участники заводятся
фабрикой, и «уведомление пришло» означает «его создало действие».

Лежать в базе корпус при этом продолжает — его кладёт раннер. Отсюда
правило: считать уведомления только по своему адресату или своей работе
(`_notes` ниже), никогда `Notification.objects.count()` на всю базу.
Первая же редакция этих тестов на нём и споткнулась — в корпусе есть
своя строка `new_chapter`.

Вопрос каждого класса — один тип события, и у каждого есть отрицательная
пара: событие, которого быть не должно, стоит проверки не меньше, чем
пришедшее. Именно отрицательные и ловят обратную ошибку — ленту, где
автор разговаривает сам с собой.
"""

from datetime import timedelta

from django.utils import timezone

from core import data
from core.models import Follow, Notification
from core.tests import factories as f
from core.tests.base import TestCase


def _notes(user, kind: str = '') -> list:
    rows = Notification.objects.filter(user=user)
    if kind:
        rows = rows.filter(kind=kind)
    return list(rows.order_by('pk'))


class ACommentReachesTheAuthor(TestCase):
    """Автор узнаёт о любом комментарии под своей работой (BR-30)."""

    def setUp(self):
        super().setUp()
        self.author = f.user()
        self.reader = f.user()
        self.story = f.story(author=self.author, chapters=1)

    def test_the_author_is_told_and_the_quote_comes_along(self):
        data.add_comment(self.story, self.reader, text='Соңы керемет болды.')

        note = _notes(self.author, 'comment')[0]
        self.assertEqual(note.actor, self.reader)
        self.assertEqual(note.story, self.story)
        # Цитата — чужие слова, одно из двух исключений из правила «в
        # тексте только событие»: лента показывает её под строкой.
        self.assertEqual(note.text, 'Соңы керемет болды.')
        self.assertFalse(note.read)

    def test_commenting_on_your_own_work_tells_nobody(self):
        """Иначе автор получает ленту, где он разговаривает сам с собой."""
        data.add_comment(self.story, self.author, text='Өзім жазып қойдым.')

        self.assertEqual(_notes(self.author), [])

    def test_a_reply_reaches_the_branch_author_too(self):
        """Адресатов двое: хозяин работы и тот, кому ответили."""
        parent = data.add_comment(self.story, self.reader, text='Бірінші пікір.')
        answering = f.user()
        data.add_comment(self.story, answering, text='Келісемін.', parent=parent)

        self.assertEqual(len(_notes(self.reader, 'comment')), 1)
        # Автору работы — оба: и сам комментарий, и ответ под ним.
        self.assertEqual(len(_notes(self.author, 'comment')), 2)

    def test_the_author_answering_in_their_own_work_gets_one_line_not_two(self):
        """Хозяин работы и хозяин ветки — один человек: событие одно.

        Две одинаковые строки подряд читаются как сбой ленты, а не как два
        события.
        """
        parent = data.add_comment(self.story, self.reader, text='Сұрақ бар.')
        Notification.objects.all().delete()
        data.add_comment(self.story, self.author, text='Жауап беремін.',
                         parent=parent)

        self.assertEqual(len(_notes(self.reader, 'comment')), 1)
        self.assertEqual(_notes(self.author), [])

    def test_a_long_comment_is_cut_to_the_field(self):
        """Колонка держит 300 знаков, а комментарий длиннее бывает."""
        data.add_comment(self.story, self.reader, text='ә' * 500)

        note = _notes(self.author, 'comment')[0]
        self.assertEqual(len(note.text), 300)
        self.assertTrue(note.text.endswith('…'))


class AReactionReachesTheAuthorOnceADay(TestCase):
    """Отклик — событие дня, а не нажатия (BR-REACT-02)."""

    def setUp(self):
        super().setUp()
        self.author = f.user()
        self.reader = f.user()
        self.story = f.story(author=self.author, chapters=3)
        self.chapters = list(self.story.chapter_set.order_by('number'))

    def test_the_author_is_told(self):
        data.toggle_chapter_reaction(self.chapters[0], self.reader, 'juregim')

        note = _notes(self.author, 'like')[0]
        self.assertEqual(note.actor, self.reader)
        # Адресует работу, не главу: у главы своего автора нет, и лента
        # ведёт читателя на страницу произведения.
        self.assertEqual(note.story, self.story)

    def test_reacting_to_your_own_chapter_tells_nobody(self):
        data.toggle_chapter_reaction(self.chapters[0], self.author, 'juregim')

        self.assertEqual(_notes(self.author), [])

    def test_a_whole_serial_read_in_one_evening_is_one_line(self):
        """Сорок глав по пять кнопок — сорок событий, и лента автора
        перестала бы показывать что-либо, кроме них."""
        for chapter in self.chapters:
            data.toggle_chapter_reaction(chapter, self.reader, 'juregim')

        self.assertEqual(len(_notes(self.author, 'like')), 1)

    def test_changing_the_reaction_does_not_add_a_second_line(self):
        data.toggle_chapter_reaction(self.chapters[0], self.reader, 'juregim')
        data.toggle_chapter_reaction(self.chapters[0], self.reader, 'jyladym')

        self.assertEqual(len(_notes(self.author, 'like')), 1)

    def test_removing_a_reaction_is_not_an_event(self):
        """«Тебя больше не отмечают» событием не является."""
        data.toggle_chapter_reaction(self.chapters[0], self.reader, 'juregim')
        Notification.objects.all().delete()
        data.toggle_chapter_reaction(self.chapters[0], self.reader, 'juregim')

        self.assertEqual(_notes(self.author), [])

    def test_the_next_day_is_a_new_event(self):
        """Окно молчания — сутки, а не «однажды и навсегда»: читатель,
        вернувшийся через неделю, — снова новость."""
        data.toggle_chapter_reaction(self.chapters[0], self.reader, 'juregim')
        Notification.objects.filter(user=self.author).update(
            created_at=timezone.now() - timedelta(days=2))

        data.toggle_chapter_reaction(self.chapters[1], self.reader, 'juregim')

        self.assertEqual(len(_notes(self.author, 'like')), 2)

    def test_another_reader_is_not_silenced_by_the_first(self):
        """Окно считается по паре «читатель и работа», а не по работе."""
        other = f.user()
        data.toggle_chapter_reaction(self.chapters[0], self.reader, 'juregim')
        data.toggle_chapter_reaction(self.chapters[0], other, 'juregim')

        self.assertEqual(len(_notes(self.author, 'like')), 2)


class ANewChapterReachesTheSubscribers(TestCase):
    """Подписка ведёт к чтению, а не только к цифре в профиле (BR-79)."""

    def setUp(self):
        super().setUp()
        self.author = f.user()
        self.subscriber = f.user()
        Follow.objects.create(follower=self.subscriber, following=self.author)

    def test_approval_calls_the_subscribers(self):
        story = f.story(author=self.author, chapters=1, published=False)
        f.submit(story)

        story.apply_moderation('approved')

        note = _notes(self.subscriber, 'new_chapter')[0]
        self.assertEqual(note.story, story)
        # Автор назван: без него строка не отвечает, почему она пришла.
        self.assertEqual(note.actor, self.author)
        self.assertEqual(note.text, 'жаңа бөлім қосылды.')

    def test_a_batch_of_chapters_is_one_line_that_says_how_many(self):
        """Одно решение открывает читателю сразу пачку глав, и три строки
        подряд про одну работу — не три события."""
        story = f.story(author=self.author, chapters=3, published=False)
        f.submit(story)

        story.apply_moderation('approved')

        notes = _notes(self.subscriber, 'new_chapter')
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].text, '3 жаңа бөлім қосылды.')

    def test_an_approved_edit_of_a_published_chapter_calls_nobody(self):
        """Правка уже стоящего у читателя текста — не новая часть.

        Именно это отличает «одобрено» от «появилось»: ревизий у главы за
        жизнь много, а читателю она открывается один раз.
        """
        story = f.story(author=self.author, chapters=1)
        Notification.objects.all().delete()
        chapter = story.chapter_set.get()
        data.save_chapter(story, chapter.pk, title=chapter.title,
                          body=chapter.body + ' Түзетілді.',
                          poll_question='', poll_options=[])
        data.submit_story_for_review(story)

        story.apply_moderation('approved')

        self.assertEqual(_notes(self.subscriber), [])

    def test_a_rejection_calls_nobody(self):
        story = f.story(author=self.author, chapters=1, published=False)
        f.submit(story)

        story.apply_moderation('needs_work', 'Соңы жоқ.')

        self.assertEqual(_notes(self.subscriber), [])
        # Автор при этом узнаёт — решение адресовано ему.
        self.assertEqual(len(_notes(self.author, 'moderation')), 1)

    def test_an_author_without_subscribers_costs_nothing(self):
        lonely = f.user()
        story = f.story(author=lonely, chapters=1, published=False)
        f.submit(story)

        story.apply_moderation('approved')

        self.assertEqual(Notification.objects.filter(story=story,
                                                     kind='new_chapter').count(), 0)

    def test_the_mailing_costs_the_same_at_one_subscriber_and_at_six(self):
        """Цена рассылки не должна расти с популярностью автора: поимённое
        создание стоило бы запроса на каждого подписчика.

        Запроса всегда два — выбрать подписчиков и вставить строки, — и
        проверяется именно постоянство: число в `assertNumQueries` тут не
        рекорд, а утверждение «от числа адресатов не зависит».
        """
        story = f.story(author=self.author, chapters=1, published=False)
        f.submit(story)

        with self.assertNumQueries(2):
            data.notify_new_chapter(story, 1)

        for _ in range(5):
            Follow.objects.create(follower=f.user(), following=self.author)
        with self.assertNumQueries(2):
            data.notify_new_chapter(story, 1)

        self.assertEqual(
            Notification.objects.filter(story=story, kind='new_chapter').count(),
            1 + 6)


class AFollowReachesTheAuthor(TestCase):
    """Новый подписчик — событие; ушедший — нет (FR-PROF-04)."""

    def setUp(self):
        super().setUp()
        self.author = f.user()
        self.reader = f.user()

    def test_the_author_is_told(self):
        data.toggle_follow(self.reader, self.author)

        note = _notes(self.author, 'follower')[0]
        self.assertEqual(note.actor, self.reader)

    def test_unfollowing_is_not_an_event(self):
        """«От тебя ушли» автору не сообщают: это не событие, а его
        отсутствие."""
        data.toggle_follow(self.reader, self.author)
        Notification.objects.all().delete()

        data.toggle_follow(self.reader, self.author)

        self.assertEqual(_notes(self.author), [])

    def test_resubscribing_is_an_event_again(self):
        data.toggle_follow(self.reader, self.author)
        data.toggle_follow(self.reader, self.author)
        Notification.objects.all().delete()

        data.toggle_follow(self.reader, self.author)

        self.assertEqual(len(_notes(self.author, 'follower')), 1)


class AContestDecisionReachesTheAuthor(TestCase):
    """Судьба заявки приходит к автору, а не ждёт, пока он проверит сам."""

    def setUp(self):
        super().setUp()
        self.author = f.user()
        self.contest = f.contest(phase='accepting')
        self.story = f.story(author=self.author, chapters=1)
        submission, _ = data.create_submission(
            self.author, self.contest, self.story,
            ai_declaration='no', age_confirmed=True, rules_confirmed=True)
        self.submission = submission

    def test_a_decision_is_told_and_names_the_contest_not_the_text(self):
        self.submission.status = 'accepted'
        data.notify_submission_decided(self.submission)

        note = _notes(self.author, 'contest')[0]
        self.assertEqual(note.contest, self.contest)
        self.assertEqual(note.text, 'өтінімің қабылданды.')
        # Имя конкурса приходит из объекта, а не из текста: переименование
        # иначе оставило бы уведомление врать.
        self.assertNotIn(self.contest.name, note.text)

    def test_being_in_the_queue_is_not_an_event(self):
        """«Қаралуда» — состояние, с которого заявка начинается."""
        data.notify_submission_decided(self.submission)

        self.assertEqual(_notes(self.author), [])

    def test_a_win_comes_by_the_grant_and_names_the_nomination(self):
        award = self.contest.award_set.create(slug='bas-zhuldе', title='Бас жүлде')
        grant = self.contest.grant_set.create(award=award, story=self.story)

        data.notify_award_granted(grant)

        note = _notes(self.author, 'contest')[0]
        self.assertEqual(note.contest, self.contest)
        self.assertIn('Бас жүлде', note.text)


class TheBellCountsWhatTheEventsPut(TestCase):
    """Сквозная проверка: событие доезжает до бейджа и до ленты.

    Пять классов выше спрашивают слой записей. Здесь — что читающая
    половина, переехавшая в тот же модуль, видит написанное: до этой
    работы лента и её наполнение жили в разных файлах и ни одним тестом
    вместе не проверялись.
    """

    def test_a_comment_lights_the_bell_and_lands_in_today(self):
        author = f.user()
        story = f.story(author=author, chapters=1)
        data.add_comment(story, f.user(), text='Оқыдым.')

        self.assertEqual(data.unread_count_for_user(author), 1)
        self.assertEqual(len(data.notifications_for_user(author)['today']), 1)

    def test_the_guest_has_no_bell(self):
        self.assertEqual(data.unread_count_for_user(None), 0)
