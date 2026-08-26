"""`seed_demo` — механизм, который заменит «данные едут вместе с кодом».

До Ф14 корпус лежал литералами в git и переносился между машинами сам.
После — переносит его эта команда, и проверять её надо ровно по двум
свойствам, которых у литералов не было.

**Идемпотентность.** Команду запускают на пустой базе, поверх засеянной и
после смены схемы. Второй запуск обязан не удваивать корпус и приводить
изменённые записи обратно к эталону — иначе «засеять ещё раз» перестаёт
быть безопасным действием, и им перестают пользоваться.

**Совпадение с корпусом.** Команда — перевод: литералы `_corpus.py`
превращаются в строки таблиц, и по дороге кое-что меняет форму (дни
назад становятся датами, текст главы — объёмом, вложенный комментарий —
ссылкой на родителя). Тесты покрывают весь корпус — от произведений до
уведомлений — и проверяют не колонки, а ответы: подпись давности, фазу
конкурса, процент в опросе.

`_corpus` здесь импортируется прямо, в обход фасада, и это второй и
последний модуль, которому так можно: перевод проверяют, сверяя обе
стороны. Правило держит `test_data_facade`.
"""

from django.core.management import call_command
from django.db.utils import IntegrityError
from django.test import TestCase
from django.utils import timezone

from core import data
from core.management.commands import _corpus
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
    """Прогнать сид ещё раз — нужно только тем, кто проверяет повтор.

    Остальным классам звать его незачем: корпус в базе уже лежит, его
    кладёт раннер один раз на прогон. Тринадцать пересевов в
    `setUpTestData` стоили тринадцати секунд и не проверяли ничего, чего
    не проверял первый.
    """
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

    def test_every_stub_author_became_a_user(self):
        self.assertEqual(User.objects.count(), len(_corpus.AUTHORS))

    def test_names_and_bio_transferred(self):
        for author in _corpus.AUTHORS:
            with self.subTest(author=author.username):
                user = User.objects.get(username=author.username)
                self.assertEqual(user.name, author.name)
                self.assertEqual(user.pen_name, author.pen_name)
                self.assertEqual(user.bio, author.bio)

    def test_joined_year_survives(self):
        for author in _corpus.AUTHORS:
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

    def test_every_stub_tag_became_a_row(self):
        self.assertEqual(Tag.objects.count(), len(_corpus.TAGS))

    def test_statuses_transferred(self):
        """Pending остаётся pending: путь тега — предмет решения модератора,
        и сид не имеет права его пройти за него (BR-TAG-03)."""
        for tag in _corpus.TAGS:
            with self.subTest(tag=tag.slug):
                self.assertEqual(Tag.objects.get(slug=tag.slug).status, tag.status)

    def test_pending_tags_are_not_public(self):
        pending = [t.slug for t in _corpus.TAGS if t.status == 'pending']
        self.assertTrue(pending, 'в стабе нет pending-тега — проверять нечего')
        for slug in pending:
            with self.subTest(tag=slug):
                self.assertFalse(Tag.objects.get(slug=slug).is_public)

    def test_showcase_counters_transferred(self):
        """Счётчики витрин — колонки по необходимости (см. `core.models.Tag`),
        и потому обязаны совпасть со стабом: на их расхождении держится
        DEC-31, а вычислить недельный не из чего."""
        for tag in _corpus.TAGS:
            with self.subTest(tag=tag.slug):
                row = Tag.objects.get(slug=tag.slug)
                self.assertEqual(row.usage_count, tag.usage_count)
                self.assertEqual(row.weekly_count, tag.weekly_count)

    def test_weekly_list_still_differs_from_all_time(self):
        """Иначе полоса «Осы аптада» — копия «Танымал тегтер» (DEC-31)."""
        from core import data

        self.assertNotEqual([t.slug for t in data.trending_tags(6)],
                            [t.slug for t in data.popular_tags(6)])


