"""Целостность stub_data.

Эти инварианты должны держаться, чтобы шаблоны не падали с KeyError при
рендере: story.author, story.primary_genre, collection.covers и т.п.
Когда добавляются новые произведения/коллекции, эти тесты ловят опечатки.
"""

import unittest

from core import stub_data


class IndexesAreConsistent(unittest.TestCase):

    def test_genres_by_slug_covers_all(self):
        self.assertEqual(len(stub_data.GENRES_BY_SLUG), len(stub_data.GENRES))
        for g in stub_data.GENRES:
            self.assertIn(g.slug, stub_data.GENRES_BY_SLUG)

    def test_authors_by_username_covers_all(self):
        self.assertEqual(len(stub_data.AUTHORS_BY_USERNAME), len(stub_data.AUTHORS))
        for a in stub_data.AUTHORS:
            self.assertIn(a.username, stub_data.AUTHORS_BY_USERNAME)
            self.assertTrue(a.public_name)

    def test_stories_by_slug_covers_all(self):
        self.assertEqual(len(stub_data.STORIES_BY_SLUG), len(stub_data.STORIES))


class StoryRelations(unittest.TestCase):

    def test_every_story_has_resolvable_author(self):
        for s in stub_data.STORIES:
            with self.subTest(story=s.slug):
                # должно отдать Author без KeyError
                self.assertIsNotNone(s.author)
                self.assertEqual(s.author.username, s.author_username)

    def test_every_story_has_resolvable_primary_genre(self):
        for s in stub_data.STORIES:
            with self.subTest(story=s.slug):
                self.assertIsNotNone(s.primary_genre)
                self.assertEqual(s.primary_genre.slug, s.genres[0])

    def test_genres_resolved_skips_none_and_unknown(self):
        for s in stub_data.STORIES:
            with self.subTest(story=s.slug):
                resolved = s.genres_resolved
                # Каждый элемент — реальный Genre
                self.assertTrue(all(isinstance(g, stub_data.Genre) for g in resolved))
                # None из tuple отфильтрован
                self.assertTrue(all(g is not None for g in resolved))

    def test_genres_field_has_at_most_two_slots(self):
        """BR-12: основной + до одного дополнительного."""
        for s in stub_data.STORIES:
            with self.subTest(story=s.slug):
                self.assertLessEqual(len(s.genres), 2)

    def test_stub_chapters_have_loaded_body_text(self):
        for slug, chapters in stub_data.CHAPTERS_BY_STORY.items():
            for chapter in chapters:
                with self.subTest(story=slug, chapter=chapter.number):
                    self.assertTrue(chapter.body)
                    self.assertGreater(chapter.char_count, 0)

    def test_single_stories_have_one_loaded_chapter(self):
        for story in stub_data.STORIES:
            if not story.is_single:
                continue
            with self.subTest(story=story.slug):
                chapters = stub_data.chapters_of(story.slug)
                self.assertEqual(story.chapters, 1)
                self.assertEqual(len(chapters), 1)
                self.assertEqual(chapters[0].number, 1)

    def test_text_chapter_points_at_the_existing_text(self):
        """`Story.text_chapter` — куда ведёт кнопка «Мәтін» (FR-WRITE-05)."""
        for story in stub_data.STORIES:
            with self.subTest(story=story.slug):
                if story.is_single:
                    self.assertEqual(story.text_chapter, 1)
                else:
                    self.assertIsNone(story.text_chapter)

    def test_text_chapter_is_none_when_no_text_written_yet(self):
        # У свежесозданного `single` главы ещё нет — кнопка обязана вести
        # в новый редактор, а не в несуществующую главу.
        fresh = stub_data.Story(
            slug="brand-new", title="Жаңа", author_username="aidana",
            cover="", genres=("drama", None),
            chapters=0, views=0, likes=0, comments=0, format="single",
        )
        self.assertIsNone(fresh.text_chapter)

    def test_public_reading_label_hides_minutes_for_serial(self):
        for story in stub_data.STORIES:
            with self.subTest(story=story.slug):
                if story.is_single:
                    self.assertIn("минут", story.reading_meta_label)
                else:
                    self.assertNotIn("минут", story.reading_meta_label)
                    self.assertIn("бөлім", story.reading_meta_label)


