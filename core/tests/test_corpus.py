"""Целостность корпуса в базе.

Инварианты, которые обязаны держаться у демо-содержимого портала: сумма
реакций сходится с главами, объявленное число частей не расходится с
написанным текстом, в подборке не лежит черновик, знаки автора выводятся
из его работ. Ломаются они не от правки кода, а от правки данных — когда
в корпус добавляют произведение или подборку.

Раньше это была целостность `stub_data`: те же проверки на литералах,
которые страницы читали напрямую. Теперь читает база, и проверять надо
её — иначе тест сторожит копию того, что показывают.
"""

from datetime import timedelta

from django.utils import timezone

from core import data
from core.models import Chapter, Story, Tag, User
from core.tests.base import TestCase


class StoriesCarryTheirText(TestCase):
    """Связи автора и жанров сторожит схема (FK), а вот текст — нет.

    Раньше здесь стояли ещё четыре проверки: что автор произведения
    находится, что основной жанр находится, что жанров не больше двух.
    На литералах это были настоящие вопросы — слаг опечатывался, и
    страница падала KeyError. В базе на них отвечает внешний ключ, и
    тест, повторяющий ограничение схемы, проверяет только Django.
    """

    def test_every_chapter_has_text(self):
        """Глава без текста — пустая страница чтения. Записи без тела в
        корпусе быть не может: работа без написанных частей несёт
        `chapters=N` и ни одной главы, а не N пустых."""
        for chapter in Chapter.objects.select_related('story'):
            with self.subTest(story=chapter.story.slug, chapter=chapter.number):
                self.assertTrue(chapter.body)
                self.assertGreater(chapter.char_count, 0)

    def test_single_stories_have_one_loaded_chapter(self):
        for story in Story.objects.all():
            if not story.is_single:
                continue
            with self.subTest(story=story.slug):
                chapters = data.chapters_of(story.slug)
                self.assertEqual(story.chapters, 1)
                self.assertEqual(len(chapters), 1)
                self.assertEqual(chapters[0].number, 1)

    def test_text_chapter_points_at_the_existing_text(self):
        """`Story.text_chapter` — куда ведёт кнопка «Мәтін» (FR-WRITE-05)."""
        for story in Story.objects.all():
            with self.subTest(story=story.slug):
                if story.is_single:
                    self.assertEqual(story.text_chapter, 1)
                else:
                    self.assertIsNone(story.text_chapter)

    def test_text_chapter_is_none_when_no_text_written_yet(self):
        # У свежесозданного `single` главы ещё нет — кнопка обязана вести
        # в новый редактор, а не в несуществующую главу.
        fresh = Story.objects.create(
            slug='brand-new', title='Жаңа',
            author=User.objects.get(username='aidana'),
            primary_genre=data.genre_by_slug('drama'),
            format='single', status='NotPublished')
        self.assertIsNone(fresh.text_chapter)

    def test_public_reading_label_hides_minutes_for_serial(self):
        for story in Story.objects.all():
            with self.subTest(story=story.slug):
                if story.is_single:
                    self.assertIn("минут", story.reading_meta_label)
                else:
                    self.assertNotIn("минут", story.reading_meta_label)
                    self.assertIn("бөлім", story.reading_meta_label)


class CollectionRelations(TestCase):

    def test_collection_covers_resolve_to_stories(self):
        for c in data.all_collections():
            with self.subTest(collection=c.slug):
                covers = c.covers
                self.assertGreater(len(covers), 0,
                    msg=f'У коллекции {c.slug} нет валидных обложек — slug опечатан?')
                for s in covers:
                    self.assertIsInstance(s, Story)

    def test_collections_have_enough_stories_for_quick_pick_grid(self):
        for c in data.all_collections():
            with self.subTest(collection=c.slug):
                self.assertGreaterEqual(len(c.stories), 5)
                self.assertGreaterEqual(c.count, 5)


class BookOfWeekAndProgressResolve(TestCase):

    def test_book_of_week_resolves(self):
        book = data.book_of_week()
        self.assertIsNotNone(book)
        self.assertIsInstance(book.story, Story)

    def test_progress_does_not_run_past_the_last_chapter(self):
        """«Оқуды жалғастыру» ведёт в главу, которая есть."""
        progress = data.reading_progress_of('aidana')
        self.assertIsNotNone(progress)
        self.assertIsInstance(progress.story, Story)
        self.assertLessEqual(progress.current_chapter, progress.story.chapters)


