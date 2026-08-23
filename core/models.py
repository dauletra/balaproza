"""Модели Ф14. Порядок появления — docs/19 §19.4.

Здесь пока только то, что заводится первым: пользователь и справочники.
Произведения, главы, конкурсы и остальное приезжают своими этапами, и до
тех пор их данные живут в `core/stub_data.py`.

Общее правило для всего файла — **производное не хранится**. Число работ
автора, счётчик жанра, популярность тега считаются запросом. Это не вкус:
хранимый `Author.works` уже врал у всех шести авторов сразу, а хранимый
`Contest.days_left` — каждый день после первого (DEC-40, DEC-45). Колонку
заводим, только если значение нельзя вывести (акт человека) или если
агрегат по логу слишком дорог — и тогда рядом стоит его пересчёт.
"""

from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator
from django.db import models

from .domain.tags import TAG_STATUSES


class User(AbstractUser):
    """Пользователь портала. Отдельной роли «читатель» нет (DEC-01).

    Любой, кто зарегистрировался, сразу и читает, и пишет: авторский
    кабинет открыт с первой минуты. Поэтому модели `Author` рядом с
    `User` не существует — она была бы вторым именем одного человека.

    `first_name` / `last_name` убраны намеренно. Казахское имя не делится
    на две западные графы, а у нас и без того есть две разные вещи:
    настоящее имя (`name` — кабинет, модерация, конкурсная заявка) и
    публичное имя (`pen_name` — то, что видит читатель). Оставленные
    пустыми поля из `AbstractUser` стали бы третьим и четвёртым местом,
    где лежит имя, и однажды разошлись бы с первыми двумя.
    """

    first_name = None
    last_name = None

    # Настоящее имя. Публично не показывается: в профиле стоит `public_name`,
    # а это поле нужно модератору и жюри конкурса.
    name = models.CharField('нақты аты', max_length=120, blank=True)
    # Публичное авторское имя. Пустое — значит автор им не обзавёлся, и
    # его называют по нику; дефолта нет, чтобы «псевдоним» не оказался
    # молча проставленным за человека.
    pen_name = models.CharField('лақап аты', max_length=60, blank=True)
    bio = models.CharField('өзі туралы', max_length=200, blank=True)

    class Meta:
        verbose_name = 'пайдаланушы'
        verbose_name_plural = 'пайдаланушылар'

    def __str__(self):
        return self.public_name

    def get_full_name(self):
        return self.name or self.username

    def get_short_name(self):
        return self.pen_name or self.username

    @property
    def public_name(self) -> str:
        """Как автора называют читателю. Ник — запасной вариант, не второй."""
        return self.pen_name or f'@{self.username}'

    @property
    def joined_year(self) -> int:
        """«2024 жылдан бері» в шапке профиля.

        Год, а не полная дата: подростку важно «давно или недавно», а
        точный день — лишние персональные данные на публичной странице.
        """
        return self.date_joined.year


class Genre(models.Model):
    """Жанр — закрытый справочник из 12 (DEC-11).

    Не UGC: новый жанр означает новый цвет в системе (docs/03) и новую
    строку в полосе-вывеске на главной, то есть решение редакции, а не
    запись пользователя. Поэтому справочник сеется миграцией и правится
    в админке, а не формой.

    `position` хранится, потому что порядок жанров — редакторский выбор,
    а не алфавит и не популярность: без него полоса на главной встала бы
    в порядке вставки, то есть случайно.

    Числа произведений здесь нет: `count` — агрегат по каталогу, и как
    колонка он разошёлся бы с выдачей на первой же смене статуса работы.
    """

    slug = models.SlugField('slug', max_length=32, unique=True)
    name = models.CharField('атауы', max_length=40)
    # OKLCH hue, 0-360 (docs/03 §3.3). Насыщенность и светлота у всех жанров
    # общие — различает их только тон, поэтому хранится один параметр.
    hue = models.PositiveSmallIntegerField('түс (OKLCH hue)',
                                           validators=[MaxValueValidator(360)])
    # Слаг <symbol> из спрайта иконок. Пусто — тайл жанра без иконки.
    icon = models.CharField('иконка', max_length=32, blank=True)
    position = models.PositiveSmallIntegerField('реті', default=0)

    class Meta:
        ordering = ('position', 'name')
        verbose_name = 'жанр'
        verbose_name_plural = 'жанрлар'

    def __str__(self):
        return self.name


class Tag(models.Model):
    """UGC-тег (docs/11, DEC-26). Заводит автор, судьбу решает модератор.

    Живёт параллельно жанрам и отвечает на другой вопрос: жанр — это
    полка, тег — то, о чём написано прямо сейчас. Поэтому у тега нет
    закрытого списка, зато есть путь `pending → accepted | rejected`
    (BR-TAG-03) и блок-лист (BR-TAG-05).

    Счётчиков использования в колонках нет: `usage_count` — агрегат по
    работам, `weekly_count` — тот же агрегат с окном в неделю. Если
    окно окажется дорогим, оно станет денормализованной колонкой с
    пересчётом — но тогда рядом будет и пересчёт, как задумано для
    `Story.recent_views` (DEC-36), а не одинокое число.
    """

    STATUS_CHOICES = [(s, s) for s in TAG_STATUSES]

    slug = models.SlugField('slug', max_length=48, unique=True,
                            allow_unicode=True)
    # Оригинал в том виде, как его ввёл автор: он и показывается.
    name = models.CharField('атауы', max_length=48)
    status = models.CharField('күйі', max_length=16, choices=STATUS_CHOICES,
                              default='pending')
    created_at = models.DateTimeField('жасалған', auto_now_add=True)

    class Meta:
        ordering = ('name',)
        verbose_name = 'тег'
        verbose_name_plural = 'тегтер'

    def __str__(self):
        return self.name

    @property
    def is_public(self) -> bool:
        """Виден ли тег постороннему (BR-TAG-07)."""
        return self.status == 'accepted'


class BlockedTagPattern(models.Model):
    """Блок-лист имён тегов (BR-TAG-05), редактируется в админке.

    Таблицей, а не константой в коде: список пополняется по мере того,
    что реально приносят авторы, и ждать релиза ради одной строки
    модератор не должен.
    """

    pattern = models.CharField('үлгі', max_length=48, unique=True)
    note = models.CharField('түсініктеме', max_length=120, blank=True)

    class Meta:
        ordering = ('pattern',)
        verbose_name = 'тыйым салынған үлгі'
        verbose_name_plural = 'тыйым салынған үлгілер'

    def __str__(self):
        return self.pattern

    def save(self, *args, **kwargs):
        # Сравнение с именем тега идёт в нижнем регистре (BR-TAG-05).
        # Нормализуем на входе, иначе «Спам» в таблице не поймает «спам».
        self.pattern = self.pattern.strip().lower()
        super().save(*args, **kwargs)