class CollectionRelations(unittest.TestCase):

    def test_collection_covers_resolve_to_stories(self):
        for c in stub_data.COLLECTIONS:
            with self.subTest(collection=c.slug):
                covers = c.covers
                self.assertGreater(len(covers), 0,
                    msg=f'У коллекции {c.slug} нет валидных обложек — slug опечатан?')
                for s in covers:
                    self.assertIsInstance(s, stub_data.Story)

    def test_collections_have_enough_stories_for_quick_pick_grid(self):
        for c in stub_data.COLLECTIONS:
            with self.subTest(collection=c.slug):
                self.assertGreaterEqual(len(c.stories), 5)
                self.assertGreaterEqual(c.count, 5)


class BookOfWeekAndProgressResolve(unittest.TestCase):

    def test_book_of_week_resolves(self):
        story = stub_data.BOOK_OF_WEEK.story
        self.assertIsInstance(story, stub_data.Story)

    def test_sample_progress_resolves(self):
        story = stub_data.SAMPLE_PROGRESS.story
        self.assertIsInstance(story, stub_data.Story)
        # Прогресс не должен быть «прочитано больше, чем глав»
        self.assertLessEqual(
            stub_data.SAMPLE_PROGRESS.current_chapter, story.chapters,
        )


class ContestsAreClassified(unittest.TestCase):

    def test_accepting_contests_subset_correct(self):
        for c in stub_data.ACCEPTING_CONTESTS:
            self.assertEqual(c.phase, 'accepting')
            self.assertIsNotNone(c.days_left, msg='у идущего приёма есть отсчёт')

    def test_hero_contest_accepts_work(self):
        """Баннер главной зовёт «Қатысу» — значит, подавать можно прямо сейчас.
        «Активный» этого не гарантировал: в судействе конкурс тоже активен."""
        self.assertTrue(stub_data.HERO_CONTEST.is_accepting)


class SchoolLinksHaveAllRequiredFields(unittest.TestCase):

    REQUIRED_CHANNELS = {'youtube', 'instagram', 'tiktok', 'telegram'}

    def test_all_required_channels_present(self):
        present = {l.channel for l in stub_data.SCHOOL_LINKS}
        self.assertTrue(self.REQUIRED_CHANNELS.issubset(present))

    def test_every_link_has_url_title_subtitle(self):
        for l in stub_data.SCHOOL_LINKS:
            with self.subTest(channel=l.channel):
                self.assertTrue(l.url)
                self.assertTrue(l.title)
                self.assertTrue(l.subtitle)


class CollectionsAreEditorialAndSelfConsistent(unittest.TestCase):
    """Жинақ — первичный вход в чтение (DEC-31), поэтому цена ошибки в данных
    выше, чем у витринного блока: подборка ведёт в тупик молча."""

    def test_count_is_derived_not_stored(self):
        """Число в UI не может соврать: `count` считается по резолвленным стори."""
        for c in stub_data.COLLECTIONS:
            with self.subTest(collection=c.slug):
                self.assertEqual(c.count, len(c.stories))

    def test_every_slug_resolves(self):
        """Битый slug раньше молча уменьшал подборку — теперь ловим здесь."""
        for c in stub_data.COLLECTIONS:
            for slug in c.story_slugs:
                with self.subTest(collection=c.slug, story=slug):
                    self.assertIn(slug, stub_data.STORIES_BY_SLUG)

    def test_collections_are_deep_enough_to_browse(self):
        """Подборка из двух произведений — не навигация, а тупик."""
        for c in stub_data.COLLECTIONS:
            with self.subTest(collection=c.slug):
                self.assertGreaterEqual(c.count, 5)

    def test_covers_come_from_the_collection_itself(self):
        """Отдельного cover_slugs нет намеренно: два списка одних и тех же
        слагов рано или поздно разъезжаются."""
        for c in stub_data.COLLECTIONS:
            with self.subTest(collection=c.slug):
                self.assertEqual(c.covers, c.stories[:3])

    def test_all_collections_are_editorial(self):
        """Пользовательских подборок на портале нет (DEC-31)."""
        for c in stub_data.COLLECTIONS:
            with self.subTest(collection=c.slug):
                self.assertEqual(c.curator, 'редакция')

    def test_collections_of_is_reverse_of_story_slugs(self):
        for c in stub_data.COLLECTIONS:
            for story in c.stories:
                with self.subTest(collection=c.slug, story=story.slug):
                    self.assertIn(c, stub_data.collections_of(story))

    def test_every_story_in_a_collection_is_public(self):
        """Черновик в редакционной подборке — утечка ненапечатанного (BR-10)."""
        for c in stub_data.COLLECTIONS:
            for story in c.stories:
                with self.subTest(collection=c.slug, story=story.slug):
                    self.assertIn(story.status, stub_data.PUBLIC_STATUSES)


