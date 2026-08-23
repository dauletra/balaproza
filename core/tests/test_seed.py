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
переключится на базу. Тесты этого файла растут вместе с командой: сейчас
пользователи, теги, произведения и главы, дальше — конкурсы, библиотека,
комментарии.
"""

from django.core.management import call_command
from django.test import TestCase

from core import stub_data
from core.models import Chapter, Genre, Story, Tag, User


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
