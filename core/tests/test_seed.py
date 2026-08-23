"""`seed_demo` — механизм, который заменит «данные едут вместе с кодом».

До Ф14 корпус лежал литералами в git и переносился между машинами сам.
После — переносит его эта команда, и проверять её надо ровно по двум
свойствам, которых у литералов не было.

**Идемпотентность.** Команду запускают на пустой базе, поверх засеянной и
после смены схемы. Второй запуск обязан не удваивать корпус и приводить
изменённые записи обратно к эталону — иначе «засеять ещё раз» перестаёт
быть безопасным действием, и им перестают пользоваться.

**Совпадение со стабом.** Пока источника два, любое расхождение — это
молчаливая смена содержимого страниц в тот день, когда чтение
переключится на базу. Тесты этого файла покрывают весь корпус —
от произведений до уведомлений, — и проверяют не колонки, а ответы:
подпись давности, фазу конкурса, процент в опросе.
"""

from django.core.management import call_command
from django.db.utils import IntegrityError
from django.test import TestCase

from core import stub_data
from core.models import (
    AwardGrant,
    BookOfWeek,
    Chapter,
    ChapterPoll,
    Collection,
    Contest,
    Follow,
    Genre,
    LibraryEntry,
    Notification,
    ReadingProgress,
    SchoolLink,
    Story,
    StoryComment,
    Submission,
    Tag,
    User,
)


def seed():
    call_command('seed_demo', quiet=True)


class SeedIsIdempotent(TestCase):

    def test_second_run_adds_nothing(self):
        seed()
        users, tags = User.objects.count(), Tag.objects.count()
        seed()
        self.assertEqual(User.objects.count(), users)
        self.assertEqual(Tag.objects.count(), tags)

    def test_second_run_restores_edited_records(self):
        """Идемпотентность — это сходимость к эталону, а не «ничего не
        делать при повторе»."""
        seed()
        User.objects.filter(username='aidana').update(pen_name='кто-то другой')
        seed()
        self.assertEqual(User.objects.get(username='aidana').pen_name, 'aidana')

    def test_seeding_does_not_touch_the_genre_reference(self):
        """Жанры заливает миграция: два источника одного справочника —
        это ровно тот случай, ради которого сид и разведён с миграцией."""
        seed()
        seed()
        self.assertEqual(Genre.objects.count(), 12)