class TrendingTagsShowMovementNotArchive(unittest.TestCase):

    def test_only_accepted_tags_with_weekly_activity(self):
        for t in stub_data.trending_tags(10):
            with self.subTest(tag=t.slug):
                self.assertEqual(t.status, 'accepted')
                self.assertGreater(t.weekly_count, 0)

    def test_sorted_by_week_not_by_all_time(self):
        weekly = [t.weekly_count for t in stub_data.trending_tags(10)]
        self.assertEqual(weekly, sorted(weekly, reverse=True))

    def test_week_and_all_time_lists_differ(self):
        """Иначе блок «Осы аптада» — копия «Танымал тегтер» и занимает место зря."""
        self.assertNotEqual(
            [t.slug for t in stub_data.trending_tags(6)],
            [t.slug for t in stub_data.popular_tags(6)],
        )


class RecentViewsAreConsistent(unittest.TestCase):
    """Окно в 14 дней — подмножество накопленного (DEC-36).

    `recent_views > views` означало бы, что за две недели прочитали больше,
    чем за всё время. В стабе это опечатка, после Ф14 — сломанный агрегат.
    """

    def test_recent_never_exceeds_total(self):
        for s in stub_data.STORIES:
            with self.subTest(story=s.slug):
                self.assertLessEqual(s.recent_views, s.views)


class StoryReactionsMatchTheirChapters(unittest.TestCase):
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
        for story in stub_data.STORIES:
            chapters = stub_data.chapters_of(story.slug)
            if any(c.reactions for c in chapters):
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
        for chapters in stub_data.CHAPTERS_BY_STORY.values():
            for c in chapters:
                for slug, _ in c.reactions:
                    with self.subTest(slug=slug):
                        self.assertIn(slug, stub_data.REACTIONS_BY_SLUG)


class DeclaredChapterCountMatchesLoadedChapters(unittest.TestCase):
    """`Story.chapters` не должен обещать больше, чем стаб умеет показать.

    `aidana-erteg` объявляла 3 бөлім без единой записи в `CHAPTERS_BY_STORY`:
    список «Менің шығармаларым» показывал «3 бөлім», а «Басқару» открывалась
    пустой. Записи главы обязаны нести текст (см.
    `test_stub_chapters_have_loaded_body_text`), поэтому честное значение там —
    ноль, а не три пустые главы.
    """

    # Каталожные сериалы, у которых текст глав не написан вовсе. В авторском
    # кабинете их никто не открывает, но публичная страница произведения
    # обещает бөлім, которых нет. Гэп известен и ждёт наполнения story_texts/;
    # список заморожен, чтобы к нему не добавилось новых произведений.
    KNOWN_TEXTLESS = {
        "zhuldyz-kartasy", "kokjal-anyzy", "keiipkerge-hat", "arqadagy-jaz",
    }

    def test_counts_match_wherever_text_is_authored(self):
        for story in stub_data.STORIES:
            if story.slug in self.KNOWN_TEXTLESS:
                continue
            with self.subTest(story=story.slug):
                self.assertEqual(story.chapters, len(stub_data.chapters_of(story.slug)))

    def test_the_list_of_textless_stories_has_not_grown(self):
        textless = {
            s.slug for s in stub_data.STORIES
            if s.chapters and not stub_data.chapters_of(s.slug)
        }
        self.assertEqual(
            textless, self.KNOWN_TEXTLESS,
            "Произведение обещает бөлім, которых нет в CHAPTERS_BY_STORY. "
            "Либо напиши текст в core/story_texts/, либо поставь chapters=0.",
        )