class ContestsAreClassified(TestCase):

    def test_accepting_contests_subset_correct(self):
        for c in data.accepting_contests():
            self.assertEqual(c.phase, 'accepting')
            self.assertIsNotNone(c.days_left, msg='у идущего приёма есть отсчёт')

    def test_hero_contest_accepts_work(self):
        """Баннер главной зовёт «Қатысу» — значит, подавать можно прямо сейчас.
        «Активный» этого не гарантировал: в судействе конкурс тоже активен."""
        self.assertTrue(data.hero_contest().is_accepting)


class SchoolLinksHaveAllRequiredFields(TestCase):

    REQUIRED_CHANNELS = {'youtube', 'instagram', 'tiktok', 'telegram'}

    def test_all_required_channels_present(self):
        present = {l.channel for l in data.school_links()}
        self.assertTrue(self.REQUIRED_CHANNELS.issubset(present))

    def test_every_link_has_url_title_subtitle(self):
        for l in data.school_links():
            with self.subTest(channel=l.channel):
                self.assertTrue(l.url)
                self.assertTrue(l.title)
                self.assertTrue(l.subtitle)


class CollectionsAreEditorialAndSelfConsistent(TestCase):
    """Жинақ — первичный вход в чтение (DEC-31), поэтому цена ошибки в данных
    выше, чем у витринного блока: подборка ведёт в тупик молча."""

    def test_count_is_derived_not_stored(self):
        """Число в UI не может соврать: `count` считается по резолвленным стори."""
        for c in data.all_collections():
            with self.subTest(collection=c.slug):
                self.assertEqual(c.count, len(c.stories))

    def test_collections_are_deep_enough_to_browse(self):
        """Подборка из двух произведений — не навигация, а тупик."""
        for c in data.all_collections():
            with self.subTest(collection=c.slug):
                self.assertGreaterEqual(c.count, 5)

    def test_covers_come_from_the_collection_itself(self):
        """Отдельного cover_slugs нет намеренно: два списка одних и тех же
        слагов рано или поздно разъезжаются."""
        for c in data.all_collections():
            with self.subTest(collection=c.slug):
                self.assertEqual(c.covers, c.stories[:3])

    def test_all_collections_are_editorial(self):
        """Пользовательских подборок на портале нет (DEC-31)."""
        for c in data.all_collections():
            with self.subTest(collection=c.slug):
                self.assertEqual(c.curator, 'редакция')

    def test_collections_of_is_reverse_of_story_slugs(self):
        for c in data.all_collections():
            for story in c.stories:
                with self.subTest(collection=c.slug, story=story.slug):
                    self.assertIn(c, data.collections_of(story))

    def test_every_story_in_a_collection_is_public(self):
        """Черновик в редакционной подборке — утечка ненапечатанного (BR-10)."""
        for c in data.all_collections():
            for story in c.stories:
                with self.subTest(collection=c.slug, story=story.slug):
                    self.assertIn(story.status, data.PUBLIC_STATUSES)


class TrendingTagsShowMovementNotArchive(TestCase):

    def test_only_accepted_tags_with_weekly_activity(self):
        for t in data.trending_tags(10):
            with self.subTest(tag=t.slug):
                self.assertEqual(t.status, 'accepted')
                self.assertGreater(t.weekly_count, 0)

    def test_sorted_by_week_not_by_all_time(self):
        weekly = [t.weekly_count for t in data.trending_tags(10)]
        self.assertEqual(weekly, sorted(weekly, reverse=True))

    def test_week_and_all_time_lists_differ(self):
        """Иначе блок «Осы аптада» — копия «Танымал тегтер» и занимает место зря."""
        self.assertNotEqual(
            [t.slug for t in data.trending_tags(6)],
            [t.slug for t in data.popular_tags(6)],
        )


class RecentViewsAreConsistent(TestCase):
    """Окно в 14 дней — подмножество накопленного (DEC-36).

    `recent_views > views` означало бы, что за две недели прочитали больше,
    чем за всё время. В стабе это опечатка, после Ф14 — сломанный агрегат.
    """

    def test_recent_never_exceeds_total(self):
        for s in Story.objects.all():
            with self.subTest(story=s.slug):
                self.assertLessEqual(s.recent_views, s.views)


