"""Модели Ф14. Порядок появления — docs/19 §19.4.

Сейчас здесь пользователь, справочники, произведения и главы. Конкурсы,
библиотека, комментарии и уведомления приезжают своими этапами, и до тех
пор их данные живут в `core/stub_data.py`.

Модель появляется раньше, чем страницы начинают её читать: сначала
таблица и сид, отдельным шагом — переключение чтения. Так видно, в каком
из двух шагов сломалось, если сломается.

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
from django.utils import timezone

from .domain.catalog import BADGE_LABELS, PUBLIC_STATUSES
from .domain.formatting import kk_updated
from .domain.story import REACTIONS, REACTIONS_BY_SLUG, STORY_FORMATS, STORY_STATUSES
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

        Считается по алматинскому времени, а не по UTC. Разница в пять
        часов значит, что у всех, кто зарегистрировался в новогоднюю ночь
        до пяти утра, профиль показывал бы прошлый год — ровно тот случай,
        когда ошибка заметна одному человеку и никогда не воспроизводится
        у того, кто её ищет.
        """
        return timezone.localtime(self.date_joined).year


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


class Story(models.Model):
    """Произведение. Центральный объект портала.

    Что здесь **не** хранится и почему — docs/19 §19.3. Коротко: число
    работ автора, счётчик жанра, «сколько дней назад трогали» и знак
    «участвует в байқау» считаются, а не лежат колонкой.

    Что хранится вопреки правилу — отмечено на месте. Таких полей три, и
    у каждого своя причина: счётчики просмотров и комментариев дороги
    как агрегаты, а `chapters` пока просто честнее источника.
    """

    STATUS_CHOICES = [(s, s) for s in STORY_STATUSES]
    FORMAT_CHOICES = [(f, f) for f in STORY_FORMATS]

    slug = models.SlugField('slug', max_length=64, unique=True)
    title = models.CharField('атауы', max_length=120)
    author = models.ForeignKey('core.User', verbose_name='авторы',
                               on_delete=models.CASCADE, related_name='stories')
    # Имя файла в MEDIA_ROOT. Пусто — `cover_placeholder.html` рисует
    # типографическую плашку по тону основного жанра, и страница не ломается.
    cover = models.CharField('мұқаба', max_length=200, blank=True)
    annotation = models.TextField('аннотация', blank=True)

    primary_genre = models.ForeignKey(Genre, verbose_name='негізгі жанр',
                                      on_delete=models.PROTECT,
                                      related_name='primary_stories')
    # Второй жанр необязателен: у произведения бывает один.
    secondary_genre = models.ForeignKey(Genre, verbose_name='қосымша жанр',
                                        on_delete=models.PROTECT,
                                        related_name='secondary_stories',
                                        null=True, blank=True)
    # До 10 на произведение (BR-TAG-01). Лимит — правило формы, а не схемы:
    # база не то место, где автору отказывают в одиннадцатом теге.
    tags = models.ManyToManyField(Tag, verbose_name='тегтер', blank=True,
                                  related_name='stories')

    status = models.CharField('мәртебесі', max_length=16,
                              choices=STATUS_CHOICES, default='NotPublished')
    # Возрастная отметка. **Без дефолта** (BR-10b): пустая строка значит
    # «автор ещё не выбрал», и это отдельное состояние, а не синоним «10+».
    # Дефолт в схеме проставлял бы отметку за человека — на детской
    # платформе это самое дорогое поле карточки.
    audience = models.CharField('жас белгісі', max_length=8, blank=True)
    format = models.CharField('түрі', max_length=8, choices=FORMAT_CHOICES,
                              default='serial')

    # Заявленное число частей. Пока хранится, потому что у четырёх сериалов
    # каталога текст не написан вовсе (`KNOWN_TEXTLESS`): вычисление из
    # записей обнулило бы им «17 бөлім» на карточке. Когда пробел закроется,
    # поле уступает место `chapter_set.count()`.
    chapters = models.PositiveSmallIntegerField('бөлім саны', default=0)

    views = models.PositiveIntegerField('оқылым', default=0)
    # Просмотры за 14 дней — ось «Қазір танымал» (DEC-36). Денормализовано
    # намеренно: агрегат по логу просмотров с окном считается на каждой
    # странице каталога. Инвариант `recent_views <= views`; пересчёт — по
    # логу, когда он появится, а не «примерно от views».
    recent_views = models.PositiveIntegerField('14 күндегі оқылым', default=0)
    # Сумма реакций по главам (BR-14, DEC-32) и число комментариев. Оба —
    # агрегаты, оба пока колонки: у произведений без текста глав нет вовсе,
    # и вычисление обнулило бы им метрику в каталоге (BR-14a).
    likes = models.PositiveIntegerField('лайк', default=0)
    comments = models.PositiveIntegerField('пікір', default=0)

    # «Редакция таңдауы» — акт редакции, из данных не выводится, как
    # `AwardGrant` (DEC-46). Второй знак каталога, «Байқауға қатысады»,
    # наоборот, выводится из заявки и колонкой быть не должен.
    is_editorial_pick = models.BooleanField('редакция таңдауы', default=False)

    created_at = models.DateTimeField('жасалған', auto_now_add=True)
    # «Когда трогали» (DEC-40). Именно дата, а не число дней: дельта
    # устаревает каждые сутки. Сид проставляет демо-значения через
    # `queryset.update()` — он обходит `auto_now`, и это единственное
    # место, где обходить его можно.
    updated_at = models.DateTimeField('өзгертілген', auto_now=True)

    class Meta:
        ordering = ('-recent_views', 'title')
        verbose_name = 'шығарма'
        verbose_name_plural = 'шығармалар'
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['-recent_views']),
        ]

    def __str__(self):
        return self.title

    # ── Жанры и теги ─────────────────────────────────────────────────────
    @property
    def genres_resolved(self) -> list:
        return [g for g in (self.primary_genre, self.secondary_genre) if g]

    @property
    def tags_resolved(self) -> list:
        return list(self.tags.all())

    # ── Формат (DEC-28) ──────────────────────────────────────────────────
    @property
    def is_single(self) -> bool:
        return self.format == 'single'

    @property
    def is_serial(self) -> bool:
        return self.format != 'single'

    @property
    def format_label(self) -> str:
        return 'Бір бөлімді' if self.is_single else 'Көп бөлімді'

    @property
    def format_badge_label(self) -> str:
        return 'Бір оқылым' if self.is_single else 'Серия'

    @property
    def text_chapter(self):
        """Номер главы с текстом одночастного произведения; None — текста нет.

        У `single` глава ровно одна, и кнопка «Мәтін» обязана вести в неё,
        а не в пустой редактор: иначе автор сохранит вторую главу у книги,
        у которой текст один по определению.
        """
        if not self.is_single:
            return None
        first = self.chapter_set.first()
        return first.number if first else None

    # ── Статус и время ───────────────────────────────────────────────────
    @property
    def is_public(self) -> bool:
        """Видит ли работу читатель. По `PUBLIC_STATUSES`, а не по литералу
        'Published' — иначе из выдачи молча пропадают все сериалы (DEC-37)."""
        return self.status in PUBLIC_STATUSES

    @property
    def updated_days_ago(self) -> int:
        return (timezone.now() - self.updated_at).days

    @property
    def updated_label(self) -> str:
        return kk_updated(self.updated_days_ago)

    # ── Знаки каталога ───────────────────────────────────────────────────
    @property
    def badges(self) -> tuple:
        """Подписи знаков на карточке (DEC-36).

        Пока только редакционный: «Байқауға қатысады» выводится из заявки,
        а заявки приезжают своим этапом (docs/19 §19.4).
        """
        return (BADGE_LABELS['editorial'],) if self.is_editorial_pick else ()

    # ── Объём чтения ─────────────────────────────────────────────────────
    @property
    def total_chars(self) -> int:
        """Объём текста. Без написанных глав — оценка по заявленным частям:
        у четырёх сериалов каталога текста нет, и ноль знаков превратил бы
        их в «3 минут оқу»."""
        total = sum(c.char_count for c in self.chapter_set.all())
        return total or self.chapters * 1800

    @property
    def read_minutes(self) -> int:
        """900 знаков в минуту — темп, комфортный для казахской прозы."""
        return max(3, (self.total_chars + 899) // 900)

    @property
    def length_bucket(self) -> str:
        """Бакет времени чтения. Границы — из намерения читателя, а не из
        нынешнего корпуса: «между делом», «за один заход», «с закладкой»."""
        if self.read_minutes <= 10:
            return 'short'
        if self.read_minutes <= 30:
            return 'medium'
        return 'long'

    @property
    def reading_meta_label(self) -> str:
        if self.is_single:
            return f'{self.read_minutes} минут оқу'
        return f'{self.chapters} бөлім'


class Chapter(models.Model):
    """Глава. Запись главы обязана нести текст (docs/12 §12.2).

    Обратная связь называется `chapter_set`, а не `chapters`: последнее имя
    занято заявленным числом частей у `Story`, и подменять одно другим
    нельзя — они расходятся ровно там, где текст ещё не написан.
    """

    story = models.ForeignKey(Story, verbose_name='шығарма',
                              on_delete=models.CASCADE)
    number = models.PositiveSmallIntegerField('нөмірі')
    title = models.CharField('атауы', max_length=120)
    body = models.TextField('мәтіні', blank=True)
    # Денормализация от `body`: прогресс чтения «X / N» спрашивает объём на
    # каждой странице, а `len()` по тексту романа этого не стоит.
    char_count = models.PositiveIntegerField('таңба саны', default=0)
    created_at = models.DateTimeField('жасалған', auto_now_add=True)

    class Meta:
        ordering = ('number',)
        constraints = [
            models.UniqueConstraint(fields=('story', 'number'),
                                    name='unique_chapter_number_per_story'),
        ]
        verbose_name = 'бөлім'
        verbose_name_plural = 'бөлімдер'

    def __str__(self):
        return f'{self.story.slug} · {self.number}. {self.title}'

    def save(self, *args, **kwargs):
        self.char_count = len(self.body)
        super().save(*args, **kwargs)

    @property
    def char_count_formatted(self) -> str:
        n = self.char_count
        if n >= 1000:
            return f'{n // 1000},{(n % 1000) // 100} мың'
        return str(n)

    @property
    def reaction_counts(self) -> dict:
        return {r.kind: r.count for r in self.reactions.all()}

    @property
    def likes(self) -> int:
        """Совокупная реакция главы — число для карточек и шапки.

        Раскладка «чем зацепило» нужна внутри главы, но в каталоге пять
        цифр на карточке превратили бы сетку в дашборд.
        """
        return sum(r.count for r in self.reactions.all())

    @property
    def top_reaction(self):
        """Самая частая реакция — «чем зацепило» одним словом."""
        rows = list(self.reactions.all())
        if not rows:
            return None
        return REACTIONS_BY_SLUG.get(max(rows, key=lambda r: r.count).kind)


class ChapterReaction(models.Model):
    """Счётчик одной реакции на главе (DEC-32, BR-REACT-01).

    Счётчик, а не голос конкретного читателя, и это осознанно. Ф14 —
    только чтение: реакцию поставить пока негде, значит строки «кто и что
    нажал» никто не создаёт, а показывать надо итог. Когда появится
    запись (Ф15), рядом встанет таблица голосов, и это поле станет её
    агрегатом — ровно так же, как `Story.likes` станет суммой глав.
    """

    KIND_CHOICES = [(r.slug, r.label) for r in REACTIONS]

    chapter = models.ForeignKey(Chapter, verbose_name='бөлім',
                                on_delete=models.CASCADE,
                                related_name='reactions')
    kind = models.CharField('реакция', max_length=16, choices=KIND_CHOICES)
    count = models.PositiveIntegerField('саны', default=0)

    class Meta:
        ordering = ('kind',)
        constraints = [
            models.UniqueConstraint(fields=('chapter', 'kind'),
                                    name='unique_reaction_kind_per_chapter'),
        ]
        verbose_name = 'бөлім реакциясы'
        verbose_name_plural = 'бөлім реакциялары'

    def __str__(self):
        return f'{self.kind}: {self.count}'