class SeededStoriesMatchTheStub(TestCase):
    """Карточка из базы обязана совпасть с карточкой из стаба.

    Это и есть приёмка этапа: в день, когда каталог переключится на базу,
    расхождение здесь стало бы сменой выдачи, которую никто не заказывал.
    Поэтому сверяются не только колонки, но и то, что из них считается, —
    бакет объёма и время чтения решают, в какой фильтр работа попадёт.
    """

    def test_every_stub_story_became_a_row(self):
        self.assertEqual(Story.objects.count(), len(_corpus.STORIES))

    def test_columns_transferred(self):
        for stub in _corpus.STORIES:
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
        for stub in _corpus.STORIES:
            with self.subTest(story=stub.slug):
                story = Story.objects.get(slug=stub.slug)
                self.assertEqual([g.slug for g in story.genres_resolved],
                                 [g for g in stub.genres if g])

    def test_tags_transferred(self):
        for stub in _corpus.STORIES:
            with self.subTest(story=stub.slug):
                story = Story.objects.get(slug=stub.slug)
                self.assertEqual({t.slug for t in story.tags_resolved},
                                 set(stub.tags))

    def test_audience_stays_unset_where_the_author_did_not_choose(self):
        """Пустая отметка — отдельное состояние, а не «10+» (BR-10b). Если
        сид её подменит, чек-лист кабинета нарисует зелёную галку за автора."""
        unset = [s.slug for s in _corpus.STORIES if not s.audience]
        self.assertTrue(unset, 'в стабе нет работы без отметки — проверять нечего')
        for slug in unset:
            with self.subTest(story=slug):
                self.assertEqual(Story.objects.get(slug=slug).audience, '')

    def test_reading_effort_comes_from_the_text(self):
        """Объём чтения решает, в какой фильтр каталога работа попадёт, и
        считается из текста глав, а не из колонки. Значит, дойти до базы
        обязан сам текст, а не число."""
        for stub in _corpus.STORIES:
            chapters = _corpus.CHAPTERS_BY_STORY.get(stub.slug, ())
            if not chapters:
                continue
            with self.subTest(story=stub.slug):
                story = Story.objects.get(slug=stub.slug)
                self.assertEqual(story.total_chars,
                                 sum(len(c.body) for c in chapters))
                self.assertGreater(story.read_minutes, 0)

    def test_editorial_badge_is_stored(self):
        """«Редакция таңдауы» — акт редакции: из данных он не выводится,
        как и присуждение награды (DEC-46)."""
        editorial = 'Редакция таңдауы'
        for stub in _corpus.STORIES:
            with self.subTest(story=stub.slug):
                story = Story.objects.get(slug=stub.slug)
                self.assertEqual(story.is_editorial_pick, stub.is_editorial_pick)
                self.assertEqual(editorial in story.badges,
                                 stub.is_editorial_pick)

    def test_contest_badge_is_derived_and_finds_what_the_stub_missed(self):
        """Второй знак каталога выводится из заявки в незавершённый конкурс.

        Рукописный список знаков был неполон: у «Таң» заявка на «Алтын
        қалам» есть, а знака не стояло. Ровно поэтому его и не хранят —
        второй экземпляр факта расходится с первым.
        """
        contest = 'Байқауға қатысады'
        marked = {s.slug for s in Story.objects.all() if contest in s.badges}
        self.assertIn('igra-kuklovoda', marked)   # знак стоял и в стабе
        self.assertIn('aidana-tan', marked)       # заявка есть, знака не было
        # Работа, чей единственный конкурс завершён, знака не носит:
        # «участвует» — про идущий конкурс, а не про биографию.
        self.assertNotIn('temniy-lord', marked)

    def test_single_story_points_at_its_own_chapter(self):
        """Кнопка «Мәтін» у одночастного ведёт в существующую главу, а не
        в пустой редактор."""
        for stub in _corpus.STORIES:
            if stub.format != 'single':
                continue
            chapters = _corpus.CHAPTERS_BY_STORY.get(stub.slug, ())
            expected = chapters[0].number if chapters else None
            with self.subTest(story=stub.slug):
                self.assertEqual(Story.objects.get(slug=stub.slug).text_chapter,
                                 expected)


