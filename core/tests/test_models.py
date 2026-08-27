"""Модели и чистые функции: правила, которые не зависят от страницы.

Здесь три рода проверок, и объединены они не по теме, а по тому, что
всем им **не нужен HTTP**: свойства моделей, справочники из миграции и
шаблонные фильтры. Раньше последние жили отдельным файлом на десять
тестов, и единственное, чем он отличался, — именем.

Данные тесты приносят свои (`factories`), кроме справочников: жанры и
блок-лист приезжают миграцией, и проверять их можно только там, где они
уже есть.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from core import data
from core.models import BlockedTagPattern, Genre, StoryTag, Tag, User
from core.templatetags.balaproza import compact_count, page_range
from core.tests import factories as make
from core.tests.base import TestCase


class UserSaysWhoTheAuthorIs(TestCase):

    def test_public_name_hides_the_real_one(self):
        """Читателю автор известен под лақап аты, настоящее имя видит он
        сам (BR-73). Ник — запасной вариант, а не второе имя: пустого
        места у карточки не бывает."""
        named = User.objects.create_user('demo-pen', pen_name='sayyn',
                                         name='Сайын Нұрбекұлы')
        self.assertEqual(named.public_name, 'sayyn')
        self.assertEqual(named.get_full_name(), 'Сайын Нұрбекұлы')
        self.assertNotIn('Сайын', named.public_name)

        nameless = User.objects.create_user('demo-nick', name='Айдана Серікқызы')
        self.assertEqual(nameless.public_name, '@demo-nick')

    def test_there_is_no_third_place_for_a_name(self):
        """`first_name` / `last_name` убраны: третье и четвёртое место для
        имени разошлись бы с первыми двумя."""
        fields = {f.name for f in User._meta.get_fields()}
        self.assertNotIn('first_name', fields)
        self.assertNotIn('last_name', fields)

    def test_joined_year_is_almaty_time_not_utc(self):
        """Новогодняя ночь: 1 января, 02:00 по Алматы — это ещё 31 декабря
        по UTC. Профиль обязан говорить «2025 жылдан бері», а не 2024."""
        u = User.objects.create_user('demo-newyear')
        self.assertEqual(u.joined_year, timezone.localtime(u.date_joined).year)

        User.objects.filter(pk=u.pk).update(
            date_joined=datetime(2025, 1, 1, 2, 0, tzinfo=ZoneInfo('Asia/Almaty')))
        u.refresh_from_db()
        self.assertEqual(u.date_joined.astimezone(UTC).year, 2024)
        self.assertEqual(u.joined_year, 2025)


class ReferenceDataArrivesWithTheSchema(TestCase):
    """Жанры и блок-лист залиты миграцией: без первых не работает ни
    каталог, ни главная, без второго `is_blocked` пропускает всё
    (BR-TAG-05). Команду сида можно и не запустить — миграцию нельзя."""

    def test_twelve_genres_in_editorial_order(self):
        """Порядок — редакторский выбор (DEC-11). Проверяется, что он не
        совпадает с алфавитом: иначе `position` выглядит декоративным, и
        первая же сортировка «для порядка» переставит полосу на главной."""
        names = [g.name for g in Genre.objects.all()]
        self.assertEqual(len(names), 12)
        self.assertNotEqual(names, sorted(names))

    def test_every_genre_can_be_rendered(self):
        """Пустой `hue` — бесцветный чип, пустой `icon` — дыра на карточке
        `/genres/`; и то и другое видно только глазами, потому что
        страница при этом не падает."""
        for genre in Genre.objects.all():
            with self.subTest(genre=genre.slug):
                self.assertTrue(genre.name)
                self.assertTrue(genre.icon)
                self.assertTrue(0 <= genre.hue <= 360)

    def test_blocked_patterns_are_stored_folded(self):
        """Сравнение идёт в нижнем регистре: «Спам» в таблице обязан
        ловить «спам» в форме."""
        patterns = set(BlockedTagPattern.objects.values_list('pattern', flat=True))
        self.assertTrue(patterns)
        self.assertEqual(patterns, {p.lower().strip() for p in patterns})
        self.assertEqual(BlockedTagPattern.objects.create(pattern='  Спам  ').pattern,
                         'спам')


class TagsFollowTheirPath(TestCase):

    def test_a_new_tag_waits_for_a_moderator(self):
        """Дефолт — `pending`: тег заводит автор, публикует модератор
        (BR-TAG-03)."""
        fresh = Tag.objects.create(slug='demo-jana', name='жаңа тег')
        self.assertEqual(fresh.status, 'pending')
        self.assertFalse(fresh.is_public)
        self.assertTrue(make.tag(status='accepted').is_public)
        self.assertFalse(make.tag(status='rejected').is_public)

    def test_slug_keeps_kazakh_letters(self):
        """`allow_unicode`: без него «жасөспірім» превращается в обрубок."""
        self.assertEqual(
            Tag.objects.create(slug='жасөспірім', name='жасөспірім').slug,
            'жасөспірім')


class CountersAreDerivedNotStored(TestCase):
    """Три числа, которые перестали быть колонками: части работы (DEC-51),
    глава закладки (DEC-52) и оба счётчика тега (DEC-53).

    Общее у них одно: колонку никто не обновлял, и она расходилась с тем,
    что лежит рядом. Здесь проверяется само правило вывода, поэтому
    данные свои: у корпуса свои числа, и тест на них отвечал бы на другой
    вопрос.
    """

    def test_chapter_count_follows_the_written_text(self):
        story = make.story(chapters=0, format='serial')
        self.assertEqual(story.chapters, 0)
        make.chapter(story, number=1)
        make.chapter(story, number=2)
        self.assertEqual(story.chapters, 2)
        self.assertEqual(story.reading_meta_label, '2 бөлім')

    def test_annotated_and_unannotated_agree(self):
        """Аннотация выдачи и одиночный объект обязаны давать одно число:
        иначе карточка каталога и страница произведения расходятся."""
        story = make.story(chapters=3, format='serial')
        from_feed = next(s for s in data.public_stories() if s.pk == story.pk)
        self.assertEqual(from_feed.chapters, 3)
        self.assertEqual(from_feed.chapters, story.chapters)

    def test_tag_counts_come_from_the_links(self):
        """Недельный счётчик не может быть больше накопленного — состояние,
        которое до DEC-53 было достижимо: числа стояли рядом независимо."""
        subject = make.tag()
        recent, old = make.story(chapters=1), make.story(chapters=1)
        for story in (recent, old):
            story.tags.add(subject)
        StoryTag.objects.filter(story=old, tag=subject).update(
            created_at=timezone.now() - timedelta(days=30))

        fresh = Tag.objects.get(pk=subject.pk)
        self.assertEqual(fresh.usage_count, 2)
        self.assertEqual(fresh.weekly_count, 1)
        self.assertLessEqual(fresh.weekly_count, fresh.usage_count)

    def test_a_draft_does_not_inflate_the_tag(self):
        """По счётчику читатель не должен догадываться, что у кого-то есть
        черновик с этим тегом — то же правило, что у жанров."""
        subject = make.tag()
        make.story(chapters=1, status='NotPublished').tags.add(subject)
        self.assertEqual(Tag.objects.get(pk=subject.pk).usage_count, 0)


class ReadingEffortIsHonest(TestCase):

    def test_a_serial_counts_parts_and_a_single_counts_minutes(self):
        single = make.story(chapters=1)
        serial = make.story(chapters=4, format='serial')
        self.assertIn('минут', single.reading_meta_label)
        self.assertIn('бөлім', serial.reading_meta_label)
        self.assertNotIn('минут', serial.reading_meta_label)

    def test_text_chapter_points_at_the_only_chapter(self):
        """Кнопка «Мәтін» обязана вести в существующую главу, а не в
        пустой редактор: у `single` глава ровно одна, и второй быть не
        должно."""
        self.assertEqual(make.story(chapters=1).text_chapter, 1)
        self.assertIsNone(make.story(chapters=0, format='single').text_chapter)
        self.assertIsNone(make.story(chapters=3, format='serial').text_chapter)

    def test_unwritten_work_falls_back_to_the_floor(self):
        """Оценки по заявленным частям больше нет (DEC-51): ненаписанная
        работа честно показывает нижнюю границу времени чтения."""
        empty = make.story(chapters=0, format='serial')
        self.assertEqual(empty.total_chars, 0)
        self.assertEqual(empty.read_minutes, 3)


class CompactCountIsForReaders(TestCase):
    """Узкие карточки сжимают число; точное с разрядами — дело `spaced`."""

    def test_thousands_and_their_boundaries(self):
        self.assertEqual(compact_count(0), '0')
        self.assertEqual(compact_count(999), '999')
        self.assertEqual(compact_count(1000), '1,0 мың')
        self.assertEqual(compact_count(8920), '8,9 мың')
        self.assertEqual(compact_count(10000), '10 мың')
        self.assertEqual(compact_count(12482), '12 мың')

    def test_rounding_up_to_ten_uses_the_integer_form(self):
        """Ветка выбирается по округлённому значению: раньше 9970 попадало
        в десятичную и печаталось «10,0 мың» рядом с «10 мың» у 10000.
        Усечение тоже не годится — оно вернуло бы «9 мың»."""
        self.assertEqual(compact_count(9949), '9,9 мың')
        self.assertEqual(compact_count(9970), '10 мың')
        self.assertEqual(compact_count(9999), '10 мың')

    def test_invalid_input_passes_through(self):
        self.assertEqual(compact_count(None), None)
        self.assertEqual(compact_count('abc'), 'abc')


class PageRangeKeepsTheStripShort(TestCase):
    """Ноль в списке — многоточие: у полосы страниц фиксированная длина,
    и растущий номер не должен её раздвигать."""

    def test_short_ranges_are_shown_whole(self):
        self.assertEqual(page_range(1, 1), [1])
        self.assertEqual(page_range(7, 4), [1, 2, 3, 4, 5, 6, 7])

    def test_long_ranges_collapse_around_the_current_page(self):
        self.assertEqual(page_range(12, 1), [1, 2, 3, 4, 5, 0, 12])
        self.assertEqual(page_range(12, 4), [1, 2, 3, 4, 5, 0, 12])
        self.assertEqual(page_range(12, 12), [1, 0, 8, 9, 10, 11, 12])
        self.assertEqual(page_range(12, 6), [1, 0, 5, 6, 7, 0, 12])
        self.assertEqual(page_range(20, 10), [1, 0, 9, 10, 11, 0, 20])

    def test_invalid_input_returns_empty_list(self):
        self.assertEqual(page_range(None, 1), [])
        self.assertEqual(page_range('abc', 1), [])
        self.assertEqual(page_range(10, 'x'), [])


class TimeIsWordedNotStored(TestCase):
    """«Когда трогали» выводится из `updated_at`, а не хранится числом дней.

    Хранимая дельта устаревала бы каждые сутки — та же ошибка, за которую
    убрали `days_left` у конкурса (DEC-45). Состояния «не задано» у
    подписи нет: у строки в базе времени изменения не может не быть.
    """

    def test_the_whole_scale(self):
        from core.models import Story

        cases = {0: 'бүгін', 1: 'кеше', 3: '3 күн бұрын',
                 7: '1 апта бұрын', 20: '2 апта бұрын', 45: '1 ай бұрын'}
        for days, expected in cases.items():
            with self.subTest(days=days):
                story = Story(updated_at=timezone.now() - timedelta(days=days))
                self.assertEqual(story.updated_label, expected)


class ReadTiersAreLadderNotRating(TestCase):
    """Ступени прочтений (FR-PROF-06). Рейтинга нет и не будет (DEC-41):
    знак говорит «ты сделал», рейтинг — «ты хуже вон того»."""

    def test_boundaries(self):
        cases = [(0, None), (999, None),
                 (1_000, 'Мың оқылым'), (9_999, 'Мың оқылым'),
                 (10_000, 'Он мың оқылым'), (49_999, 'Он мың оқылым'),
                 (50_000, 'Елу мың оқылым'), (99_999, 'Елу мың оқылым'),
                 (100_000, 'Жүз мың оқылым'), (999_999, 'Жүз мың оқылым')]
        for total, expected in cases:
            with self.subTest(total=total):
                tier = data.tier_for(total)
                self.assertEqual(tier[1] if tier else None, expected)

    def test_the_ladder_is_ascending_and_has_a_top(self):
        thresholds = [t[0] for t in data.READ_TIERS]
        self.assertEqual(thresholds, sorted(thresholds))
        self.assertEqual(len(thresholds), len(set(thresholds)))
        self.assertEqual(data.next_tier_for(0)[0], 1_000)
        self.assertEqual(data.next_tier_for(2_117)[0], 10_000)
        self.assertIsNone(data.next_tier_for(100_000))

    def test_reads_count_public_work_only(self):
        """BR-73: прочтения приходят от читателей, читатель видит публичное."""
        author = make.user()
        make.story(author=author, chapters=1, views=500)
        make.story(author=author, chapters=1, views=700, status='NotPublished')
        self.assertEqual(data.reads_total(author.username), 500)

    def test_an_unknown_user_has_no_tier(self):
        self.assertEqual(data.reads_total('ghost'), 0)
        self.assertIsNone(data.read_tier('ghost'))


class PublicWorkCountIsDerived(TestCase):
    """`User.works` — число публичных работ, а не колонка (BR-ACH-01).

    Хранимый счётчик здесь однажды уже разошёлся с реальностью, и это
    решение стало образцом для DEC-51/52/53.
    """

    def test_it_counts_the_public_ones_only(self):
        author = make.user()
        make.story(author=author, chapters=1)
        make.story(author=author, chapters=1, status='Completed', format='serial')
        make.story(author=author, chapters=1, status='NotPublished')
        make.story(author=author, chapters=1, status='OnModeration')
        self.assertEqual(data.author_by_username(author.username).works, 2)
