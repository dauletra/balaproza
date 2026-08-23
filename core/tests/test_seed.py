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
пользователи и теги, дальше — произведения, главы, конкурсы.
"""

from django.core.management import call_command
from django.test import TestCase

from core import stub_data
from core.models import Genre, Tag, User


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