class SeededChaptersCarryTheirText(TestCase):

    def test_chapter_count_matches_the_stub(self):
        expected = sum(len(_corpus.CHAPTERS_BY_STORY.get(s.slug, ())) for s in _corpus.STORIES)
        self.assertEqual(Chapter.objects.count(), expected)

    def test_text_and_titles_transferred(self):
        for stub in _corpus.STORIES:
            for stub_chapter in _corpus.CHAPTERS_BY_STORY.get(stub.slug, ()):
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
        for stub in _corpus.STORIES:
            for stub_chapter in _corpus.CHAPTERS_BY_STORY.get(stub.slug, ()):
                if not stub_chapter.reactions:
                    continue
                with self.subTest(story=stub.slug, chapter=stub_chapter.number):
                    chapter = Chapter.objects.get(story__slug=stub.slug,
                                                  number=stub_chapter.number)
                    self.assertEqual(chapter.reaction_counts,
                                     dict(stub_chapter.reactions))
                    self.assertEqual(
                        chapter.likes,
                        sum(n for _, n in stub_chapter.reactions))

    def test_top_reaction_matches(self):
        """«Чем зацепило» одним словом — реакция с наибольшим счётчиком."""
        checked = 0
        for stub in _corpus.STORIES:
            for stub_chapter in _corpus.CHAPTERS_BY_STORY.get(stub.slug, ()):
                if not stub_chapter.reactions:
                    continue
                checked += 1
                chapter = Chapter.objects.get(story__slug=stub.slug,
                                              number=stub_chapter.number)
                with self.subTest(story=stub.slug, chapter=stub_chapter.number):
                    top = max(stub_chapter.reactions, key=lambda r: r[1])[0]
                    self.assertEqual(chapter.top_reaction.slug, top)
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

    def test_every_stub_contest_became_a_row(self):
        self.assertEqual(Contest.objects.count(), len(_corpus.CONTESTS))

    def test_dates_and_numbers_transferred(self):
        for stub in _corpus.CONTESTS:
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

    # Какую фазу даты корпуса обязаны дать сегодня. Это и есть предмет
    # проверки: сдвиги `_d(±N)` подобраны так, чтобы все четыре фазы были
    # представлены (DEC-45), и правка одного числа тихо оставляет портал
    # без «Жақында» или без судейства.
    PHASES = {
        'qys-ertegisi':     'upcoming',
        'zhas-aldym-2026':  'accepting',
        'bolashak-mektebi': 'accepting',
        'altyn-qalam':      'judging',
        'zhas-aldym-2023':  'finished',
    }

    def test_dates_land_in_the_intended_phase(self):
        for slug, phase in self.PHASES.items():
            with self.subTest(contest=slug):
                self.assertEqual(Contest.objects.get(slug=slug).phase, phase)

    def test_all_four_phases_are_represented(self):
        """Иначе предыдущий тест проверяет одну ветку из четырёх."""
        phases = {c.phase for c in Contest.objects.all()}
        self.assertEqual(phases, set(data.CONTEST_PHASES))

    def test_composition_transferred(self):
        for stub in _corpus.CONTESTS:
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
        for stub in _corpus.CONTESTS:
            contest = Contest.objects.get(slug=stub.slug)
            with self.subTest(contest=stub.slug):
                self.assertEqual([s.label for s in contest.timeline],
                                 [s.label for s in stub.timeline])
                self.assertEqual([(s.starts, s.ends) for s in contest.timeline],
                                 [(s.starts, s.ends) for s in stub.timeline])
                # Состояние этапа не переносится, а выводится из дат: у
                # конкурса 2023 года хранимое «Өтінім қабылдау — идёт»
                # так и стояло активным в 2026-м.
                for stage in contest.timeline:
                    self.assertIn(stage.state, ('done', 'active', 'upcoming'))

    def test_submission_count_is_counted_not_stored(self):
        """«87 өтінім» стояло при одной настоящей заявке (BR-40a)."""
        for stub in _corpus.CONTESTS:
            expected = sum(1 for subs in _corpus.SUBMISSIONS_BY_USER.values()
                           for x in subs if x.contest_slug == stub.slug)
            with self.subTest(contest=stub.slug):
                self.assertEqual(Contest.objects.get(slug=stub.slug).submissions,
                                 expected)

    def test_winners_come_from_grants(self):
        """Победа — присуждение (DEC-46), а не вычисление по данным."""
        for stub in _corpus.CONTESTS:
            expected = [g.story_slug for g in _corpus.AWARD_GRANTS
                        if g.contest_slug == stub.slug]
            with self.subTest(contest=stub.slug):
                contest = Contest.objects.get(slug=stub.slug)
                self.assertEqual(sorted(contest.winners), sorted(expected))
                self.assertEqual(sorted(s.slug for s in contest.winner_stories),
                                 sorted(expected))

    def test_finished_contest_actually_has_winners(self):
        """Иначе предыдущий тест сверяет два пустых кортежа."""
        finished = Contest.objects.get(slug='zhas-aldym-2023')
        self.assertTrue(finished.is_finished)
        self.assertEqual(len(finished.winners), 2)

    def test_editions_link_by_series(self):
        """Связь выпусков по слагу семейства, а не по совпадению имён
        (BR-47): без неё завершённый конкурс — тупик."""
        for stub in _corpus.CONTESTS:
            expected = {c.slug for c in _corpus.CONTESTS
                        if c.series and c.series == stub.series
                        and c.slug != stub.slug}
            with self.subTest(contest=stub.slug):
                contest = Contest.objects.get(slug=stub.slug)
                self.assertEqual({c.slug for c in contest.other_editions},
                                 expected)

    def test_grant_notes_transferred(self):
        for stub in _corpus.AWARD_GRANTS:
            with self.subTest(award=stub.award_slug, contest=stub.contest_slug):
                grant = AwardGrant.objects.get(contest__slug=stub.contest_slug,
                                               award__slug=stub.award_slug)
                self.assertEqual(grant.story.slug, stub.story_slug)
                self.assertEqual(grant.note, stub.note)
                by_slug = {s.slug: s for s in _corpus.STORIES}
                self.assertEqual(grant.author.username,
                                 by_slug[stub.story_slug].author_username)