class StoryReactionsMatchTheirChapters(TestCase):
    """Итог произведения не расходится с суммой по главам (BR-14, DEC-32).

    Расхождение видно **на экране**, а не только в данных: список глав
    показывает счётчик у каждой главы, шапка — итог, и читатель может
    сложить одно и получить другое. Так и было — «Алыс жағалауларда»
    объявляла 4 821 при 5 230 по главам, «Империя құдіреті» — 3 890
    при 245.

    Это тот же класс, что `Author.works` (DEC-40) и `days_left` (DEC-45):
    хранимое значение рядом с собственным источником. Разница в том, что
    здесь источник **неполон** — у четырёх работ главы не написаны вовсе
    (`DeclaredChapterCountMatchesLoadedChapters.KNOWN_TEXTLESS`), и
    вычислять итог из пустоты значило бы обнулить каталог. Поэтому
    правило условное: сверяем там, где источник есть.

    После Ф14, когда главы будут у всех, `Story.likes` обязан стать
    агрегатом запроса, а этот тест — проверкой самого агрегата.
    """

    def _with_reactions(self):
        for story in Story.objects.all():
            chapters = data.chapters_of(story.slug)
            if any(c.reaction_counts for c in chapters):
                yield story, chapters

    def test_total_equals_the_sum_where_chapters_carry_reactions(self):
        checked = 0
        for story, chapters in self._with_reactions():
            checked += 1
            with self.subTest(story=story.slug):
                self.assertEqual(
                    story.likes, sum(c.likes for c in chapters),
                    'итог в шапке не сходится с числами в списке глав — '
                    'читатель может сложить их сам',
                )
        self.assertTrue(checked, 'ни у одной главы нет реакций — тест ничего не проверяет')

    def test_reaction_slugs_are_from_the_closed_set(self):
        """Словарь реакций закрыт (BR-REACT-01): опечатка в слаге — мёртвая кнопка."""
        for chapter in Chapter.objects.all():
            for slug in chapter.reaction_counts:
                with self.subTest(slug=slug):
                    self.assertIn(slug, data.REACTIONS_BY_SLUG)


class ChapterCountIsDerived(TestCase):
    """«N бөлім» считается по записям глав, а не объявляется колонкой.

    Прежде здесь стоял сторож расхождения: `Story.chapters` была полем, её
    заполнял автор при создании, и `save_chapter` её не обновлял. Тест
    держал список известных лжецов (`KNOWN_TEXTLESS` — четыре сериала,
    обещавших до 19 бөлім без единой написанной главы) и следил, чтобы он
    не рос. Поля больше нет: расходиться нечему, и сторожить нечего —
    осталось проверить, что считается именно написанное.
    """

    def test_count_equals_the_number_of_written_chapters(self):
        for story in Story.objects.all():
            with self.subTest(story=story.slug):
                self.assertEqual(story.chapters, len(data.chapters_of(story.slug)))

    def test_annotated_and_unannotated_agree(self):
        """Аннотация выдачи и одиночный объект обязаны давать одно число:
        иначе карточка каталога и страница произведения расходятся."""
        annotated = {s.slug: s.chapters for s in data.public_stories()}
        for slug, n in annotated.items():
            with self.subTest(story=slug):
                self.assertEqual(n, Story.objects.get(slug=slug).chapters)


class AuthorWorkCountIsDerived(TestCase):
    """`Author.works` считается из данных, а не хранится рядом с ними.

    Литерал врал у всех шести авторов сразу: `rudazov` заявлял 12 работ при
    трёх, `sayyn` — 2 при трёх. Число рендерится в шести местах, включая
    карточку автора на странице произведения и «Жаңа авторлар» на главной.
    """

    def test_matches_the_public_works(self):
        for author in data.all_authors():
            with self.subTest(author=author.username):
                public = [s for s in Story.objects.select_related('author')
                          if s.author.username == author.username and s.is_public]
                self.assertEqual(author.works, len(public))

    def test_drafts_are_not_advertised_publicly(self):
        # BR-10: черновик публично не виден, значит и в публичный счётчик
        # попадать не должен — иначе число выдаёт факт неопубликованного
        hidden = [s for s in data.my_stories_of('aidana') if not s.is_public]
        self.assertTrue(hidden, 'у демо-автора не осталось непубличных работ')
        self.assertEqual(
            data.author_by_username('aidana').works,
            len(data.my_stories_of('aidana')) - len(hidden),
        )


