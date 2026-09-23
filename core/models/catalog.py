"""Каталог: жанры, теги с их путём модерации, подборки и книга недели."""

from datetime import timedelta
from functools import cached_property

from django.core.validators import MaxValueValidator
from django.db import models
from django.utils import timezone

from ..domain.catalog import PUBLIC_STATUSES
from ..domain.tags import TAG_STATUS_LABELS, TAG_STATUSES
from ..managers import from_annotation


class Genre(models.Model):
    """Жанр — закрытый справочник из 12, не UGC: новый жанр это
    новый цвет в системе и новая строка на главной, то есть решение
    редакции. `position` хранится — порядок редакторский. Числа
    произведений нет: колонкой оно разошлось бы с выдачей."""

    slug = models.SlugField('slug', max_length=32, unique=True)
    name = models.CharField('атауы', max_length=40)
    # OKLCH hue, 0-360 (docs/ui.md): насыщенность и светлота у всех жанров
    # общие, различает их только тон.
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
    """UGC-тег. Заводит автор, судьбу решает модератор.

    Жанр — полка, тег — то, о чём написано сейчас. Отсюда открытый список,
    путь `pending → accepted | rejected` и блок-лист.
    Оба счётчика — производные, и только по публичным работам.
    """

    STATUS_CHOICES = [(s, TAG_STATUS_LABELS[s]) for s in TAG_STATUSES]

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
        indexes = [
            # Обе витрины и автокомплит начинают с `accepted`; дальше
            # порядок задают аннотации, и своего индекса у них быть не может.
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return self.name

    @property
    def usage_count(self) -> int:
        """Сколько публичных работ несут этот тег (аннотация `usage`)."""
        return from_annotation(
            self, 'usage',
            lambda: self.stories.filter(status__in=PUBLIC_STATUSES).count())

    @property
    def weekly_count(self) -> int:
        """«Осы аптада» — по дате связки, а не колонкой: хранимое
        число не убывает, и витрина стала бы копией накопленной."""
        def counted():
            from ..queries.tags import TRENDING_DAYS

            since = timezone.now() - timedelta(days=TRENDING_DAYS)
            return self.stories.filter(
                status__in=PUBLIC_STATUSES,
                storytag__tag=self, storytag__created_at__gte=since).count()

        return from_annotation(self, 'weekly', counted)

    @property
    def is_public(self) -> bool:
        """Виден ли тег постороннему."""
        return self.status == 'accepted'


class BlockedTagPattern(models.Model):
    """Блок-лист: имена тегов и слова, задерживающие
    комментарий (D2). Таблицей, а не константой: список пополняется тем,
    что приносят авторы, и релиза ради строки не ждут.

    `scope` разводит два разных списка в одной таблице, и это не
    экономия, а необходимость. У тега сравнение точное — «спам» ловит тег
    «спам»; у комментария подстрочное — «спам» ловит «спамить». Общий
    список без `scope` означал бы, что образец, заведённый под теги,
    задерживает каждый комментарий, где эта строка встретилась внутри
    слова: «тест» подвесил бы половину ленты.
    """

    SCOPES = (
        ('tag',     'тег атауы'),
        ('comment', 'пікір мәтіні'),
        ('both',    'екеуі де'),
    )

    pattern = models.CharField('үлгі', max_length=48, unique=True)
    scope = models.CharField('қайда қолданылады', max_length=8,
                             choices=SCOPES, default='tag')
    note = models.CharField('түсініктеме', max_length=120, blank=True)

    class Meta:
        ordering = ('pattern',)
        verbose_name = 'тыйым салынған үлгі'
        verbose_name_plural = 'тыйым салынған үлгілер'

    def __str__(self):
        return self.pattern

    def save(self, *args, **kwargs):
        # Сравнение с именем тега идёт в нижнем регистре.
        # Нормализуем на входе, иначе «Спам» в таблице не поймает «спам».
        self.pattern = self.pattern.strip().lower()
        super().save(*args, **kwargs)


class StoryTag(models.Model):
    """Связка «работа — тег», с датой. Голое M2M не несёт момент,
    когда автор поставил тег, — а без него «Осы аптада» нечем посчитать."""

    story = models.ForeignKey('core.Story', verbose_name='шығарма',
                              on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, verbose_name='тег', on_delete=models.CASCADE)
    created_at = models.DateTimeField('қосылған', auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('story', 'tag'),
                                    name='unique_tag_per_story'),
        ]
        verbose_name = 'жұмыс тегі'
        verbose_name_plural = 'жұмыс тегтері'

    def __str__(self):
        return f'{self.story.slug} · #{self.tag.name}'