class AuthorWorkCountIsDerived(unittest.TestCase):
    """`Author.works` считается из данных, а не хранится рядом с ними.

    Литерал врал у всех шести авторов сразу: `rudazov` заявлял 12 работ при
    трёх, `sayyn` — 2 при трёх. Число рендерится в шести местах, включая
    карточку автора на странице произведения и «Жаңа авторлар» на главной.
    """

    def test_matches_the_public_works(self):
        for author in stub_data.AUTHORS:
            with self.subTest(author=author.username):
                public = [s for s in stub_data.STORIES
                          if s.author_username == author.username and s.is_public]
                self.assertEqual(author.works, len(public))

    def test_drafts_are_not_advertised_publicly(self):
        # BR-10: черновик публично не виден, значит и в публичный счётчик
        # попадать не должен — иначе число выдаёт факт неопубликованного
        hidden = [s for s in stub_data.my_stories_of('aidana') if not s.is_public]
        self.assertTrue(hidden, 'у демо-автора не осталось непубличных работ')
        self.assertEqual(
            stub_data.AUTHORS_BY_USERNAME['aidana'].works,
            len(stub_data.my_stories_of('aidana')) - len(hidden),
        )


class UpdatedLabelReadsAsTime(unittest.TestCase):
    """Подпись «когда трогали» — единственная опора для «что я делал последним»."""

    def test_scale(self):
        cases = {0: "бүгін", 1: "кеше", 3: "3 күн бұрын",
                 7: "1 апта бұрын", 20: "2 апта бұрын", 45: "1 ай бұрын"}
        for days, expected in cases.items():
            with self.subTest(days=days):
                story = stub_data.Story(
                    slug="x", title="X", author_username="aidana", cover="",
                    genres=("drama", None), chapters=0, views=0, likes=0,
                    comments=0, updated_days_ago=days)
                self.assertEqual(story.updated_label, expected)

    def test_unset_renders_nothing(self):
        story = stub_data.Story(
            slug="x", title="X", author_username="aidana", cover="",
            genres=("drama", None), chapters=0, views=0, likes=0, comments=0)
        self.assertEqual(story.updated_label, "")


class WriterAttentionOnlySpeaksWhenThereIsSomething(unittest.TestCase):

    def test_aidana_has_all_three_signals(self):
        kinds = [i["kind"] for i in stub_data.writer_attention("aidana")]
        self.assertEqual(kinds, ["moderation", "comments", "draft"])

    def test_unknown_user_is_silent(self):
        self.assertEqual(stub_data.writer_attention("no-such-user"), [])

    def test_slug_is_set_only_for_a_single_item(self):
        for item in stub_data.writer_attention("aidana"):
            with self.subTest(kind=item["kind"]):
                if item["count"] > 1 or item["kind"] == "comments":
                    self.assertEqual(item["slug"], "")
                else:
                    self.assertIn(item["slug"], stub_data.STORIES_BY_SLUG)


# ───────────────────────── PROF · достижения (FR-PROF-06) ─────────────────

class ReadTiers(unittest.TestCase):
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
                tier = stub_data.tier_for(total)
                self.assertEqual(tier[1] if tier else None, expected)

    def test_next_tier(self):
        self.assertEqual(stub_data.next_tier_for(0)[0], 1_000)
        self.assertEqual(stub_data.next_tier_for(2_117)[0], 10_000)
        self.assertEqual(stub_data.next_tier_for(60_342)[0], 100_000)
        self.assertIsNone(stub_data.next_tier_for(100_000))

    def test_tiers_are_ascending(self):
        thresholds = [t[0] for t in stub_data.READ_TIERS]
        self.assertEqual(thresholds, sorted(thresholds))
        self.assertEqual(len(thresholds), len(set(thresholds)))

    def test_reads_total_counts_public_only(self):
        # BR-73: прочтения приходят от читателей, читатель видит публичное.
        for a in stub_data.AUTHORS:
            with self.subTest(author=a.username):
                self.assertEqual(
                    stub_data.reads_total(a.username),
                    sum(s.views for s in stub_data.public_stories_of(a.username)),
                )

    def test_unknown_user_has_no_tier(self):
        self.assertEqual(stub_data.reads_total("ghost"), 0)
        self.assertIsNone(stub_data.read_tier("ghost"))