class UpdatedLabelReadsAsTime(TestCase):
    """Подпись «когда трогали» — единственная опора для «что я делал последним»."""

    def test_scale(self):
        """Подпись выводится из `updated_at`, а не хранится числом дней.

        Состояния «не задано» у неё больше нет: у строки в базе времени
        изменения не может не быть, и ветка, рисовавшая пустоту, ушла
        вместе со стабом.
        """
        cases = {0: "бүгін", 1: "кеше", 3: "3 күн бұрын",
                 7: "1 апта бұрын", 20: "2 апта бұрын", 45: "1 ай бұрын"}
        for days, expected in cases.items():
            with self.subTest(days=days):
                story = Story(updated_at=timezone.now() - timedelta(days=days))
                self.assertEqual(story.updated_label, expected)

    def test_every_story_says_when_it_was_touched(self):
        for story in Story.objects.all():
            with self.subTest(story=story.slug):
                self.assertTrue(story.updated_label)


class WriterAttentionOnlySpeaksWhenThereIsSomething(TestCase):

    def test_aidana_has_all_three_signals(self):
        kinds = [i["kind"] for i in data.writer_attention("aidana")]
        self.assertEqual(kinds, ["moderation", "comments", "draft"])

    def test_unknown_user_is_silent(self):
        self.assertEqual(data.writer_attention("no-such-user"), [])

    def test_slug_is_set_only_for_a_single_item(self):
        for item in data.writer_attention("aidana"):
            with self.subTest(kind=item["kind"]):
                if item["count"] > 1 or item["kind"] == "comments":
                    self.assertEqual(item["slug"], "")
                else:
                    self.assertIsNotNone(data.story_by_slug(item["slug"]))


# ───────────────────────── PROF · достижения (FR-PROF-06) ─────────────────

class ReadTiers(TestCase):
    """Ступени прочтений: границы и «только высшая»."""

    def test_boundaries(self):
        cases = [
            (0,       None),
            (999,     None),
            (1_000,   "Мың оқылым"),
            (9_999,   "Мың оқылым"),
            (10_000,  "Он мың оқылым"),
            (49_999,  "Он мың оқылым"),
            (50_000,  "Елу мың оқылым"),
            (99_999,  "Елу мың оқылым"),
            (100_000, "Жүз мың оқылым"),
            (999_999, "Жүз мың оқылым"),
        ]
        for total, expected in cases:
            with self.subTest(total=total):
                tier = data.tier_for(total)
                self.assertEqual(tier[1] if tier else None, expected)

    def test_next_tier(self):
        self.assertEqual(data.next_tier_for(0)[0], 1_000)
        self.assertEqual(data.next_tier_for(2_117)[0], 10_000)
        self.assertEqual(data.next_tier_for(60_342)[0], 100_000)
        self.assertIsNone(data.next_tier_for(100_000))

    def test_tiers_are_ascending(self):
        thresholds = [t[0] for t in data.READ_TIERS]
        self.assertEqual(thresholds, sorted(thresholds))
        self.assertEqual(len(thresholds), len(set(thresholds)))

    def test_reads_total_counts_public_only(self):
        # BR-73: прочтения приходят от читателей, читатель видит публичное.
        for a in data.all_authors():
            with self.subTest(author=a.username):
                self.assertEqual(
                    data.reads_total(a.username),
                    sum(s.views for s in data.public_stories_of(a.username)),
                )

    def test_unknown_user_has_no_tier(self):
        self.assertEqual(data.reads_total("ghost"), 0)
        self.assertIsNone(data.read_tier("ghost"))


