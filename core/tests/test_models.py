"""Модели Ф14: пользователь и справочники (docs/19 §19.4, этап 1).

Две разные вещи здесь проверяются.

Первая — свойства модели, которые останутся навсегда: как автора зовут
читателю, что уходит из публичного имени в приватное, как нормализуется
блок-лист.

Вторая — **временная и потому самая важная**: справочник жанров, залитый
миграцией, обязан совпадать с тем, что до сих пор рисует стаб. Пока
источника два, любое расхождение — это молчаливая смена каталога в тот
день, когда чтение переключится на базу (этап 3). Литералы в миграции
заморожены намеренно, сверять их с живым модулем больше нечем.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from core import stub_data
from core.models import BlockedTagPattern, Genre, Tag, User


class UserSaysWhoTheAuthorIs(TestCase):
    """Свои пользователи, а не корпусные: имена демо-авторов заняты сидом,
    и тест о поведении модели не должен зависеть от того, кто есть в
    базе."""


    def test_pen_name_is_the_public_name(self):
        u = User.objects.create_user('demo-pen', pen_name='sayyn', name='Сайын Нұрбекұлы')
        self.assertEqual(u.public_name, 'sayyn')

    def test_without_pen_name_the_nick_stands_in(self):
        """Ник — запасной вариант, а не второе имя: пустого места на месте
        автора у карточки не бывает."""
        u = User.objects.create_user('demo-nick', name='Айдана Серікқызы')
        self.assertEqual(u.public_name, '@demo-nick')

    def test_real_name_is_not_the_public_one(self):
        u = User.objects.create_user('demo-real', pen_name='BekTor',
                                     name='Бекжан Тұрсынов')
        self.assertNotIn('Тұрсынов', u.public_name)
        self.assertEqual(u.get_full_name(), 'Бекжан Тұрсынов')

    def test_western_name_fields_are_gone(self):
        """`first_name` / `last_name` убраны: третье и четвёртое место для
        имени разошлись бы с первыми двумя."""
        fields = {f.name for f in User._meta.get_fields()}
        self.assertNotIn('first_name', fields)
        self.assertNotIn('last_name', fields)

    def test_joined_year_comes_from_the_account(self):
        u = User.objects.create_user('demo-joined')
        self.assertEqual(u.joined_year, timezone.localtime(u.date_joined).year)

    def test_joined_year_is_almaty_time_not_utc(self):
        """Новогодняя ночь: 1 января, 02:00 по Алматы — это ещё 31 декабря
        по UTC. Профиль обязан говорить «2025 жылдан бері», а не 2024."""
        u = User.objects.create_user('demo-newyear')
        User.objects.filter(pk=u.pk).update(
            date_joined=datetime(2025, 1, 1, 2, 0, tzinfo=ZoneInfo('Asia/Almaty')))
        u.refresh_from_db()
        self.assertEqual(u.date_joined.astimezone(UTC).year, 2024)
        self.assertEqual(u.joined_year, 2025)


class ReferenceDataArrivesWithTheSchema(TestCase):
    """Жанры залиты миграцией: без них не работает ни каталог, ни главная."""

    def test_all_twelve_genres_exist(self):
        self.assertEqual(Genre.objects.count(), 12)

    def test_order_is_editorial_not_alphabetical(self):
        slugs = list(Genre.objects.values_list('slug', flat=True))
        self.assertEqual(slugs, [g.slug for g in stub_data.GENRES])

    def test_hue_and_icon_match_the_stub(self):
        """Расхождение здесь — смена цвета карточки в день переключения
        чтения на базу, и заметить её будет нечем."""
        for stub in stub_data.GENRES:
            with self.subTest(genre=stub.slug):
                genre = Genre.objects.get(slug=stub.slug)
                self.assertEqual(genre.name, stub.name)
                self.assertEqual(genre.hue, stub.hue)
                self.assertEqual(genre.icon, stub.icon)

    def test_genre_carries_no_story_counter(self):
        """`count` — агрегат по каталогу; колонкой он разошёлся бы с выдачей
        на первой же смене статуса работы."""
        self.assertNotIn('count', {f.name for f in Genre._meta.get_fields()})

    def test_blocked_patterns_match_the_stub(self):
        patterns = set(BlockedTagPattern.objects.values_list('pattern', flat=True))
        self.assertEqual(patterns, set(stub_data.BLOCKED_TAG_PATTERNS))


class TagsFollowTheirPath(TestCase):
    """Свои теги, не корпусные: слаги демо-набора заняты сидом."""

    def test_new_tag_waits_for_a_moderator(self):
        """Дефолт — `pending`: тег заводит автор, а публикует модератор
        (BR-TAG-03)."""
        tag = Tag.objects.create(slug='demo-jana', name='жаңа тег')
        self.assertEqual(tag.status, 'pending')
        self.assertFalse(tag.is_public)

    def test_accepted_tag_is_public(self):
        tag = Tag.objects.create(slug='demo-ashyq', name='ашық тег', status='accepted')
        self.assertTrue(tag.is_public)

    def test_rejected_tag_is_not_public(self):
        tag = Tag.objects.create(slug='spam', name='спам', status='rejected')
        self.assertFalse(tag.is_public)

    def test_slug_keeps_kazakh_letters(self):
        """`allow_unicode`: без него «жасөспірім» превращается в обрубок."""
        tag = Tag.objects.create(slug='жасөспірім', name='жасөспірім')
        self.assertEqual(tag.slug, 'жасөспірім')


class BlockedPatternsAreCompared(TestCase):

    def test_pattern_is_stored_lowercase(self):
        """Сравнение с именем тега идёт в нижнем регистре (BR-TAG-05):
        «Спам» в таблице обязан ловить «спам» в форме."""
        p = BlockedTagPattern.objects.create(pattern='  Спам  ')
        self.assertEqual(p.pattern, 'спам')
