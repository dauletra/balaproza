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

    def test_active_contests_subset_correct(self):
        for c in stub_data.ACTIVE_CONTESTS:
            self.assertEqual(c.status, 'active')
            self.assertIsNotNone(c.days_left, msg='active должен иметь days_left')

    def test_hero_contest_is_active(self):
        self.assertEqual(stub_data.HERO_CONTEST.status, 'active')


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
                    self.assertIn(story.status, ('Published', 'Completed'))


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
