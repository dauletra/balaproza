"""Модели Ф14: пользователь и справочники (docs/19 §19.4, этап 1).

Две разные вещи здесь проверяются.

Первая — свойства модели, которые останутся навсегда: как автора зовут
читателю, что уходит из публичного имени в приватное, как нормализуется
блок-лист.

Вторая — справочник, который приезжает вместе со схемой: двенадцать
жанров заливает миграция, и без них не работает ни каталог, ни главная.
Сверять их больше не с чем — второго списка в проекте нет, и это цель,
а не потеря. Проверяется поэтому не совпадение с копией, а то, что
делает справочник справочником: полнота, редакторский порядок и
пригодность каждой записи к рендеру.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

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
        """Порядок жанров — редакторский выбор (DEC-11).

        Проверяется, что он не совпадает с алфавитом: `position` без
        этого выглядит декоративным полем, и первая же сортировка «для
        порядка» переставила бы полосу на главной.
        """
        names = [g.name for g in Genre.objects.all()]
        self.assertEqual(len(names), 12)
        self.assertNotEqual(names, sorted(names))

    def test_every_genre_can_be_rendered(self):
        """У жанра есть всё, чем его рисуют: имя, тон и иконка тайла.

        Пустой `hue` — бесцветный чип, пустой `icon` — дыра на карточке
        `/genres/`; и то и другое видно только глазами, потому что
        страница при этом не падает.
        """
        for genre in Genre.objects.all():
            with self.subTest(genre=genre.slug):
                self.assertTrue(genre.name)
                self.assertTrue(genre.icon)
                self.assertTrue(0 <= genre.hue <= 360)

    def test_genre_carries_no_story_counter(self):
        """`count` — агрегат по каталогу; колонкой он разошёлся бы с выдачей
        на первой же смене статуса работы."""
        self.assertNotIn('count', {f.name for f in Genre._meta.get_fields()})

    def test_blocked_patterns_arrive_with_the_schema(self):
        """Блок-лист тоже референс-данные: без него `is_blocked` пропускает
        всё (BR-TAG-05), а команду сида можно и не запустить."""
        patterns = set(BlockedTagPattern.objects.values_list('pattern', flat=True))
        self.assertTrue(patterns)
        self.assertEqual(patterns, {p.lower().strip() for p in patterns})


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