class Achievements(unittest.TestCase):
    """Знаки выводятся из данных, не хранятся (DEC-41)."""


    def _all(self):
        return [(a.username, ach)
                for a in stub_data.AUTHORS
                for ach in stub_data.achievements_of(a.username)]

    def test_unknown_user_gets_nothing(self):
        self.assertEqual(stub_data.achievements_of("ghost"), [])

    def test_keys_unique_per_author(self):
        for a in stub_data.AUTHORS:
            keys = [x["key"] for x in stub_data.achievements_of(a.username)]
            with self.subTest(author=a.username):
                self.assertEqual(len(keys), len(set(keys)))

    def test_only_highest_read_tier_is_shown(self):
        for a in stub_data.AUTHORS:
            reads = [x for x in stub_data.achievements_of(a.username)
                     if x["key"] == "reads"]
            with self.subTest(author=a.username):
                self.assertLessEqual(len(reads), 1)
                if reads:
                    self.assertEqual(reads[0]["label"],
                                     stub_data.read_tier(a.username)[1])

    def test_shape_is_complete(self):
        for username, ach in self._all():
            with self.subTest(author=username, key=ach.get("key")):
                self.assertEqual(set(ach), {"key", "label", "art", "tier"})
                self.assertTrue(ach["label"])
                self.assertTrue(ach["art"])
                self.assertIn(ach["tier"], stub_data.AWARD_TIERS)

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
        self.assertEqual(stub_data.READ_TIER_ART[100_000][1], "gold")
        self.assertEqual(stub_data.READ_TIER_ART[1_000][1], "bronze")

    def test_read_tier_art_covers_every_tier(self):
        thresholds = {t[0] for t in stub_data.READ_TIERS}
        self.assertEqual(set(stub_data.READ_TIER_ART), thresholds)
        for art, metal in stub_data.READ_TIER_ART.values():
            with self.subTest(art=art):
                self.assertIn(metal, stub_data.AWARD_TIERS)

    def test_art_slugs_are_unique_per_author(self):
        for a in stub_data.AUTHORS:
            arts = [x["art"] for x in stub_data.achievements_of(a.username)]
            with self.subTest(author=a.username):
                self.assertEqual(len(arts), len(set(arts)))

    def test_finished_serial_needs_a_serial(self):
        # У aygerim_k три опубликованных одиночных рассказа и ни одного
        # дописанного сериала: одиночный «дописан» в момент публикации.
        keys = {x["key"] for x in stub_data.achievements_of("aygerim_k")}
        self.assertNotIn("finished_serial", keys)
        self.assertTrue(any(s.is_single for s in stub_data.my_stories_of("aygerim_k")))

    def test_winner_implies_participant_and_accepted(self):
        """Награда конкурса не берётся без заявки, прошедшей жюри (DEC-46)."""
        for a in stub_data.AUTHORS:
            keys = {x["key"] for x in stub_data.achievements_of(a.username)}
            with self.subTest(author=a.username):
                if stub_data.contest_awards_of(a.username):
                    self.assertIn("contest_participant", keys)
                    self.assertIn("contest_accepted", keys)

    def test_editorial_badge_comes_from_public_work(self):
        label = stub_data.BADGE_LABELS["editorial"]
        for a in stub_data.AUTHORS:
            keys = {x["key"] for x in stub_data.achievements_of(a.username)}
            has_public = any(label in s.badges
                             for s in stub_data.public_stories_of(a.username))
            with self.subTest(author=a.username):
                self.assertEqual("editorial_choice" in keys, has_public)

    def test_winning_stories_belong_to_author(self):
        for a in stub_data.AUTHORS:
            for s in stub_data.winning_stories_of(a.username):
                with self.subTest(author=a.username, story=s.slug):
                    self.assertEqual(s.author_username, a.username)