class Achievements(TestCase):
    """Знаки выводятся из данных, не хранятся (DEC-41)."""


    def _all(self):
        return [(a.username, ach)
                for a in data.all_authors()
                for ach in data.achievements_of(a.username)]

    def test_unknown_user_gets_nothing(self):
        self.assertEqual(data.achievements_of("ghost"), [])

    def test_keys_unique_per_author(self):
        for a in data.all_authors():
            keys = [x["key"] for x in data.achievements_of(a.username)]
            with self.subTest(author=a.username):
                self.assertEqual(len(keys), len(set(keys)))

    def test_only_highest_read_tier_is_shown(self):
        for a in data.all_authors():
            reads = [x for x in data.achievements_of(a.username)
                     if x["key"] == "reads"]
            with self.subTest(author=a.username):
                self.assertLessEqual(len(reads), 1)
                if reads:
                    self.assertEqual(reads[0]["label"],
                                     data.read_tier(a.username)[1])

    def test_shape_is_complete(self):
        for username, ach in self._all():
            with self.subTest(author=username, key=ach.get("key")):
                self.assertEqual(set(ach), {"key", "label", "art", "tier"})
                self.assertTrue(ach["label"])
                self.assertTrue(ach["art"])
                self.assertIn(ach["tier"], data.AWARD_TIERS)

    def test_gold_stays_rare(self):
        """Металл — сигнал ценности. Позолотить всё значит обесценить золото."""
        gold = {ach["key"] for _, ach in self._all() if ach["tier"] == "gold"}
        # Верхнюю ступень оқылым в стабе пока не взял никто, поэтому
        # включение, а не равенство: тест про «золота не больше», а не про
        # конкретный состав фикстуры.
        # «Байқау жеңімпазы» из системного реестра убран (DEC-46): победу
        # называет награда конкретного конкурса, и металла у неё нет.
        self.assertTrue(gold <= {"editorial_choice", "reads"}, gold)
        self.assertIn("editorial_choice", gold)
        # У «reads» золото положено только верхней ступени.
        golden_reads = {ach["label"] for _, ach in self._all()
                        if ach["key"] == "reads" and ach["tier"] == "gold"}
        self.assertTrue(golden_reads <= {"Жүз мың оқылым"})
        self.assertEqual(data.READ_TIER_ART[100_000][1], "gold")
        self.assertEqual(data.READ_TIER_ART[1_000][1], "bronze")

    def test_read_tier_art_covers_every_tier(self):
        thresholds = {t[0] for t in data.READ_TIERS}
        self.assertEqual(set(data.READ_TIER_ART), thresholds)
        for art, metal in data.READ_TIER_ART.values():
            with self.subTest(art=art):
                self.assertIn(metal, data.AWARD_TIERS)

    def test_art_slugs_are_unique_per_author(self):
        for a in data.all_authors():
            arts = [x["art"] for x in data.achievements_of(a.username)]
            with self.subTest(author=a.username):
                self.assertEqual(len(arts), len(set(arts)))

    def test_finished_serial_needs_a_serial(self):
        # У aygerim_k три опубликованных одиночных рассказа и ни одного
        # дописанного сериала: одиночный «дописан» в момент публикации.
        keys = {x["key"] for x in data.achievements_of("aygerim_k")}
        self.assertNotIn("finished_serial", keys)
        self.assertTrue(any(s.is_single for s in data.my_stories_of("aygerim_k")))

    def test_winner_implies_participant_and_accepted(self):
        """Награда конкурса не берётся без заявки, прошедшей жюри (DEC-46)."""
        for a in data.all_authors():
            keys = {x["key"] for x in data.achievements_of(a.username)}
            with self.subTest(author=a.username):
                if data.contest_awards_of(a.username):
                    self.assertIn("contest_participant", keys)
                    self.assertIn("contest_accepted", keys)

    def test_editorial_badge_comes_from_public_work(self):
        label = data.BADGE_LABELS["editorial"]
        for a in data.all_authors():
            keys = {x["key"] for x in data.achievements_of(a.username)}
            has_public = any(label in s.badges
                             for s in data.public_stories_of(a.username))
            with self.subTest(author=a.username):
                self.assertEqual("editorial_choice" in keys, has_public)

    def test_award_belongs_to_the_author_it_is_shown_under(self):
        """Награда конкурса приходит через работу (DEC-46), и работа обязана
        быть авторской: второе имя разошлось бы с первым."""
        for a in data.all_authors():
            for item in data.contest_awards_of(a.username):
                story = item['story']
                if story is None:      # снята с публикации — не называется (BR-73)
                    continue
                with self.subTest(author=a.username, story=story.slug):
                    self.assertEqual(story.author.username, a.username)