class SeededSubmissionsMatchTheStub(TestCase):

    def test_every_stub_submission_became_a_row(self):
        expected = sum(len(v) for v in _corpus.SUBMISSIONS_BY_USER.values())
        self.assertEqual(Submission.objects.count(), expected)

    def test_fields_transferred(self):
        for username, subs in _corpus.SUBMISSIONS_BY_USER.items():
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
        for username, subs in _corpus.SUBMISSIONS_BY_USER.items():
            for stub in subs:
                with self.subTest(author=username, contest=stub.contest_slug):
                    row = Submission.objects.get(author__username=username,
                                                 contest__slug=stub.contest_slug)
                    self.assertEqual(row.submitted_on, stub.submitted_on)
                    self.assertTrue(row.submitted_label)

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

    def test_follow_rows_match(self):
        for follower, targets in _corpus.FOLLOWING.items():
            with self.subTest(user=follower):
                actual = set(Follow.objects
                             .filter(follower__username=follower)
                             .values_list('following__username', flat=True))
                self.assertEqual(actual, set(targets))

    def test_follower_counter_comes_from_the_stub_not_from_rows(self):
        """У демо-корпуса счётчик есть, а строк под ним нет: восемь тысяч
        подписчиков некому создать поимённо. Число и строки живут рядом
        осознанно — и число обязано остаться тем же, что рисует профиль."""
        for author in _corpus.AUTHORS:
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

    def test_every_stub_collection_became_a_row(self):
        self.assertEqual(Collection.objects.count(), len(_corpus.COLLECTIONS))

    def test_order_inside_a_collection_is_editorial(self):
        """Порядок в подборке и есть подборка: первые три — витрина."""
        for stub in _corpus.COLLECTIONS:
            with self.subTest(collection=stub.slug):
                collection = Collection.objects.get(slug=stub.slug)
                self.assertEqual([s.slug for s in collection.stories],
                                 list(stub.story_slugs))
                self.assertEqual([s.slug for s in collection.covers],
                                 list(stub.story_slugs[:3]))

    def test_count_is_counted(self):
        """`count` — длина состава, а не колонка рядом с ним."""
        for stub in _corpus.COLLECTIONS:
            with self.subTest(collection=stub.slug):
                self.assertEqual(Collection.objects.get(slug=stub.slug).count,
                                 len(stub.story_slugs))

    def test_book_of_week_transferred(self):
        stub = _corpus.BOOK_OF_WEEK
        book = BookOfWeek.objects.latest()
        self.assertEqual(book.story.slug, stub.story_slug)
        self.assertEqual(book.editorial_note, stub.editorial_note)
        self.assertEqual(book.quote, stub.quote)


class SeededLibraryMatchesTheStub(TestCase):

    def test_entries_and_kinds_transferred(self):
        for username, entries in _corpus.LIBRARY_BY_USER.items():
            for stub in entries:
                with self.subTest(user=username, story=stub.story_slug):
                    row = LibraryEntry.objects.get(user__username=username,
                                                   story__slug=stub.story_slug)
                    self.assertEqual(row.kind, stub.kind)
                    self.assertEqual(row.progress_chapter, stub.progress_chapter)

    def test_the_shelf_remembers_when_it_was_filled(self):
        """Давность лежит датой, а подпись выводится (BR-70a): хранимая
        строка «1 апта бұрын» назавтра врала бы."""
        today = timezone.localdate()
        for username, entries in _corpus.LIBRARY_BY_USER.items():
            for stub in entries:
                with self.subTest(user=username, story=stub.story_slug):
                    row = LibraryEntry.objects.get(user__username=username,
                                                   story__slug=stub.story_slug)
                    self.assertEqual(row.added_on, today - stub.added_ago)
                    self.assertTrue(row.added_relative)

    def test_a_story_lies_in_exactly_one_shelf(self):
        """Три вида не пересекаются (BR-60/61): иначе «Оқуды жалғастыру»
        предложит то, что читатель уже закрыл."""
        row = LibraryEntry.objects.first()
        with self.assertRaises(IntegrityError):
            LibraryEntry.objects.create(user=row.user, story=row.story,
                                        kind='done')

    def test_reading_progress_transferred(self):
        stub = _corpus.SAMPLE_PROGRESS
        row = ReadingProgress.objects.get(user__username='aidana')
        self.assertEqual(row.story.slug, stub.story_slug)
        self.assertEqual(row.current_chapter, stub.current_chapter)
        self.assertEqual(row.quote, stub.quote)
        self.assertEqual(row.minutes_left, stub.minutes_left)
        self.assertEqual(row.last_read_days, stub.last_read_days)