class Collection(models.Model):
    """Редакционная подборка — первичный вход в чтение. Создаёт
    только редакция; личное хранение — «Кітапхана». Отвечает на «зачем
    читать сейчас», поэтому имя — фраза-состояние, а не жанр."""

    slug = models.SlugField('slug', max_length=64, unique=True)
    name = models.CharField('атауы', max_length=120)
    # OKLCH hue для тонировки карточки и иконки (docs/ui.md).
    tint_hue = models.PositiveSmallIntegerField('түс (OKLCH hue)',
                                                validators=[MaxValueValidator(360)])
    icon = models.CharField('иконка', max_length=32)
    curator = models.CharField('құрастырған', max_length=80, default='редакция')
    description = models.TextField('сипаттамасы', blank=True)
    position = models.PositiveSmallIntegerField('реті', default=0)

    class Meta:
        ordering = ('position', 'pk')
        verbose_name = 'жинақ'
        verbose_name_plural = 'жинақтар'

    def __str__(self):
        return self.name

    @cached_property
    def stories(self) -> list:
        """Работы подборки в редакционном порядке. Через `item_set.all()`, а
        не своим `select_related`: свой запрос игнорирует `prefetch_related`
        вызывающей стороны, и десять карточек стоили бы десяти запросов."""
        return [item.story for item in self.item_set.all()]

    @property
    def covers(self) -> list:
        """Стопка обложек на карточке — первые три в редакционном порядке."""
        return self.stories[:3]

    @property
    def count(self) -> int:
        # `len()` по тому же списку, а не `count()`: при готовом prefetch
        # отдельный COUNT — это ещё один запрос на каждую подборку.
        return len(self.item_set.all())


class CollectionItem(models.Model):
    """Произведение в подборке. Порядок — редакционный, поэтому хранится."""

    collection = models.ForeignKey(Collection, verbose_name='жинақ',
                                   on_delete=models.CASCADE,
                                   related_name='item_set')
    story = models.ForeignKey('core.Story', verbose_name='шығарма',
                              on_delete=models.CASCADE,
                              related_name='collection_items')
    position = models.PositiveSmallIntegerField('реті', default=0)

    class Meta:
        ordering = ('position', 'pk')
        constraints = [
            models.UniqueConstraint(fields=('collection', 'story'),
                                    name='unique_story_per_collection'),
        ]
        verbose_name = 'жинақтағы шығарма'
        verbose_name_plural = 'жинақтағы шығармалар'

    def __str__(self):
        return f'{self.collection.slug} · {self.story.slug}'


class BookOfWeek(models.Model):
    """Книга недели — редакционный выбор с двумя цитатами.
    Таблицей, а не флагом у произведения: неделя проходит, и выбор
    становится историей, а флаг пришлось бы снимать руками."""

    story = models.ForeignKey('core.Story', verbose_name='шығарма',
                              on_delete=models.CASCADE,
                              related_name='weeks')
    # Голос редакции: почему именно это и почему сейчас.
    editorial_note = models.TextField('редакциядан')
    # Из самой книги — приглашение, а не пересказ.
    quote = models.TextField('үзінді')
    published_on = models.DateField('апта басы', default=timezone.localdate)

    class Meta:
        ordering = ('-published_on',)
        get_latest_by = 'published_on'
        verbose_name = 'аптаның кітабы'
        verbose_name_plural = 'аптаның кітаптары'

    def __str__(self):
        return f'{self.published_on}: {self.story.title}'
