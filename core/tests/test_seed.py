"""`seed_demo` — механизм, который переносит демо-корпус между машинами.

До Ф14 корпус лежал литералами в git и переносился сам. После — переносит
его эта команда, и проверять её надо по трём свойствам.

**Идемпотентность.** Команду запускают на пустой базе, поверх засеянной и
после смены схемы. Второй запуск обязан не удваивать корпус и приводить
изменённые записи обратно к эталону — иначе «засеять ещё раз» перестаёт
быть безопасным действием, и им перестают пользоваться.

**Полнота.** Ни одна запись корпуса не должна потеряться по дороге. Это
одна проверка на все таблицы (`SeededCorpusHasEveryRow`), а не по тесту
на таблицу.

**Выводимое выводится.** Команда — перевод, и по дороге кое-что меняет
форму: дни назад становятся датами, текст главы — объёмом, вложенный
комментарий — ссылкой на родителя. Проверяются **ответы**: подпись
давности, фаза конкурса, процент в опросе, бакет объёма.

Чего здесь **больше нет** — построчной сверки колонок со стабом
(`assertEqual(story.title, stub.title)` и так по каждому полю каждой
таблицы). Это была приёмка перехода на модели: в день переключения
каталога на базу расхождение стало бы сменой выдачи, которую никто не
заказывал. Переход состоялся, приёмка пройдена, а обязанность править
файл при каждой правке корпуса осталась бы навсегда — при том что ловить
такой тест мог только ошибку в прямом присваивании внутри `seed_demo`.

`_corpus` здесь импортируется прямо, в обход фасада, и это второй и
последний модуль, которому так можно: перевод проверяют, сверяя обе
стороны.
"""

from django.core.management import call_command
from django.db.utils import IntegrityError
from django.test import TestCase
from django.utils import timezone