class SeededCommentsMatchTheStub(TestCase):

    def test_threads_and_replies_transferred(self):
        for story_slug, comments in _corpus.COMMENTS_BY_STORY.items():
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
        for story_slug, comments in _corpus.COMMENTS_BY_STORY.items():
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

    def test_questions_and_options_transferred(self):
        for (story_slug, number), stub in _corpus.POLLS_BY_CHAPTER.items():
            with self.subTest(story=story_slug, chapter=number):
                poll = ChapterPoll.objects.get(chapter__story__slug=story_slug,
                                               chapter__number=number)
                self.assertEqual(poll.question, stub.question)
                self.assertEqual([(o.slug, o.text) for o in poll.options],
                                 list(stub.options))
                self.assertEqual(poll.total_votes,
                                 sum(n for _, n in stub.votes))

    def test_closing_is_derived_from_the_next_chapter(self):
        """Опрос закрывается публикацией следующей главы (BR-POLL-05):
        ответ приходит там, сюжетом."""
        for (story_slug, number), stub in _corpus.POLLS_BY_CHAPTER.items():
            with self.subTest(story=story_slug, chapter=number):
                poll = ChapterPoll.objects.get(chapter__story__slug=story_slug,
                                               chapter__number=number)
                numbers = [c.number
                           for c in _corpus.CHAPTERS_BY_STORY[story_slug]]
                self.assertEqual(poll.closed, any(n > number for n in numbers))

    def test_percentages_come_from_the_votes(self):
        """Процент считается из голосов, а не лежит рядом с ними."""
        for (story_slug, number), stub in _corpus.POLLS_BY_CHAPTER.items():
            with self.subTest(story=story_slug, chapter=number):
                poll = ChapterPoll.objects.get(chapter__story__slug=story_slug,
                                               chapter__number=number)
                votes = dict(stub.votes)
                for row in poll.results:
                    self.assertEqual(row['count'], votes.get(row['slug'], 0))
                # Округление каждой доли по отдельности даёт в сумме 99
                # или 101 — это ожидаемо; проценты не обязаны сходиться в
                # сто, обязаны отвечать своим голосам.
                total = sum(n for _, n in stub.votes) or 1
                for row in poll.results:
                    self.assertEqual(row['percent'],
                                     round(row['count'] * 100 / total))


class SeededNotificationsMatchTheStub(TestCase):

    def test_every_stub_notification_became_a_row(self):
        expected = sum(len(v) for v in _corpus.NOTIFICATIONS_BY_USER.values())
        self.assertEqual(Notification.objects.count(), expected)

    def _pairs(self):
        """Пары «стаб — строка». Сопоставление по тексту события, а не по
        порядку: у одинаковой давности порядок в выдаче произвольный."""
        for username, items in _corpus.NOTIFICATIONS_BY_USER.items():
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
                self.assertEqual(row.days_ago, stub.days_ago)
                self.assertTrue(row.when)
                self.assertEqual(row.bucket,
                                 {0: 'today', 1: 'yesterday'}.get(
                                     stub.days_ago, 'past_week'))

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
                self.assertEqual(row.outcome_label,
                                 data.MODERATION_OUTCOME_LABELS[stub.outcome])


class SeededSchoolLinksMatchTheStub(TestCase):

    def test_links_transferred_in_order(self):
        rows = list(SchoolLink.objects.all())
        self.assertEqual([r.channel for r in rows],
                         [s.channel for s in _corpus.SCHOOL_LINKS])
        self.assertEqual([r.subtitle for r in rows],
                         [s.subtitle for s in _corpus.SCHOOL_LINKS])