class SeededUsersMatchTheStub(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed()

    def test_every_stub_author_became_a_user(self):
        self.assertEqual(User.objects.count(), len(stub_data.AUTHORS))

    def test_names_and_bio_transferred(self):
        for author in stub_data.AUTHORS:
            with self.subTest(author=author.username):
                user = User.objects.get(username=author.username)
                self.assertEqual(user.name, author.name)
                self.assertEqual(user.pen_name, author.pen_name)
                self.assertEqual(user.bio, author.bio)

    def test_public_name_matches_the_stub(self):
        """То, как автора зовут читателю, обязано совпасть до буквы: это
        имя стоит в шести местах рендера."""
        for author in stub_data.AUTHORS:
            with self.subTest(author=author.username):
                user = User.objects.get(username=author.username)
                self.assertEqual(user.public_name, author.public_name)

    def test_joined_year_survives(self):
        for author in stub_data.AUTHORS:
            with self.subTest(author=author.username):
                user = User.objects.get(username=author.username)
                self.assertEqual(user.joined_year, author.joined_year)

    def test_demo_users_have_no_usable_password(self):
        """Настоящего логина до этапа 9 нет. Пустой пароль означал бы «вход
        без пароля», а не «входа нет»."""
        for user in User.objects.all():
            with self.subTest(user=user.username):
                self.assertFalse(user.has_usable_password())


class SeededTagsMatchTheStub(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed()

    def test_every_stub_tag_became_a_row(self):
        self.assertEqual(Tag.objects.count(), len(stub_data.TAGS))

    def test_statuses_transferred(self):
        """Pending остаётся pending: путь тега — предмет решения модератора,
        и сид не имеет права его пройти за него (BR-TAG-03)."""
        for tag in stub_data.TAGS:
            with self.subTest(tag=tag.slug):
                self.assertEqual(Tag.objects.get(slug=tag.slug).status, tag.status)

    def test_pending_tags_are_not_public(self):
        pending = [t.slug for t in stub_data.TAGS if t.status == 'pending']
        self.assertTrue(pending, 'в стабе нет pending-тега — проверять нечего')
        for slug in pending:
            with self.subTest(tag=slug):
                self.assertFalse(Tag.objects.get(slug=slug).is_public)

    def test_usage_counters_are_not_stored(self):
        """`usage_count` и `weekly_count` — агрегаты по работам, колонок под
        них нет; сид не должен был их «перенести»."""
        fields = {f.name for f in Tag._meta.get_fields()}
        self.assertNotIn('usage_count', fields)
        self.assertNotIn('weekly_count', fields)


class SeededStoriesMatchTheStub(TestCase):
    """Карточка из базы обязана совпасть с карточкой из стаба.

    Это и есть приёмка этапа: в день, когда каталог переключится на базу,
    расхождение здесь стало бы сменой выдачи, которую никто не заказывал.
    Поэтому сверяются не только колонки, но и то, что из них считается, —
    бакет объёма и время чтения решают, в какой фильтр работа попадёт.
    """

    @classmethod
    def setUpTestData(cls):
        seed()

    def test_every_stub_story_became_a_row(self):
        self.assertEqual(Story.objects.count(), len(stub_data.STORIES))

    def test_columns_transferred(self):
        for stub in stub_data.STORIES:
            with self.subTest(story=stub.slug):
                story = Story.objects.get(slug=stub.slug)
                self.assertEqual(story.title, stub.title)
                self.assertEqual(story.author.username, stub.author_username)
                self.assertEqual(story.cover, stub.cover)
                self.assertEqual(story.annotation, stub.annotation)
                self.assertEqual(story.status, stub.status)
                self.assertEqual(story.audience, stub.audience)
                self.assertEqual(story.format, stub.format)
                self.assertEqual(story.chapters, stub.chapters)
                self.assertEqual(story.views, stub.views)
                self.assertEqual(story.recent_views, stub.recent_views)
                self.assertEqual(story.likes, stub.likes)
                self.assertEqual(story.comments, stub.comments)

    def test_genres_resolve_in_the_same_order(self):
        """Порядок значим: первый жанр даёт цвет карточки и обложки."""
        for stub in stub_data.STORIES:
            with self.subTest(story=stub.slug):
                story = Story.objects.get(slug=stub.slug)
                self.assertEqual([g.slug for g in story.genres_resolved],
                                 [g.slug for g in stub.genres_resolved])

    def test_tags_transferred(self):
        for stub in stub_data.STORIES:
            with self.subTest(story=stub.slug):
                story = Story.objects.get(slug=stub.slug)
                self.assertEqual({t.slug for t in story.tags_resolved},
                                 {t.slug for t in stub.tags_resolved})

    def test_audience_stays_unset_where_the_author_did_not_choose(self):
        """Пустая отметка — отдельное состояние, а не «10+» (BR-10b). Если
        сид её подменит, чек-лист кабинета нарисует зелёную галку за автора."""
        unset = [s.slug for s in stub_data.STORIES if not s.audience]
        self.assertTrue(unset, 'в стабе нет работы без отметки — проверять нечего')
        for slug in unset:
            with self.subTest(story=slug):
                self.assertEqual(Story.objects.get(slug=slug).audience, '')

    def test_reading_effort_matches(self):
        """`length_bucket` и `read_minutes` решают, в какой фильтр каталога
        работа попадёт, и считаются из текста глав, а не из колонки."""
        for stub in stub_data.STORIES:
            with self.subTest(story=stub.slug):
                story = Story.objects.get(slug=stub.slug)
                self.assertEqual(story.total_chars, stub.total_chars)
                self.assertEqual(story.read_minutes, stub.read_minutes)
                self.assertEqual(story.length_bucket, stub.length_bucket)
                self.assertEqual(story.reading_meta_label, stub.reading_meta_label)

    def test_public_visibility_matches(self):
        for stub in stub_data.STORIES:
            with self.subTest(story=stub.slug):
                self.assertEqual(Story.objects.get(slug=stub.slug).is_public,
                                 stub.is_public)

    def test_editorial_badge_transferred(self):
        """Из двух знаков каталога переносится один. «Редакция таңдауы» —
        акт редакции и хранится; «Байқауға қатысады» выводится из заявки,
        и до этапа конкурсов его у модели нет намеренно."""
        editorial = 'Редакция таңдауы'
        for stub in stub_data.STORIES:
            with self.subTest(story=stub.slug):
                story = Story.objects.get(slug=stub.slug)
                self.assertEqual(story.is_editorial_pick, editorial in stub.badges)
                self.assertEqual(story.badges,
                                 (editorial,) if editorial in stub.badges else ())

    def test_single_story_points_at_its_own_chapter(self):
        """Кнопка «Мәтін» у одночастного ведёт в существующую главу, а не
        в пустой редактор."""
        for stub in stub_data.STORIES:
            with self.subTest(story=stub.slug):
                self.assertEqual(Story.objects.get(slug=stub.slug).text_chapter,
                                 stub.text_chapter)


class SeededChaptersCarryTheirText(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed()

    def test_chapter_count_matches_the_stub(self):
        expected = sum(len(stub_data.chapters_of(s.slug)) for s in stub_data.STORIES)
        self.assertEqual(Chapter.objects.count(), expected)

    def test_text_and_titles_transferred(self):
        for stub in stub_data.STORIES:
            for stub_chapter in stub_data.chapters_of(stub.slug):
                with self.subTest(story=stub.slug, chapter=stub_chapter.number):
                    chapter = Chapter.objects.get(story__slug=stub.slug,
                                                  number=stub_chapter.number)
                    self.assertEqual(chapter.title, stub_chapter.title)
                    self.assertEqual(chapter.body, stub_chapter.body)
                    self.assertEqual(chapter.char_count, stub_chapter.char_count)

    def test_declared_count_may_exceed_written_chapters(self):
        """У четырёх сериалов каталога текст не написан вовсе. `chapters`
        поэтому колонка, а не `chapter_set.count()`: вычисление обнулило бы
        им «17 бөлім» на карточке."""
        textless = Story.objects.filter(slug='zhuldyz-kartasy').get()
        self.assertEqual(textless.chapters, 17)
        self.assertEqual(textless.chapter_set.count(), 0)
        self.assertGreater(textless.read_minutes, 3)

    def test_reactions_transferred(self):
        for stub in stub_data.STORIES:
            for stub_chapter in stub_data.chapters_of(stub.slug):
                if not stub_chapter.reactions:
                    continue
                with self.subTest(story=stub.slug, chapter=stub_chapter.number):
                    chapter = Chapter.objects.get(story__slug=stub.slug,
                                                  number=stub_chapter.number)
                    self.assertEqual(chapter.reaction_counts,
                                     dict(stub_chapter.reactions))
                    self.assertEqual(chapter.likes, stub_chapter.likes)

    def test_top_reaction_matches(self):
        """«Чем зацепило» одним словом — та же реакция, что в стабе."""
        checked = 0
        for stub in stub_data.STORIES:
            for stub_chapter in stub_data.chapters_of(stub.slug):
                if not stub_chapter.reactions:
                    continue
                checked += 1
                chapter = Chapter.objects.get(story__slug=stub.slug,
                                              number=stub_chapter.number)
                with self.subTest(story=stub.slug, chapter=stub_chapter.number):
                    self.assertEqual(chapter.top_reaction.slug,
                                     stub_chapter.top_reaction.slug)
        self.assertTrue(checked, 'ни у одной главы нет реакций — тест пуст')

    def test_story_total_equals_the_sum_of_its_chapters(self):
        """BR-14a на моделях: где главы несут реакции, итог в шапке обязан
        сходиться с числами в списке глав — читатель может сложить их сам."""
        checked = 0
        for story in Story.objects.all():
            chapters = list(story.chapter_set.all())
            if not any(c.reactions.exists() for c in chapters):
                continue
            checked += 1
            with self.subTest(story=story.slug):
                self.assertEqual(story.likes, sum(c.likes for c in chapters))
        self.assertTrue(checked, 'ни у одной работы нет реакций — тест пуст')


class SeededContestsMatchTheStub(TestCase):
    """Конкурс — самый производный объект проекта: из трёх дат считается
    почти всё, что видит участник. Сверяются поэтому не колонки, а ответы:
    фаза, отсчёт, строка «что дальше», возрастная вилка.
    """

    @classmethod
    def setUpTestData(cls):
        seed()

    def test_every_stub_contest_became_a_row(self):
        self.assertEqual(Contest.objects.count(), len(stub_data.CONTESTS))

    def test_dates_and_numbers_transferred(self):
        for stub in stub_data.CONTESTS:
            with self.subTest(contest=stub.slug):
                contest = Contest.objects.get(slug=stub.slug)
                self.assertEqual(contest.name, stub.name)
                self.assertEqual(contest.subtitle, stub.subtitle)
                self.assertEqual(contest.opens_on, stub.opens_on)
                self.assertEqual(contest.closes_on, stub.closes_on)
                self.assertEqual(contest.results_on, stub.results_on)
                self.assertEqual(contest.prize_kzt, stub.prize_kzt)
                self.assertEqual(contest.series, stub.series)
                self.assertEqual(contest.min_chars, stub.min_chars)
                self.assertEqual(contest.max_chars, stub.max_chars)
                self.assertEqual(contest.min_age, stub.min_age)
                self.assertEqual(contest.max_age, stub.max_age)

    def test_phase_and_countdown_match(self):
        """Фаза выводится из дат (DEC-45), и обе стороны обязаны вывести
        одно и то же — иначе в день переключения бейдж конкурса сменится."""
        for stub in stub_data.CONTESTS:
            with self.subTest(contest=stub.slug):
                contest = Contest.objects.get(slug=stub.slug)
                self.assertEqual(contest.phase, stub.phase)
                self.assertEqual(contest.is_accepting, stub.is_accepting)
                self.assertEqual(contest.is_finished, stub.is_finished)
                self.assertEqual(contest.days_left, stub.days_left)
                self.assertEqual(contest.days_until_open, stub.days_until_open)
                self.assertEqual(contest.year, stub.year)

    def test_all_four_phases_are_represented(self):
        """Иначе предыдущий тест проверяет одну ветку из четырёх."""
        phases = {c.phase for c in Contest.objects.all()}
        self.assertEqual(phases, set(stub_data.CONTEST_PHASES))

    def test_sentences_match(self):
        """`timing_line` и `eligibility_line` собираются в слое данных, а
        не в шаблоне: их показывают по три поверхности каждую."""
        for stub in stub_data.CONTESTS:
            with self.subTest(contest=stub.slug):
                contest = Contest.objects.get(slug=stub.slug)
                self.assertEqual(contest.timing_line, stub.timing_line)
                self.assertEqual(contest.eligibility_line, stub.eligibility_line)
                self.assertEqual(contest.opens_on_label, stub.opens_on_label)
                self.assertEqual(contest.closes_on_label, stub.closes_on_label)
                self.assertEqual(contest.results_on_label, stub.results_on_label)

    def test_composition_transferred(self):
        for stub in stub_data.CONTESTS:
            with self.subTest(contest=stub.slug):
                contest = Contest.objects.get(slug=stub.slug)
                self.assertEqual(contest.conditions, list(stub.conditions))
                self.assertEqual([m.name for m in contest.jury],
                                 [m.name for m in stub.jury])
                self.assertEqual([m.role for m in contest.jury],
                                 [m.role for m in stub.jury])
                self.assertEqual([a.slug for a in contest.awards],
                                 [a.slug for a in stub.awards])
                self.assertEqual([a.image for a in contest.awards],
                                 [a.image for a in stub.awards])

    def test_timeline_states_are_derived_the_same_way(self):
        """Состояние этапа считается от календаря. Хранимое уже расходилось
        с данными: «Өтінім қабылдау» конкурса 2023 года стоял активным."""
        for stub in stub_data.CONTESTS:
            contest = Contest.objects.get(slug=stub.slug)
            with self.subTest(contest=stub.slug):
                self.assertEqual([s.label for s in contest.timeline],
                                 [s.label for s in stub.timeline])
                self.assertEqual([s.period for s in contest.timeline],
                                 [s.period for s in stub.timeline])
                self.assertEqual([s.state for s in contest.timeline],
                                 [s.state for s in stub.timeline])

    def test_submission_count_is_counted_not_stored(self):
        for stub in stub_data.CONTESTS:
            with self.subTest(contest=stub.slug):
                self.assertEqual(Contest.objects.get(slug=stub.slug).submissions,
                                 stub.submissions)

    def test_winners_come_from_grants(self):
        for stub in stub_data.CONTESTS:
            with self.subTest(contest=stub.slug):
                contest = Contest.objects.get(slug=stub.slug)
                self.assertEqual(contest.winners, stub.winners)
                self.assertEqual([s.slug for s in contest.winner_stories],
                                 [s.slug for s in stub.winner_stories])

    def test_finished_contest_actually_has_winners(self):
        """Иначе предыдущий тест сверяет два пустых кортежа."""
        finished = Contest.objects.get(slug='zhas-aldym-2023')
        self.assertTrue(finished.is_finished)
        self.assertEqual(len(finished.winners), 2)

    def test_editions_link_by_series(self):
        """Связь выпусков по слагу семейства, а не по совпадению имён
        (BR-47): без неё завершённый конкурс — тупик."""
        for stub in stub_data.CONTESTS:
            with self.subTest(contest=stub.slug):
                contest = Contest.objects.get(slug=stub.slug)
                self.assertEqual([c.slug for c in contest.other_editions],
                                 [c.slug for c in stub.other_editions])

    def test_grant_notes_transferred(self):
        for stub in stub_data.AWARD_GRANTS:
            with self.subTest(award=stub.award_slug, contest=stub.contest_slug):
                grant = AwardGrant.objects.get(contest__slug=stub.contest_slug,
                                               award__slug=stub.award_slug)
                self.assertEqual(grant.story.slug, stub.story_slug)
                self.assertEqual(grant.note, stub.note)
                self.assertEqual(grant.author.username,
                                 stub.story.author_username)


class SeededSubmissionsMatchTheStub(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed()

    def test_every_stub_submission_became_a_row(self):
        expected = sum(len(v) for v in stub_data.SUBMISSIONS_BY_USER.values())
        self.assertEqual(Submission.objects.count(), expected)

    def test_fields_transferred(self):
        for username, subs in stub_data.SUBMISSIONS_BY_USER.items():
            for stub in subs:
                with self.subTest(author=username, contest=stub.contest_slug):
                    row = Submission.objects.get(author__username=username,
                                                 contest__slug=stub.contest_slug)
                    self.assertEqual(row.story.slug, stub.story_slug)
                    self.assertEqual(row.submitted_on, stub.submitted_on)
                    self.assertEqual(row.status, stub.status)
                    self.assertEqual(row.note, stub.note)

    def test_relative_label_is_derived(self):
        """«5 күн бұрын» считается от даты. Хранимая строка не просто
        устаревала — она лгала проверяемо (BR-41a)."""
        for username, subs in stub_data.SUBMISSIONS_BY_USER.items():
            for stub in subs:
                with self.subTest(author=username, contest=stub.contest_slug):
                    row = Submission.objects.get(author__username=username,
                                                 contest__slug=stub.contest_slug)
                    self.assertEqual(row.submitted_label, stub.submitted_label)

    def test_submission_lies_inside_the_intake_window(self):
        """Инвариант данных: подача не может быть раньше открытия приёма
        или позже дедлайна."""
        for row in Submission.objects.select_related('contest'):
            with self.subTest(author=row.author.username,
                              contest=row.contest.slug):
                self.assertGreaterEqual(row.submitted_on, row.contest.opens_on)
                self.assertLessEqual(row.submitted_on, row.contest.closes_on)

    def test_one_submission_per_author_per_contest(self):
        """BR-23 — ограничение базы, а не только формы: вторая заявка
        ломает и счёт участников, и конкурсную биографию."""
        row = Submission.objects.first()
        with self.assertRaises(IntegrityError):
            Submission.objects.create(contest=row.contest, author=row.author,
                                      story=row.story,
                                      submitted_on=row.submitted_on)


class SeededSocialGraphMatchesTheStub(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed()

    def test_follow_rows_match(self):
        for follower, targets in stub_data.FOLLOWING.items():
            with self.subTest(user=follower):
                actual = set(Follow.objects
                             .filter(follower__username=follower)
                             .values_list('following__username', flat=True))
                self.assertEqual(actual, set(targets))

    def test_follower_counter_comes_from_the_stub_not_from_rows(self):
        """У демо-корпуса счётчик есть, а строк под ним нет: восемь тысяч
        подписчиков некому создать поимённо. Число и строки живут рядом
        осознанно — и число обязано остаться тем же, что рисует профиль."""
        for author in stub_data.AUTHORS:
            with self.subTest(author=author.username):
                user = User.objects.get(username=author.username)
                self.assertEqual(user.followers, author.followers)
        rudazov = User.objects.get(username='rudazov')
        self.assertGreater(rudazov.followers, rudazov.follower_set.count())

    def test_nobody_follows_themselves(self):
        me = User.objects.get(username='aidana')
        with self.assertRaises(IntegrityError):
            Follow.objects.create(follower=me, following=me)


class SeededCollectionsMatchTheStub(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed()

    def test_every_stub_collection_became_a_row(self):
        self.assertEqual(Collection.objects.count(), len(stub_data.COLLECTIONS))

    def test_order_inside_a_collection_is_editorial(self):
        """Порядок в подборке и есть подборка: первые три — витрина."""
        for stub in stub_data.COLLECTIONS:
            with self.subTest(collection=stub.slug):
                collection = Collection.objects.get(slug=stub.slug)
                self.assertEqual([s.slug for s in collection.stories],
                                 [s.slug for s in stub.stories])
                self.assertEqual([s.slug for s in collection.covers],
                                 [s.slug for s in stub.covers])

    def test_count_is_counted(self):
        for stub in stub_data.COLLECTIONS:
            with self.subTest(collection=stub.slug):
                self.assertEqual(Collection.objects.get(slug=stub.slug).count,
                                 stub.count)

    def test_book_of_week_transferred(self):
        stub = stub_data.BOOK_OF_WEEK
        book = BookOfWeek.objects.latest()
        self.assertEqual(book.story.slug, stub.story_slug)
        self.assertEqual(book.editorial_note, stub.editorial_note)
        self.assertEqual(book.quote, stub.quote)


class SeededLibraryMatchesTheStub(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed()

    def test_entries_and_kinds_transferred(self):
        for username, entries in stub_data.LIBRARY_BY_USER.items():
            for stub in entries:
                with self.subTest(user=username, story=stub.story_slug):
                    row = LibraryEntry.objects.get(user__username=username,
                                                   story__slug=stub.story_slug)
                    self.assertEqual(row.kind, stub.kind)
                    self.assertEqual(row.progress_chapter, stub.progress_chapter)

    def test_relative_label_survives_the_conversion(self):
        """Строка «1 апта бұрын» стала датой и обязана прочитаться обратно
        той же строкой — иначе библиотека молча сменила бы текст."""
        for username, entries in stub_data.LIBRARY_BY_USER.items():
            for stub in entries:
                with self.subTest(user=username, story=stub.story_slug):
                    row = LibraryEntry.objects.get(user__username=username,
                                                   story__slug=stub.story_slug)
                    self.assertEqual(row.added_relative, stub.added_relative)

    def test_a_story_lies_in_exactly_one_shelf(self):
        """Три вида не пересекаются (BR-60/61): иначе «Оқуды жалғастыру»
        предложит то, что читатель уже закрыл."""
        row = LibraryEntry.objects.first()
        with self.assertRaises(IntegrityError):
            LibraryEntry.objects.create(user=row.user, story=row.story,
                                        kind='done')

    def test_reading_progress_transferred(self):
        stub = stub_data.SAMPLE_PROGRESS
        row = ReadingProgress.objects.get(user__username='aidana')
        self.assertEqual(row.story.slug, stub.story_slug)
        self.assertEqual(row.current_chapter, stub.current_chapter)
        self.assertEqual(row.quote, stub.quote)
        self.assertEqual(row.minutes_left, stub.minutes_left)
        self.assertEqual(row.last_read_days, stub.last_read_days)


class SeededCommentsMatchTheStub(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed()

    def test_threads_and_replies_transferred(self):
        for story_slug, comments in stub_data.COMMENTS_BY_STORY.items():
            with self.subTest(story=story_slug):
                top = StoryComment.objects.filter(story__slug=story_slug,
                                                  parent__isnull=True)
                self.assertEqual([c.text for c in top],
                                 [c.text for c in comments])
                for stub, row in zip(comments, top):
                    self.assertEqual([r.text for r in row.replies],
                                     [r.text for r in stub.replies])

    def test_nesting_is_one_level_deep(self):
        """BR-30: ответ на ответ превращает обсуждение в дерево, которое
        на телефоне не читается и которое некому модерировать."""
        for row in StoryComment.objects.filter(parent__isnull=False):
            with self.subTest(comment=row.pk):
                self.assertIsNone(row.parent.parent)

    def test_author_badge_is_derived(self):
        for story_slug, comments in stub_data.COMMENTS_BY_STORY.items():
            for stub in comments:
                with self.subTest(story=story_slug, text=stub.text[:20]):
                    row = StoryComment.objects.get(story__slug=story_slug,
                                                   text=stub.text)
                    self.assertEqual(row.is_author_badge, stub.is_author_badge)

    def test_ownership_decides_the_menu(self):
        """Свой комментарий предлагает «Жою», чужой — «Шағым» (BR-33)."""
        row = StoryComment.objects.first()
        self.assertTrue(row.belongs_to(row.author.username))
        self.assertFalse(row.belongs_to('someone-else'))
        self.assertFalse(row.belongs_to(''))

    def test_date_is_derived_from_the_moment(self):
        """Подпись выводится, а не хранится строкой. Две формулировки при
        этом поменялись: «1 күн бұрын» стало «кеше», «1 апта бұрын» —
        «7 күн бұрын». Лесенка в проекте одна, и рукописная строка была
        ровно тем, что BR-70a запрещает."""
        fresh = StoryComment.objects.order_by('-created_at').first()
        self.assertIn('бұрын', fresh.date)
        self.assertNotIn('апта', fresh.date)


class SeededPollsMatchTheStub(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed()

    def test_questions_and_options_transferred(self):
        for (story_slug, number), stub in stub_data.POLLS_BY_CHAPTER.items():
            with self.subTest(story=story_slug, chapter=number):
                poll = ChapterPoll.objects.get(chapter__story__slug=story_slug,
                                               chapter__number=number)
                self.assertEqual(poll.question, stub.question)
                self.assertEqual([(o.slug, o.text) for o in poll.options],
                                 list(stub.options))
                self.assertEqual(poll.total_votes, stub.total_votes)

    def test_closing_is_derived_from_the_next_chapter(self):
        """Опрос закрывается публикацией следующей главы (BR-POLL-05):
        ответ приходит там, сюжетом."""
        for (story_slug, number), stub in stub_data.POLLS_BY_CHAPTER.items():
            with self.subTest(story=story_slug, chapter=number):
                poll = ChapterPoll.objects.get(chapter__story__slug=story_slug,
                                               chapter__number=number)
                self.assertEqual(poll.closed, stub.closed)
                self.assertEqual(poll.answer_chapter, stub.answer_chapter)

    def test_percentages_match(self):
        for (story_slug, number), stub in stub_data.POLLS_BY_CHAPTER.items():
            with self.subTest(story=story_slug, chapter=number):
                poll = ChapterPoll.objects.get(chapter__story__slug=story_slug,
                                               chapter__number=number)
                self.assertEqual([r['percent'] for r in poll.results],
                                 [r['percent'] for r in stub.results])


class SeededNotificationsMatchTheStub(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed()

    def test_every_stub_notification_became_a_row(self):
        expected = sum(len(v) for v in stub_data.NOTIFICATIONS_BY_USER.values())
        self.assertEqual(Notification.objects.count(), expected)

    def _pairs(self):
        """Пары «стаб — строка». Сопоставление по тексту события, а не по
        порядку: у одинаковой давности порядок в выдаче произвольный."""
        for username, items in stub_data.NOTIFICATIONS_BY_USER.items():
            for stub in items:
                row = Notification.objects.get(
                    user__username=username, kind=stub.kind, text=stub.text,
                    story__slug=stub.story_slug or None,
                    contest__slug=stub.contest_slug or None,
                    actor__username=stub.actor_username or None)
                yield username, stub, row

    def test_labels_and_buckets_are_derived(self):
        """`when` и `bucket` считаются из момента. Хранимые, они устаревали
        назавтра (BR-70a)."""
        for username, stub, row in self._pairs():
            with self.subTest(user=username, kind=stub.kind):
                self.assertEqual(row.when, stub.when)
                self.assertEqual(row.bucket, stub.bucket)

    def test_subject_links_survive(self):
        """Уведомление обязано вести к своему предмету (BR-72a)."""
        for username, stub, row in self._pairs():
            with self.subTest(user=username, kind=stub.kind):
                self.assertEqual(row.story.slug if row.story else '',
                                 stub.story_slug)
                self.assertEqual(row.contest.slug if row.contest else '',
                                 stub.contest_slug)
                self.assertEqual(row.actor.username if row.actor else '',
                                 stub.actor_username)

    def test_moderation_outcome_is_stored_with_its_label(self):
        """Исход — акт модератора (BR-72b): из `Story.status` он не
        выводится, потому что статус живёт дальше события."""
        for username, stub, row in self._pairs():
            with self.subTest(user=username, kind=stub.kind):
                self.assertEqual(row.outcome, stub.outcome)
                self.assertEqual(row.outcome_label, stub.outcome_label)


class SeededSchoolLinksMatchTheStub(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed()

    def test_links_transferred_in_order(self):
        rows = list(SchoolLink.objects.all())
        self.assertEqual([r.channel for r in rows],
                         [s.channel for s in stub_data.SCHOOL_LINKS])
        self.assertEqual([r.subtitle for r in rows],
                         [s.subtitle for s in stub_data.SCHOOL_LINKS])