from core import data
from core.management.commands import _corpus
from core.templatetags.balaproza import ago, outcome_label, since
from core.models import (
    AwardGrant,
    Chapter,
    ChapterPoll,
    Collection,
    Contest,
    Follow,
    Genre,
    LibraryEntry,
    Notification,
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


class SeededUsersHaveNoWayIn(TestCase):

    def test_demo_users_have_no_usable_password(self):
        """Настоящего логина до этапа 9 нет. Пустой пароль означал бы «вход
        без пароля», а не «входа нет»."""
        for user in User.objects.all():
            with self.subTest(user=user.username):
                self.assertFalse(user.has_usable_password())


class SeededTagsRespectTheirStatus(TestCase):

    def test_pending_tags_are_not_public(self):
        pending = [t.slug for t in _corpus.TAGS if t.status == 'pending']
        self.assertTrue(pending, 'в стабе нет pending-тега — проверять нечего')
        for slug in pending:
            with self.subTest(tag=slug):
                self.assertFalse(Tag.objects.get(slug=slug).is_public)


class SeededStoriesDeriveWhatIsDerived(TestCase):
    """Из колонок работы считается то, что решает её судьбу в выдаче.

    Бакет объёма и время чтения решают, в какой фильтр работа попадёт;
    знак каталога у одного из двух видов выводится, а не хранится.
    """

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


class SeededChapterReactionsAddUp(TestCase):

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


class SeededContestsDeriveTheirPhase(TestCase):
    """Конкурс — самый производный объект проекта: из трёх дат считается
    почти всё, что видит участник. Проверяются поэтому не колонки, а
    ответы: фаза, состояние этапа, число заявок, победители.
    """

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


class SeededSubmissionsSitInsideTheirWindow(TestCase):

    def test_relative_label_is_derived(self):
        """«5 күн бұрын» считается от даты. Хранимая строка не просто
        устаревала — она лгала проверяемо (BR-41a)."""
        for username, subs in _corpus.SUBMISSIONS_BY_USER.items():
            for stub in subs:
                with self.subTest(author=username, contest=stub.contest_slug):
                    row = Submission.objects.get(author__username=username,
                                                 contest__slug=stub.contest_slug)
                    self.assertEqual(row.submitted_on, stub.submitted_on)
                    self.assertTrue(ago(row.submitted_on))

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


class SeededSocialGraphStaysValid(TestCase):

    def test_nobody_follows_themselves(self):
        me = User.objects.get(username='aidana')
        with self.assertRaises(IntegrityError):
            Follow.objects.create(follower=me, following=me)


class SeededCollectionsCountThemselves(TestCase):

    def test_count_is_counted(self):
        """`count` — длина состава, а не колонка рядом с ним."""
        for stub in _corpus.COLLECTIONS:
            with self.subTest(collection=stub.slug):
                self.assertEqual(Collection.objects.get(slug=stub.slug).count,
                                 len(stub.story_slugs))


class SeededShelvesDoNotOverlap(TestCase):

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
                    self.assertTrue(since(row.added_on))

    def test_a_story_lies_in_exactly_one_shelf(self):
        """Три вида не пересекаются (BR-60/61): иначе «Оқуды жалғастыру»
        предложит то, что читатель уже закрыл."""
        row = LibraryEntry.objects.first()
        with self.assertRaises(IntegrityError):
            LibraryEntry.objects.create(user=row.user, story=row.story,
                                        kind='done')


class SeededCommentsStayOneLevelDeep(TestCase):

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
        self.assertIn('бұрын', ago(fresh.created_at))
        self.assertNotIn('апта', ago(fresh.created_at))


class SeededPollsDeriveTheirResults(TestCase):

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


class SeededNotificationsDeriveTheirTime(TestCase):

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
                self.assertTrue(ago(row.created_at))
                self.assertEqual(row.bucket,
                                 {0: 'today', 1: 'yesterday'}.get(
                                     stub.days_ago, 'past_week'))

    def test_moderation_outcome_is_stored_with_its_label(self):
        """Исход — акт модератора (BR-72b): из `Story.status` он не
        выводится, потому что статус живёт дальше события."""
        for username, stub, row in self._pairs():
            with self.subTest(user=username, kind=stub.kind):
                self.assertEqual(row.outcome, stub.outcome)
                self.assertEqual(outcome_label(row),
                                 data.MODERATION_OUTCOME_LABELS[stub.outcome])


class SeededCorpusHasEveryRow(TestCase):
    """Ни одна запись корпуса не потерялась по дороге в базу.

    Одна проверка на все таблицы вместо восьми `test_every_stub_X_became_
    a_row`. Числа — единственное, что стоило сверять построчно: содержимое
    колонок команда переносит присваиванием, и тест на него проверял, что
    присваивание присваивает.
    """

    def test_row_counts_match_the_corpus(self):
        flat = lambda d: sum(len(v) for v in d.values())
        expected = {
            User:         len(_corpus.AUTHORS),
            Tag:          len(_corpus.TAGS),
            Story:        len(_corpus.STORIES),
            Chapter:      flat(_corpus.CHAPTERS_BY_STORY),
            Contest:      len(_corpus.CONTESTS),
            AwardGrant:   len(_corpus.AWARD_GRANTS),
            Submission:   flat(_corpus.SUBMISSIONS_BY_USER),
            Collection:   len(_corpus.COLLECTIONS),
            SchoolLink:   len(_corpus.SCHOOL_LINKS),
            LibraryEntry: flat(_corpus.LIBRARY_BY_USER),
            Follow:       flat(_corpus.FOLLOWING),
            Notification: flat(_corpus.NOTIFICATIONS_BY_USER),
            ChapterPoll:  len(_corpus.POLLS_BY_CHAPTER),
        }
        for model, n in expected.items():
            with self.subTest(model=model.__name__):
                self.assertEqual(model.objects.count(), n)


class SeededCorpusHoldsItsInvariants(TestCase):
    """Целостность демо-содержимого — то, что ломается от правки данных,
    а не кода.

    Раньше это был отдельный файл на 55 тестов. Половина его проверяла
    правила (ступени наград, вывод счётчиков, подписи времени) и переехала
    туда, где эти правила живут; здесь осталось то, что действительно про
    корпус: он должен быть пригоден к показу.
    """

    def test_every_chapter_carries_text(self):
        """Глава без тела — пустая страница чтения. Работа без написанных
        частей не несёт ни одной главы, а не N пустых."""
        for chapter in Chapter.objects.select_related('story'):
            with self.subTest(story=chapter.story.slug, chapter=chapter.number):
                self.assertTrue(chapter.body)
                self.assertGreater(chapter.char_count, 0)

    def test_single_works_carry_exactly_one_chapter(self):
        for story in Story.objects.filter(format='single'):
            with self.subTest(story=story.slug):
                self.assertEqual(story.chapters, 1)

    def test_recent_views_never_exceed_the_total(self):
        """Окно в 14 дней — подмножество накопленного (DEC-36). Обратное
        означало бы, что за две недели прочитали больше, чем за всё время."""
        for story in Story.objects.all():
            with self.subTest(story=story.slug):
                self.assertLessEqual(story.recent_views, story.views)

    def test_collections_are_deep_enough_and_public(self):
        """Жинақ — первичный вход в чтение (DEC-31): подборка из двух
        работ это тупик, а черновик в ней — утечка ненапечатанного."""
        for collection in data.all_collections():
            with self.subTest(collection=collection.slug):
                self.assertGreaterEqual(collection.count, 5)
                self.assertEqual(collection.count, len(collection.stories))
                self.assertEqual(collection.covers, collection.stories[:3])
                self.assertEqual(collection.curator, 'редакция')
                for story in collection.stories:
                    self.assertIn(story.status, data.PUBLIC_STATUSES)

    def test_the_showcases_resolve(self):
        """Книга недели, баннер конкурса и ссылки школы — то, что видит
        гость в первом фолде. Пустой любой из них — дыра на главной."""
        self.assertIsInstance(data.book_of_week().story, Story)
        self.assertTrue(data.hero_contest().is_accepting)
        channels = {link.channel for link in data.school_links()}
        self.assertTrue({'youtube', 'instagram', 'tiktok', 'telegram'} <= channels)
        for link in data.school_links():
            with self.subTest(channel=link.channel):
                self.assertTrue(link.url and link.title and link.subtitle)

    def test_a_work_is_never_older_than_its_author(self):
        """Дата создания и приход автора расходились молча: `auto_now_add`
        ставил всем работам момент запуска сида, и год в шапке профиля
        («2025 жылдан бері») жил отдельно от того, что этот автор написал."""
        for story in Story.objects.select_related('author'):
            with self.subTest(story=story.slug):
                self.assertGreaterEqual(story.created_at, story.author.date_joined)
                self.assertGreaterEqual(story.updated_at, story.created_at)

    def test_the_axes_of_the_catalog_show_different_orders(self):
        """Три оси — три вопроса, и ответы обязаны различаться.

        Пока все работы создавались в момент запуска сида, «Жаңалары»
        давала случайный порядок; пока окно не убывало, «Қазір танымал»
        сходилась с «Ең көп оқылған». Обе оси существовали, но ничего не
        сообщали.
        """
        newest = [s.slug for s in Story.objects.order_by('-created_at')[:5]]
        recent = [s.slug for s in Story.objects.order_by('-recent_views')[:5]]
        alltime = [s.slug for s in Story.objects.order_by('-views')[:5]]
        self.assertNotEqual(newest, recent)
        self.assertNotEqual(recent, alltime)
        self.assertNotEqual(newest, alltime)

    def test_the_two_tag_showcases_do_not_coincide(self):
        """Иначе «Осы аптада» — копия «Танымал тегтер» и занимает место зря
        (DEC-31). Держится это на разбросе дат правок в корпусе: сид
        датирует связку последней правкой работы."""
        self.assertNotEqual(
            [t.slug for t in data.trending_tags(6)],
            [t.slug for t in data.popular_tags(6)],
        )
