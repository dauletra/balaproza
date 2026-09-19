"""Модели портала: поля, Meta, инварианты и мутации.

Производное не хранится (DEC-40, DEC-45). Колонка заводится, только если
значение нельзя вывести (акт человека) или агрегат по логу слишком дорог, —
и тогда рядом стоит её пересчёт.

Подписи собирает `templatetags/qazaqnovel`, выдачу — `managers.py`.
"""

from datetime import timedelta
from functools import cached_property

from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.indexes import GinIndex
from django.core.validators import MaxValueValidator
from django.db import models, transaction
from django.utils import timezone

from .domain.catalog import BADGE_LABELS, PUBLIC_STATUSES
from .domain.contests import AI_DECLARATIONS, SUBMISSION_STATUSES
from .domain.formatting import kk_joined, kk_period
from .domain.library import LIBRARY_KINDS
from .domain.notifications import (
    MODERATION_OUTCOME_LABELS,
    MODERATION_OUTCOMES,
    NOTIF_KINDS,
)
from .domain.profile import GENDERS, GENDER_LABELS
from .domain.reports import REPORT_REASON_LABELS, REPORT_REASONS
from .domain.story import (
    REACTIONS,
    REACTIONS_BY_SLUG,
    REVISION_STATES,
    STORY_FORMATS,
    STORY_STATUSES,
    story_status,
)
from .domain.tags import TAG_STATUSES
from .managers import (
    ContestQuerySet,
    StoryQuerySet,
    from_annotation,
    viewer_choice,
    viewer_mark,
)
from .uploads import _ext, validate_raster_image


def story_cover_path(instance, filename):
    """`covers/<slug>.<ext>`: загруженное имя попало бы в публичный URL
    навсегда, а слаг уникален и читается."""
    return f'covers/{instance.slug}{_ext(filename)}'


def user_avatar_path(instance, filename):
    return f'avatars/{instance.username}{_ext(filename)}'


def contest_poster_path(instance, filename):
    return f'contests/{instance.slug}{_ext(filename)}'


def award_image_path(instance, filename):
    """`awards/<contest>/<award>.<ext>` (BR-46). Конкурс в пути обязателен:
    «бас-жүлде» есть у каждого второго, и эмблемы затирали бы друг друга."""
    return f'awards/{instance.contest.slug}/{instance.slug}{_ext(filename)}'


class User(AbstractUser):
    """Пользователь портала; роли «читатель» нет (DEC-01). `first_name` /
    `last_name` убраны: казахское имя не делится на две западные графы.
    Настоящего имени сайт не хранит вовсе (DEC-82) — только `pen_name`,
    под которым автор выступает."""

    first_name = None
    last_name = None

    GENDER_CHOICES = [(g, GENDER_LABELS[g]) for g in GENDERS]

    # Единственное имя у аккаунта — публичное. Обязательно с онбординга
    # (BR-90): пустое поле означало бы, что автора называют по нику
    # (`@id<цифры>`) до первого сознательного выбора, а его теперь нет.
    pen_name = models.CharField('лақап аты', max_length=60, blank=True)
    bio = models.CharField('өзі туралы', max_length=200, blank=True)
    # Самодекларация (DEC-24), без верификации. Возрастную вилку конкурса
    # решает отдельный чекбокс формы подачи (BR-48), а не это поле. Дата,
    # а не число лет (DEC-82): число протухает с каждым днём рождения без
    # пересчёта — то самое производное, которое проект не хранит.
    birth_date = models.DateField('туған күні', null=True, blank=True)
    gender = models.CharField('жынысы', max_length=4, choices=GENDER_CHOICES,
                              blank=True)
    avatar = models.FileField('аватар', upload_to=user_avatar_path, blank=True,
                              max_length=200, validators=[validate_raster_image])
    # Колонка, а не `follower_set.count()`: её читают `ORDER BY` ленты
    # «Жаңа авторлар» и `WHERE` оси каталога. Пересчитывается по строкам
    # `Follow`, а не сдвигается на единицу, — так она сама себя исправляет.
    followers = models.PositiveIntegerField('жазылушы саны', default=0)
    # Провайдер личности (NFR-25). `null=True` — у сидовых и тестовых
    # пользователей его нет и не будет. Не участвует в `username`: тот —
    # случайный плейсхолдер (BR-90), telegram_id только связывает
    # повторный вход с уже существующим аккаунтом.
    telegram_id = models.BigIntegerField('telegram id', unique=True,
                                         null=True, blank=True)
    # Акт согласия (FR-AUTH-05), не булев флаг — с датой, как
    # `AwardGrant`/`Notification.outcome`. Онбординг завершён ⟺ это поле
    # не `None` (BR-90); отдельного флага «завершил онбординг» не заводим.
    terms_accepted_at = models.DateTimeField('ережелерге келісті',
                                             null=True, blank=True)

    class Meta:
        verbose_name = 'пайдаланушы'
        verbose_name_plural = 'пайдаланушылар'
        indexes = [
            # Поиск ищет автора всеми тремя именами `ILIKE`-подстрокой.
            # B-tree её не берёт — совпадение начинается не с начала
            # строки; триграммный берёт и сам складывает регистр.
            GinIndex(fields=['pen_name'], name='user_pen_name_trgm',
                     opclasses=['gin_trgm_ops']),
            GinIndex(fields=['username'], name='user_username_trgm',
                     opclasses=['gin_trgm_ops']),
        ]

    def __str__(self):
        return self.public_name

    def get_full_name(self):
        return self.public_name

    def get_short_name(self):
        return self.public_name

    @property
    def public_name(self) -> str:
        """Как автора называют читателю. Ник — запасной вариант, не второй."""
        return self.pen_name or f'@{self.username}'

    @cached_property
    def works(self) -> int:
        """Сколько работ автора видит читатель (DEC-40). Черновики не в
        счёт: иначе число выдаёт читателю, что у автора есть неопубликованное.
        """
        return from_annotation(
            self, 'works_count',
            lambda: self.stories.filter(status__in=PUBLIC_STATUSES).count())

    # ── Снимок автора на один запрос ─────────────────────────────────────
    # Профиль спрашивает работы автора из восьми мест. Снимок живёт в
    # `self.__dict__`, то есть ровно запрос; долгоживущий экземпляр —
    # команда, скрипт — покажет прочитанное в начале, как всякий снимок.
    @cached_property
    def authored(self) -> list:
        """Все работы автора, любого статуса, «что трогал последним»."""
        from .queries.catalog import all_stories

        return list(all_stories().by_author(self).latest_edited())

    @cached_property
    def public_works(self) -> list:
        """Работы, которые видит посторонний (BR-73). Режется из уже
        загруженных: правило то же, а второй `WHERE` — второй запрос."""
        return [s for s in self.authored if s.is_public]

    @cached_property
    def own_submissions(self) -> list:
        from .queries.contests import submissions_of

        return list(submissions_of(self))

    @cached_property
    def library_entries(self) -> list:
        """Вся библиотека — три полки одной выборкой."""
        from .queries.author import library_of

        return list(library_of(self))

    def shelf(self, kind: str) -> list:
        """Одна полка из общей выборки: три вкладки библиотеки стоили трёх
        запросов ради трёх счётчиков."""
        return [e for e in self.library_entries if e.kind == kind]

    @cached_property
    def reads(self) -> int:
        """Сколько раз прочитали автора — по публичным работам (BR-73)."""
        return sum(s.views for s in self.public_works)

    @property
    def joined_since(self) -> str:
        """«2 айдан бері» / «3 жыл 2 айдан бері» в шапке профиля —
        `kk_joined` по алматинскому календарному дню, а не UTC: полночь
        31 декабря по UTC — это уже 1 января в Алматы, и счёт дней обязан
        идти по нему же, не по серверному часовому поясу."""
        joined_date = timezone.localtime(self.date_joined).date()
        days = (timezone.localdate() - joined_date).days
        return kk_joined(days)


class Genre(models.Model):
    """Жанр — закрытый справочник из 12 (DEC-11), не UGC: новый жанр это
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
    """UGC-тег (DEC-26). Заводит автор, судьбу решает модератор.

    Жанр — полка, тег — то, о чём написано сейчас. Отсюда открытый список,
    путь `pending → accepted | rejected` (BR-TAG-03) и блок-лист (BR-TAG-05).
    Оба счётчика — производные (DEC-53), и только по публичным работам.
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
        """«Осы аптада» (DEC-31) — по дате связки, а не колонкой: хранимое
        число не убывает, и витрина стала бы копией накопленной."""
        def counted():
            from .queries.tags import TRENDING_DAYS

            since = timezone.now() - timedelta(days=TRENDING_DAYS)
            return self.stories.filter(
                status__in=PUBLIC_STATUSES,
                storytag__tag=self, storytag__created_at__gte=since).count()

        return from_annotation(self, 'weekly', counted)

    @property
    def is_public(self) -> bool:
        """Виден ли тег постороннему (BR-TAG-07)."""
        return self.status == 'accepted'


class BlockedTagPattern(models.Model):
    """Блок-лист имён тегов (BR-TAG-05). Таблицей, а не константой: список
    пополняется тем, что приносят авторы, и релиза ради строки не ждут."""

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


class StoryTag(models.Model):
    """Связка «работа — тег», с датой (DEC-31). Голое M2M не несёт момент,
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


class Story(models.Model):
    """Произведение. Центральный объект портала.

    Что здесь не хранится и почему — docs/architecture.md. Что хранится
    вопреки правилу «производное не хранится» — отмечено на месте.
    """

    STATUS_CHOICES = [(s, s) for s in STORY_STATUSES]
    FORMAT_CHOICES = [(f, f) for f in STORY_FORMATS]

    objects = StoryQuerySet.as_manager()

    slug = models.SlugField('slug', max_length=64, unique=True)
    title = models.CharField('атауы', max_length=120)
    author = models.ForeignKey('core.User', verbose_name='авторы',
                               on_delete=models.CASCADE, related_name='stories')
    # Пусто — `cover_placeholder.html` рисует плашку по тону жанра.
    cover = models.FileField('мұқаба', upload_to=story_cover_path, blank=True,
                             max_length=200, validators=[validate_raster_image])
    annotation = models.TextField('аннотация', blank=True)

    primary_genre = models.ForeignKey(Genre, verbose_name='негізгі жанр',
                                      on_delete=models.PROTECT,
                                      related_name='primary_stories')
    # Второй жанр необязателен: у произведения бывает один.
    secondary_genre = models.ForeignKey(Genre, verbose_name='қосымша жанр',
                                        on_delete=models.PROTECT,
                                        related_name='secondary_stories',
                                        null=True, blank=True)
    # До 10 на произведение (BR-TAG-01) — правило формы, а не схемы.
    # `through=StoryTag`, а не голое M2M: DEC-31 держится на дате связки.
    tags = models.ManyToManyField(Tag, through=StoryTag, verbose_name='тегтер',
                                  blank=True, related_name='stories')

    status = models.CharField('мәртебесі', max_length=16,
                              choices=STATUS_CHOICES, default='NotPublished')
    # Без дефолта (BR-10b): пустая строка значит «автор ещё не выбрал» —
    # отдельное состояние, а не синоним «10+». На детской платформе дефолт
    # проставлял бы отметку за человека.
    audience = models.CharField('жас белгісі', max_length=8, blank=True)
    format = models.CharField('түрі', max_length=8, choices=FORMAT_CHOICES,
                              default='serial')

    # Накопленный счёт за всё время. Колонка, а не COUNT по журналу: журнал
    # держит только окно (DEC-55), за его пределами считать уже нечего.
    views = models.PositiveIntegerField('оқылым', default=0)
    # Просмотры за окно — ось «Қазір танымал» (DEC-36). Денормализовано:
    # агрегат по журналу с окном считался бы на каждой странице каталога.
    # Инвариант `recent_views <= views`. Растёт по строкам `StoryView` и
    # ими же пересчитывается вниз (`recount_views`) — как `Story.likes` и
    # `User.followers`, колонка под ORDER BY, а не независимое число.
    recent_views = models.PositiveIntegerField('14 күндегі оқылым', default=0)
    # Голоса за реакции по всем главам (BR-14, DEC-32) и комментарии — обе
    # колонки, а не вычисление: у работы без текста глав нет вовсе, и счёт
    # по главам обнулил бы ей метрику в каталоге (BR-14a).
    likes = models.PositiveIntegerField('лайк', default=0)
    comments = models.PositiveIntegerField('пікір', default=0)

    # «Дописано» — слово автора о своей работе, а не исход модерации
    # (BR-79). Отдельным полем, потому что `status` теперь пересчитывается
    # по главам и хранить в нём авторское решение больше негде.
    completed_by_author = models.BooleanField('аяқталды деп белгіленген',
                                              default=False)

    # Акт редакции, из данных не выводится, как `AwardGrant` (DEC-46).
    # Второй знак каталога, «Байқауға қатысады», наоборот выводится.
    is_editorial_pick = models.BooleanField('редакция таңдауы', default=False)

    created_at = models.DateTimeField('жасалған', auto_now_add=True)
    # «Когда трогали» (DEC-40) — дата, а не число дней: дельта устаревает
    # каждые сутки. Сид проставляет демо-значения `queryset.update()`, в
    # обход `auto_now`; это единственное место, где так можно.
    updated_at = models.DateTimeField('өзгертілген', auto_now=True)

    class Meta:
        ordering = ('-recent_views', 'title')
        verbose_name = 'шығарма'
        verbose_name_plural = 'шығармалар'
        indexes = [
            models.Index(fields=['status']),
            # По одному на ось сортировки: «Қазір танымал» (дефолт),
            # «Ең көп оқылған», «Жаңалары» (она же дефолт тега, DEC-31).
            models.Index(fields=['-recent_views']),
            models.Index(fields=['-views']),
            models.Index(fields=['-created_at']),
            # Поиск по названию — тот же ILIKE с подстрокой, что и по автору.
            GinIndex(fields=['title'], name='story_title_trgm',
                     opclasses=['gin_trgm_ops']),
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
    def chapters(self) -> int:
        """Сколько частей **может прочесть читатель** (DEC-51, BR-79).

        Считаются опубликованные: «8 бөлім» рядом с текстом на пять — то же
        обещание ненаписанного, ради отказа от которого число и перестало
        быть колонкой. Автору его портфель показывает `chapters_written`.
        """
        return from_annotation(
            self, 'chapter_count',
            lambda: self.chapter_set.filter(
                published_revision__isnull=False).count())

    @property
    def saved_by_viewer(self) -> bool:
        """Лежит ли работа на полке того, кто смотрит (BR-96). Метку ставит
        `for_viewer`; незаданная значит «нет», и это молчаливо неверный
        ответ, поэтому промах пишется в лог (`viewer_mark`), а не
        досчитывается: объект не знает, кто на него смотрит.
        """
        return viewer_mark(self, 'viewer_saved', False)

    @property
    def read_up_to(self) -> int:
        """Докуда дочитал тот, кто смотрит; 0 — не начинал (BR-96)."""
        return viewer_mark(self, 'viewer_chapter', 0)

    @property
    def viewer_progress_pct(self) -> int:
        """Прогресс полосой на обложке — только у сериала.

        У одночастной работы `chapters` равна единице, и любая начатая
        превращалась бы в «100%»: запись о прогрессе там означает «открыл»,
        а не «дочитал». Врать полосой хуже, чем не рисовать её.
        """
        if self.is_single or self.chapters < 2 or self.read_up_to < 1:
            return 0
        return min(100, round(100 * self.read_up_to / self.chapters))

    @property
    def last_published_at(self):
        """Когда читателю показали последнюю часть — или `None`, если ни
        одной ещё не показали.

        Не `updated_at`: тот двигает любое сохранение строки, в том числе
        пересчёт статуса и решение модератора о соседней главе, и подпись
        «жаңарды» врала бы на работе, где ничего нового не вышло. Здесь —
        дата решения по опубликованной ревизии (BR-79), ровно момент, с
        которого часть стала видна.

        Имя аннотации намеренно другое (`last_published`): свойство —
        data-дескриптор и перекрывает одноимённый атрибут экземпляра, то
        есть совпади имена — `from_annotation` читал бы сам себя. Тот же
        разнос, что у `chapters`/`chapter_count`.
        """
        return from_annotation(
            self, 'last_published',
            lambda: self.chapter_set.filter(published_revision__isnull=False)
            .aggregate(last=models.Max('published_revision__decided_at'))['last'])

    @property
    def chapters_written(self) -> int:
        """Сколько частей написано, включая ждущие модератора — число
        кабинета: автор, написавший три бөлім, обязан видеть три."""
        return from_annotation(self, 'written_chapter_count',
                               self.chapter_set.count)

    @property
    def has_chapters(self) -> bool:
        """Написана ли хоть одна глава — не «есть ли текст»: пустая глава
        даёт ноль знаков, но работа уже начата, и полоса внимания кабинета
        зовёт дописать именно её."""
        return from_annotation(self, 'has_any_chapter',
                               self.chapter_set.exists)

    @property
    def text_chapter(self):
        """`pk` главы одночастного произведения; None — текста нет.

        У `single` глава ровно одна, и «Мәтін» обязана вести в неё, а не в
        пустой редактор: иначе автор заведёт вторую там, где текст один по
        определению. Отдаёт `pk`, а не `number` (BR-83): адрес кабинета
        держится на стабильном id, номер — читательский и им не адресуют.
        """
        if not self.is_single:
            return None
        first = self.chapter_set.first()
        return first.pk if first else None

    # ── Статус и время ───────────────────────────────────────────────────
    @property
    def is_public(self) -> bool:
        """Видит ли работу читатель. По `PUBLIC_STATUSES`, а не по литералу
        'Published' — иначе из выдачи молча пропадают все сериалы (DEC-37)."""
        return self.status in PUBLIC_STATUSES

    def refresh_status(self) -> str:
        """Пересчитать `status` по главам (BR-79) и сохранить, если сдвинулся.

        Единственная дверь, через которую колонка меняется. Раньше статус
        назначали — модерация, форма настроек, админка, — и каждое из мест
        отвечало за свой кусок правды. Теперь правда одна: что опубликовано
        и что ждёт очереди.
        """
        chapters = list(self.chapter_set.all())
        # Возвращённое отличается от нетронутого черновика (BR-80), и
        # отличие это — последнее решение модератора, а не отдельная
        # колонка: колонка разошлась бы с лентой уведомлений, где то же
        # решение уже записано.
        last_outcome = (Notification.objects
                        .filter(story=self, kind='moderation')
                        .order_by('-created_at', '-pk')
                        .values_list('outcome', flat=True).first())
        fresh = story_status(
            has_published=any(c.published_revision_id for c in chapters),
            has_pending=ChapterRevision.objects.filter(
                chapter__story=self, state='pending').exists(),
            is_single=self.is_single,
            completed=self.completed_by_author,
            returned=last_outcome in ('needs_work', 'rejected'),
        )
        if fresh != self.status:
            self.status = fresh
            self.save(update_fields=['status', 'updated_at'])
        return fresh

    def apply_moderation(self, outcome: str, reason: str = '', moderator=None):
        """Решение модератора: судьба поданных ревизий и весть автору.

        Одна дверь на два действия, потому что порознь они бессмысленны:
        статус без уведомления оставляет автора гадать. Здесь, а не в
        `admin.py`: админка — сегодняшний инструмент модерации (DEC-23).
        Причина обязательна у обоих отрицательных исходов (BR-11, BR-72b).

        Решается **поданный текст**, а не работа целиком (BR-79):
        одобрение переводит каждую ждущую ревизию в опубликованную, отказ
        закрывает её и **не трогает то, что уже стоит у читателя**. Это и
        есть разница с прежней моделью: у публичного сериала, чью новую
        главу вернули на доработку, старые главы остаются на месте, а
        назначенный `NotPublished` увёл бы из каталога всю работу.

        Возвращает созданное уведомление.
        """
        if outcome not in MODERATION_OUTCOMES:
            raise ValueError(f'Белгісіз модерация нәтижесі: {outcome!r}')
        pending = list(ChapterRevision.objects.filter(
            chapter__story=self, state='pending').select_related('chapter'))
        if not pending:
            raise ValueError(
                f'«{self.title}» модерацияға жіберілмеген: күтіп тұрған нұсқа жоқ.')
        reason = reason.strip()
        if outcome != 'approved' and not reason:
            raise ValueError('Себепсіз қайтаруға болмайды (BR-11).')

        from .queries.notifications import notify_new_chapter

        now = timezone.now()
        # Сколько глав **впервые** стало видно читателю. Не то же, что
        # число одобренных ревизий: одобренная правка уже стоящего текста
        # — не новая часть, и звать за ней подписчиков второй раз значит
        # обещать им то, чего нет.
        opened = 0
        with transaction.atomic():
            for revision in pending:
                revision.state = 'approved' if outcome == 'approved' else 'rejected'
                revision.decided_at = now
                revision.save(update_fields=['state', 'decided_at'])
                if outcome == 'approved':
                    chapter = revision.chapter
                    if chapter.published_revision_id is None:
                        opened += 1
                    chapter.published_revision = revision
                    chapter.save(update_fields=['published_revision'])
            # Акт решения — с тем, кто его принял (BR-82). Пишется рядом с
            # уведомлением и в той же транзакции: это две стороны одного
            # события, и разойтись они не должны.
            ModerationDecision.objects.create(
                story=self, moderator=moderator, outcome=outcome,
                reason=reason, chapters=len(pending))
            # Метка «взял в работу» снимается решением: она про намерение
            # прочесть, а прочтение состоялось.
            ModerationClaim.objects.filter(story=self).delete()
            # Уведомление пишется **до** пересчёта: статус `NeedsWork`
            # выводится из последнего решения (BR-80), а решение и есть эта
            # запись. Обратный порядок оставлял бы возвращённую работу
            # неотличимой от нетронутого черновика до следующей правки.
            note = Notification.objects.create(
                user=self.author, kind='moderation', story=self,
                outcome=outcome, text=reason,
            )
            self.refresh_status()
            # После пересчёта: подписчиков зовут на то, что уже стоит у
            # читателя. Тип у этих строк другой (`new_chapter`), и
            # `refresh_status`, читающий последнее решение по `moderation`,
            # их не видит, — порядок выбран смыслом, а не необходимостью.
            if opened:
                notify_new_chapter(self, opened)
            return note

    def take_down(self, reason: str) -> 'Notification':
        """Снять уже опубликованное с публикации по жалобе (BR-33).

        Не `apply_moderation`: та решает поданную ревизию (BR-79) и без
        `pending` падает — здесь наоборот, ревизии может не быть вовсе,
        решается то, что уже стоит у читателя. Общее с ней — форма: акт,
        уведомление и пересчёт статуса одной транзакцией. Текст остаётся
        у автора, снимается только видимость (`published_revision`), тем
        же способом, каким её даёт BR-79, — поэтому `refresh_status()`
        сам приводит работу в `NeedsWork`, ничего изобретать не пришлось.

        Кто снял — хранит сам `Report` (`resolved_by`/`resolved_at`), не
        это уведомление: у `apply_moderation` тоже нет `actor` в акте
        читателю, решение платформы не подписывается именем модератора.
        """
        reason = reason.strip()
        if not reason:
            raise ValueError('Себепсіз алып тастауға болмайды.')
        with transaction.atomic():
            self.chapter_set.filter(published_revision__isnull=False) \
                .update(published_revision=None)
            note = Notification.objects.create(
                user=self.author, kind='moderation', story=self,
                outcome='rejected', text=reason,
            )
            self.refresh_status()
            return note

    @property
    def updated_days_ago(self) -> int:
        """Сколько дней работу не трогали. Число, а не подпись: кабинет
        считает им срок проверки, а подпись собирает фильтр `since`."""
        return (timezone.now() - self.updated_at).days

    # ── Знаки каталога ───────────────────────────────────────────────────
    @property
    def badges(self) -> tuple:
        """Подписи знаков на карточке (DEC-36). Редакционный хранится — это
        акт человека; конкурсный выводится из заявки в **незавершённый**
        конкурс: ушедшая к жюри работа ещё участвует (DEC-45)."""
        out = []
        if self.is_editorial_pick:
            out.append(BADGE_LABELS['editorial'])
        in_contest = from_annotation(
            self, 'in_open_contest',
            lambda: self.submissions.filter(
                contest__results_on__gt=timezone.localdate()).exists())
        if in_contest:
            out.append(BADGE_LABELS['contest'])
        return tuple(out)

    # ── Объём чтения ─────────────────────────────────────────────────────
    @property
    def total_chars(self) -> int:
        """Объём написанного текста. Оценки по заявленным частям нет:
        ненаписанная работа честно показывает нижнюю границу."""
        return from_annotation(
            self, 'effective_chars',
            lambda: sum(c.public_char_count for c in self.chapter_set.all()))

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


class StoryView(models.Model):
    """Одно засчитанное прочтение работы — журнал под окно «Қазір танымал».

    Ось DEC-36 обещает просмотры за две недели, но без дат убывать им было
    не от чего: оба счётчика росли вместе, и окно со временем сходилось с
    «Ең көп оқылған» — две оси показывали бы один и тот же порядок
    (DEC-55).

    Журнал держит **только окно**: `recount_views` пересчитывает по нему
    `Story.recent_views` и тут же вычищает всё, что старше. Поэтому таблица
    растёт с трафиком двух недель, а не с трафиком за всё время, а
    накопленный `Story.views` остаётся колонкой — за пределами окна
    считать уже нечего.

    `viewer` пуст у гостя: читают и без входа, и это тоже прочтение.
    Дедупликация идёт раньше вставки, по сессии (`views/story._count_view`).
    """

    story = models.ForeignKey(Story, verbose_name='шығарма',
                              on_delete=models.CASCADE, related_name='view_set')
    viewer = models.ForeignKey(User, verbose_name='оқырман', null=True,
                               blank=True, on_delete=models.SET_NULL,
                               related_name='+')
    # Не `auto_now_add`: сид расставляет прошлые моменты по всему окну, а
    # `auto_now_add` проставил бы всем время запуска — и весь журнал
    # оказался бы в одном дне.
    created_at = models.DateTimeField('оқылған сәт', default=timezone.now)

    class Meta:
        verbose_name = 'оқылым'
        verbose_name_plural = 'оқылымдар'
        indexes = [
            # Пересчёт идёт по работе и дате, вычистка — по одной дате.
            models.Index(fields=['story', '-created_at']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f'{self.story_id} @ {self.created_at:%Y-%m-%d}'


class Chapter(models.Model):
    """Глава — единица публикации (BR-79).

    Здесь лежит **рабочая копия** автора: `title`/`body`/`char_count` — то,
    что он сейчас пишет, и то, что правит автосохранение. Читателю она не
    показывается никогда. Читатель видит `published_revision` — снимок,
    который прошёл модератора.

    Разделение появилось потому, что до него это была одна строка: правка
    одобренного текста доезжала до читателя мгновенно, а новая глава
    публичного сериала публиковалась сама (C1/C2 в AUDIT-WRITE-FLOW).
    Модерация выдавалась работе один раз и дальше ни на что не влияла.
    """

    # Метка зрителя, её ставит `queries/story.chapters_of`. По умолчанию
    # **читатель**: промах метки должен приводить к «показать меньше», а не
    # к утечке неодобренного текста.
    as_author = False

    story = models.ForeignKey(Story, verbose_name='шығарма',
                              on_delete=models.CASCADE)
    # Читательский номер — контиг 1..N, пересчитывается вслед за `position`
    # (`queries/write._renumber_chapters`, BR-84). Кабинет адресует главу
    # не им, а `pk` (BR-83): номер сдвигается при удалении/перестановке
    # соседей, и адрес, завязанный на него, тихо открывал бы другую главу.
    number = models.PositiveSmallIntegerField('нөмірі')
    # Порядок глав — то, чем управляет перестановка автора. Отдельно от
    # `number`, чтобы кабинет не путал «на каком месте» с «под каким видом
    # читателю» — они пересчитываются одной функцией, но это разные вопросы.
    position = models.PositiveSmallIntegerField('реті', default=0)
    title = models.CharField('атауы', max_length=120)
    body = models.TextField('мәтіні', blank=True)
    # Денормализация от `body`: объём спрашивают на каждой странице, а
    # `len()` по тексту романа этого не стоит.
    char_count = models.PositiveIntegerField('таңба саны', default=0)
    # Что видит читатель. Пусто — главы для него не существует: она либо
    # ещё пишется, либо ждёт модератора. `SET_NULL`, а не `CASCADE`:
    # удаление ревизии не должно уносить саму главу.
    published_revision = models.ForeignKey(
        'core.ChapterRevision', verbose_name='жарияланған нұсқа', null=True,
        blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField('жасалған', auto_now_add=True)

    class Meta:
        ordering = ('position', 'number')
        constraints = [
            models.UniqueConstraint(fields=('story', 'number'),
                                    name='unique_chapter_number_per_story'),
        ]
        verbose_name = 'бөлім'
        verbose_name_plural = 'бөлімдер'

    def __str__(self):
        return f'{self.story.slug} · {self.number}. {self.title}'

    def save(self, *args, **kwargs):
        # Браузер шлёт `\r\n` (HTML нормализует перевод строки в textarea на
        # отправке), живой счётчик в редакторе считает JS-строку с голым
        # `\n` — без нормализации здесь объём расходился на число абзацев
        # (V1 в AUDIT-WRITE-FLOW): автор видел 1588 при наборе и 1646 после
        # сохранения. Одно место, потому что char_count кормит read_minutes,
        # length_bucket каталога и условия конкурса min_chars/max_chars.
        self.body = self.body.replace('\r\n', '\n').replace('\r', '\n')
        self.char_count = len(self.body)
        super().save(*args, **kwargs)

    @property
    def reaction_counts(self) -> dict:
        return {r.kind: r.count for r in self.reactions.all()}

    @property
    def likes(self) -> int:
        """Совокупная реакция главы: раскладка нужна внутри главы, а пять
        цифр на карточке каталога превратили бы сетку в дашборд."""
        return sum(r.count for r in self.reactions.all())

    @property
    def top_reaction(self):
        """Самая частая реакция — «чем зацепило» одним словом."""
        rows = list(self.reactions.all())
        if not rows:
            return None
        return REACTIONS_BY_SLUG.get(max(rows, key=lambda r: r.count).kind)

    @property
    def my_reaction(self) -> str:
        """Slug реакции текущего читателя, '' — голоса нет. Метку ставит
        `queries/story._attach_my_reaction`, гостю тоже (BR-REACT-02)."""
        return viewer_choice(self, '_my_reaction')

    # ── Опубликованное против рабочего (BR-79) ───────────────────────────
    @property
    def is_published(self) -> bool:
        return self.published_revision_id is not None

    @property
    def public_title(self) -> str:
        """Заголовок, который видит читатель. Пусто — главы для него нет."""
        return self.published_revision.title if self.is_published else ''

    @property
    def public_body(self) -> str:
        return self.published_revision.body if self.is_published else ''

    @property
    def public_char_count(self) -> int:
        """Объём **опубликованного**. Рабочая копия в счёт не идёт: иначе
        каталог обещал бы читателю знаки, которых он не увидит."""
        return self.published_revision.char_count if self.is_published else 0

    @property
    def shown_title(self) -> str:
        """Что стоит на читательской странице.

        Читателю — одобренное; автору и модератору, открывшим предпросмотр
        (BR-76), — рабочая копия: они смотрят на то, что пишется, иначе
        предпросмотр черновика был бы пуст.
        """
        return self.title if self.as_author else self.public_title

    @property
    def shown_body(self) -> str:
        return self.body if self.as_author else self.public_body

    @property
    def shown_char_count(self) -> int:
        return self.char_count if self.as_author else self.public_char_count

    @property
    def pending_revision(self):
        """Ревизия, ждущая модератора, или None. У главы она одна: подача
        закрывает предыдущую (`submit_story_for_review`)."""
        return next((r for r in self.revisions.all() if r.state == 'pending'),
                    None)

    @property
    def has_unpublished_changes(self) -> bool:
        """Расходится ли рабочая копия с тем, что видит читатель.

        Сравнение по тексту, а не по времени правки: автор мог открыть
        главу, ничего не изменить и сохранить — это не новая версия.
        """
        if not self.is_published:
            return bool(self.body.strip() or self.title.strip())
        published = self.published_revision
        return (self.title, self.body) != (published.title, published.body)


class ChapterRevision(models.Model):
    """Один снимок текста главы и его судьба (BR-79).

    Ревизия — то, что модератор читает и одобряет. Именно она, а не глава,
    проходит модерацию: у главы за жизнь их много, и каждая правка
    опубликованного текста заводит новую, пока не одобренную.

    Причина отказа здесь не хранится — она живёт в `Notification.text`
    (BR-72b): у события есть автор и адресат, у снимка текста их нет.
    """

    STATE_CHOICES = [(s, s) for s in REVISION_STATES]

    chapter = models.ForeignKey(Chapter, verbose_name='бөлім',
                                on_delete=models.CASCADE,
                                related_name='revisions')
    title = models.CharField('атауы', max_length=120)
    body = models.TextField('мәтіні', blank=True)
    char_count = models.PositiveIntegerField('таңба саны', default=0)
    state = models.CharField('күйі', max_length=16, choices=STATE_CHOICES,
                             default='draft')
    created_at = models.DateTimeField('жасалған', auto_now_add=True)
    submitted_at = models.DateTimeField('жіберілген', null=True, blank=True)
    decided_at = models.DateTimeField('шешілген', null=True, blank=True)

    class Meta:
        # Новая сверху: и очередь модератора, и история автора читаются
        # с последней.
        ordering = ('-created_at', '-pk')
        verbose_name = 'бөлім нұсқасы'
        verbose_name_plural = 'бөлім нұсқалары'
        indexes = [
            # Очередь модерации и «есть ли у главы поданное» — один индекс.
            models.Index(fields=['state', 'submitted_at']),
        ]

    def __str__(self):
        return f'{self.chapter_id} · {self.state}'

    def save(self, *args, **kwargs):
        self.char_count = len(self.body)
        super().save(*args, **kwargs)


class ModerationDecision(models.Model):
    """Решение модератора как акт — с тем, кто его принял (BR-82).

    До этой модели след решения был один: `Notification`, адресованное
    автору. У него нет автора решения, и вопрос «кто одобрил вот это»
    ответа не имел вовсе. Акт с датой и человеком не выводится из
    состояния объекта — как `AwardGrant` (DEC-46).

    Уведомление никуда не делось: это разные вещи. Решение — что
    произошло; уведомление — что об этом сказали автору.
    """

    OUTCOME_CHOICES = [(o, MODERATION_OUTCOME_LABELS[o])
                       for o in MODERATION_OUTCOMES]

    story = models.ForeignKey(Story, verbose_name='шығарма',
                              on_delete=models.CASCADE,
                              related_name='moderation_decisions')
    # Модератор мог уйти с портала; решение остаётся — оно уже случилось.
    moderator = models.ForeignKey(User, verbose_name='модератор', null=True,
                                  blank=True, on_delete=models.SET_NULL,
                                  related_name='+')
    outcome = models.CharField('нәтижесі', max_length=16,
                               choices=OUTCOME_CHOICES)
    reason = models.TextField('себебі', blank=True)
    # Сколько глав затронуло решение: одно нажатие решает судьбу пачки
    # ревизий (BR-79), и «одобрено 3 бөлім» — часть того, что случилось.
    chapters = models.PositiveSmallIntegerField('бөлім саны', default=0)
    decided_at = models.DateTimeField('шешілген', auto_now_add=True)

    class Meta:
        ordering = ('-decided_at', '-pk')
        verbose_name = 'модерация шешімі'
        verbose_name_plural = 'модерация шешімдері'
        indexes = [models.Index(fields=['story', '-decided_at'])]

    def __str__(self):
        return f'{self.story_id} · {self.outcome}'

    @property
    def label(self) -> str:
        return MODERATION_OUTCOME_LABELS.get(self.outcome, '')


class ModerationClaim(models.Model):
    """«Взял в работу» (BR-82).

    Отдельной строкой, а не полем у `Story`: состояние живёт минуты,
    удаляется решением и не имеет отношения к произведению как таковому.
    Двое модераторов, открывшие одну работу, до этого узнавали друг о
    друге только по результату — второй читал уже решённое.

    Метка не запрещает решать: она предупреждает. Запрет означал бы, что
    забытая метка блокирует очередь до вмешательства администратора.
    """

    story = models.OneToOneField(Story, verbose_name='шығарма',
                                 on_delete=models.CASCADE,
                                 related_name='claim')
    moderator = models.ForeignKey(User, verbose_name='модератор',
                                  on_delete=models.CASCADE, related_name='+')
    claimed_at = models.DateTimeField('алынған', auto_now_add=True)

    class Meta:
        verbose_name = 'қаралуда'
        verbose_name_plural = 'қаралуда'

    def __str__(self):
        return f'{self.story_id} → {self.moderator_id}'


class ChapterReaction(models.Model):
    """Счётчик одной реакции на главе (DEC-32, BR-REACT-01): агрегат по
    `ChapterReactionVote`, обновляемый в момент голосования. Строка
    заводится первым голосом, а ряд из пяти кнопок полон и без неё."""

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


class ChapterReactionVote(models.Model):
    """Кто поставил какую реакцию на главе (BR-REACT-02/03). Одна активная
    на пользователя и главу — ограничение базы: повторный клик снимает,
    клик по другой заменяет. `Story.likes` считает голоса (BR-14a)."""

    user = models.ForeignKey('core.User', verbose_name='оқырман',
                             on_delete=models.CASCADE,
                             related_name='chapter_reaction_votes')
    chapter = models.ForeignKey(Chapter, verbose_name='бөлім',
                                on_delete=models.CASCADE,
                                related_name='reaction_votes')
    kind = models.CharField('реакция', max_length=16,
                            choices=ChapterReaction.KIND_CHOICES)
    created_at = models.DateTimeField('басылған', auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('user', 'chapter'),
                                    name='one_reaction_per_user_per_chapter'),
        ]
        verbose_name = 'бөлім реакциясының дауысы'
        verbose_name_plural = 'бөлім реакцияларының дауыстары'

    def __str__(self):
        return f'{self.user.username} · {self.chapter_id} · {self.kind}'


class Contest(models.Model):
    """Конкурс. Заводит админ; всё, что можно вывести, выводится (DEC-45).

    Хранятся **три даты** — открытие приёма, дедлайн, итоги; из них
    считаются фаза, отсчёт дней и год. Колонок `status`, `days_left`,
    `year`, `submissions` нет: они протухают назавтра (BR-40a).

    Списки состава — `cached_property`: страница спрашивает их по нескольку
    раз, а экземпляр живёт один запрос.
    """

    objects = ContestQuerySet.as_manager()

    slug = models.SlugField('slug', max_length=64, unique=True)
    name = models.CharField('атауы', max_length=120)
    subtitle = models.CharField('санаты', max_length=160, blank=True)

    opens_on = models.DateField('қабылдау басталады')
    closes_on = models.DateField('қабылдау жабылады')
    results_on = models.DateField('қорытынды жарияланады')

    # None — конкурс без денежного приза. Ноль означал бы «приз есть, но
    # он нулевой», а это разные вещи.
    prize_kzt = models.PositiveIntegerField('сыйлық (₸)', null=True, blank=True)
    # Афиша грузится админом (BR-47a). Пусто — платформа рисует свою.
    poster = models.FileField('афиша', upload_to=contest_poster_path,
                              blank=True, max_length=200,
                              validators=[validate_raster_image])
    # Семейство повторяющегося конкурса (BR-47); пусто — разовый. Слагом,
    # а не совпадением имён: у выпусков имена расходятся.
    series = models.SlugField('серия', max_length=64, blank=True)
    description = models.TextField('сипаттамасы', blank=True)

    # Пороги объёма для подачи (BR-22). У конкурса свои — подпись чек-листа
    # берёт числа отсюда, а не вписывает литералом (FR-CONT-07).
    min_chars = models.PositiveIntegerField('ең аз көлемі', default=5_000)
    max_chars = models.PositiveIntegerField('ең көп көлемі', default=15_000)
    # Возрастная вилка **этого конкурса** (BR-48). Любая граница может
    # отсутствовать, обе — тоже: своего ценза у платформы нет (DEC-47).
    min_age = models.PositiveSmallIntegerField('ең кіші жас', null=True, blank=True)
    max_age = models.PositiveSmallIntegerField('ең үлкен жас', null=True, blank=True)

    class Meta:
        ordering = ('-results_on',)
        verbose_name = 'байқау'
        verbose_name_plural = 'байқаулар'
        constraints = [
            # Инвариант дат: приём открывается не позже дедлайна, итоги —
            # строго после него. Нарушение делает фазу невыводимой.
            models.CheckConstraint(
                condition=models.Q(opens_on__lte=models.F('closes_on')),
                name='contest_opens_before_it_closes'),
            models.CheckConstraint(
                condition=models.Q(closes_on__lt=models.F('results_on')),
                name='contest_results_after_it_closes'),
        ]

    def __str__(self):
        return self.name

    # ── Списки состава ───────────────────────────────────────────────────
    @cached_property
    def awards(self) -> list:
        return list(self.award_set.all())

    @cached_property
    def timeline(self) -> list:
        return list(self.stage_set.all())

    @cached_property
    def jury(self) -> list:
        return list(self.jury_set.all())

    @cached_property
    def conditions(self) -> list:
        """Условия именно этого конкурса, строками. Общие для всех живут
        в `common_rules` и здесь не повторяются (BR-48a)."""
        return [c.text for c in self.condition_set.all()]

    # ── Фаза и сроки (DEC-45) ────────────────────────────────────────────
    @property
    def phase(self) -> str:
        """Одна из `CONTEST_PHASES`; единственный источник — три даты.
        «Қазылар қарауда» отдельная: между дедлайном и итогами конкурс не
        «активен» и ещё не «завершён»."""
        today = timezone.localdate()
        if today < self.opens_on:
            return 'upcoming'
        if today <= self.closes_on:
            return 'accepting'
        if today < self.results_on:
            return 'judging'
        return 'finished'

    @property
    def is_accepting(self) -> bool:
        """Можно ли подать работу. Именно это, а не «конкурс активен»,
        решает судьбу кнопки «Қатысу»."""
        return self.phase == 'accepting'

    @property
    def is_finished(self) -> bool:
        return self.phase == 'finished'

    @property
    def days_left(self):
        return (self.closes_on - timezone.localdate()).days if self.is_accepting else None

    @property
    def days_until_open(self):
        if self.phase != 'upcoming':
            return None
        return (self.opens_on - timezone.localdate()).days

    @property
    def year(self) -> int:
        """Год проведения — год объявления итогов. Нужен конкурсной
        биографии автора: «1 жыл бұрын» устаревает каждый день."""
        return self.results_on.year

    # ── Производное от состава ───────────────────────────────────────────
    @property
    def submissions(self) -> int:
        """Число поданных работ — по заявкам (аннотация `submission_count`)."""
        return from_annotation(self, 'submission_count',
                               self.submission_set.count)

    @cached_property
    def awards_by_slug(self) -> dict:
        return {a.slug: a for a in self.awards}

    @cached_property
    def grants(self) -> list:
        """Присуждения этого конкурса, в порядке номинаций (DEC-46)."""
        return list(self.grant_set.all())

    @cached_property
    def winner_stories(self) -> list:
        """Произведения-победители, в порядке номинаций, без повторов.
        Автор выводится через работу, вторым полем не хранится."""
        seen, out = set(), []
        for grant in self.grants:
            if grant.story_id not in seen:
                seen.add(grant.story_id)
                out.append(grant.story)
        return out

    @cached_property
    def winners(self) -> tuple:
        """Слаги победителей — производное от присуждений, не хранимый кортеж."""
        return tuple(s.slug for s in self.winner_stories)

    @cached_property
    def other_editions(self) -> list:
        """Другие выпуски того же семейства, свежие сверху (BR-47). Без них
        завершённый конкурс — тупик, хотя приём в выпуск этого года может
        идти прямо сейчас."""
        if not self.series:
            return []
        return list(Contest.objects.for_card()
                    .filter(series=self.series)
                    .exclude(pk=self.pk).order_by('-results_on'))

    @cached_property
    def current_stage(self):
        """Этап, идущий сейчас. Нужен рейлу (FR-CONT-09) — «что происходит
        прямо сейчас» единственное, чего нет в хиро."""
        return next((s for s in self.timeline if s.state == 'active'), None)

    @cached_property
    def next_stage(self):
        return next((s for s in self.timeline if s.state == 'upcoming'), None)


class ContestCondition(models.Model):
    """Условие конкретного конкурса, одной строкой: только то, чем он
    отличается. Общие правила живут одним списком в `common_rules` и в
    каждый конкурс не переписываются (BR-48a)."""

    contest = models.ForeignKey(Contest, verbose_name='байқау',
                                on_delete=models.CASCADE,
                                related_name='condition_set')
    text = models.CharField('шарт', max_length=200)
    position = models.PositiveSmallIntegerField('реті', default=0)

    class Meta:
        ordering = ('position', 'pk')
        verbose_name = 'байқау шарты'
        verbose_name_plural = 'байқау шарттары'

    def __str__(self):
        return self.text


class TimelineStage(models.Model):
    """Этап конкурса. Хранятся даты, состояние выводится: проставленное
    руками, оно устаревает молча."""

    contest = models.ForeignKey(Contest, verbose_name='байқау',
                                on_delete=models.CASCADE,
                                related_name='stage_set')
    label = models.CharField('атауы', max_length=80)
    starts = models.DateField('басталуы')
    # Однодневный этап задаётся равными датами — «15 жел» вместо диапазона.
    ends = models.DateField('аяқталуы')
    position = models.PositiveSmallIntegerField('реті', default=0)

    class Meta:
        ordering = ('position', 'starts')
        verbose_name = 'байқау кезеңі'
        verbose_name_plural = 'байқау кезеңдері'

    def __str__(self):
        return f'{self.label} ({kk_period(self.starts, self.ends)})'

    @property
    def state(self) -> str:
        today = timezone.localdate()
        if today > self.ends:
            return 'done'
        if today >= self.starts:
            return 'active'
        return 'upcoming'


class JuryMember(models.Model):
    """Член жюри конкурса. Имя и роль — то, что видит участник."""

    contest = models.ForeignKey(Contest, verbose_name='байқау',
                                on_delete=models.CASCADE,
                                related_name='jury_set')
    name = models.CharField('аты-жөні', max_length=120)
    role = models.CharField('рөлі', max_length=40)
    position = models.PositiveSmallIntegerField('реті', default=0)

    class Meta:
        ordering = ('position', 'pk')
        verbose_name = 'қазылар алқасының мүшесі'
        verbose_name_plural = 'қазылар алқасы'

    def __str__(self):
        return f'{self.name} — {self.role}'


class ContestAward(models.Model):
    """Номинация конкурса и её награда (DEC-46, BR-44/46). Общего реестра
    номинаций нет и быть не может — он и есть то, чем один конкурс
    отличается от другого. Раму эмблемы рисует платформа: иначе через
    десять конкурсов ряд наград станет коллекцией чужих JPEG."""

    contest = models.ForeignKey(Contest, verbose_name='байқау',
                                on_delete=models.CASCADE,
                                related_name='award_set')
    slug = models.SlugField('slug', max_length=48)
    title = models.CharField('атауы', max_length=80)
    image = models.FileField('эмблема', upload_to=award_image_path,
                             blank=True, max_length=200,
                             validators=[validate_raster_image])
    description = models.CharField('сипаттамасы', max_length=200, blank=True)
    position = models.PositiveSmallIntegerField('реті', default=0)

    class Meta:
        ordering = ('position', 'pk')
        constraints = [
            models.UniqueConstraint(fields=('contest', 'slug'),
                                    name='unique_award_slug_per_contest'),
        ]
        verbose_name = 'байқау номинациясы'
        verbose_name_plural = 'байқау номинациялары'

    def __str__(self):
        return f'{self.contest.slug} · {self.title}'


class AwardGrant(models.Model):
    """Присуждение: кому и за что вручена награда конкурса (DEC-46, BR-45).
    Хранится сам акт — решение жюри из данных не вычисляется, и этим
    конкурсные награды отличаются от системных знаков (BR-ACH-01). Автор не
    хранится: он у работы."""

    contest = models.ForeignKey(Contest, verbose_name='байқау',
                                on_delete=models.CASCADE,
                                related_name='grant_set')
    award = models.ForeignKey(ContestAward, verbose_name='номинация',
                              on_delete=models.CASCADE,
                              related_name='grant_set')
    story = models.ForeignKey(Story, verbose_name='шығарма',
                              on_delete=models.CASCADE,
                              related_name='award_grants')
    note = models.CharField('түсініктеме', max_length=200, blank=True)

    class Meta:
        ordering = ('award__position', 'pk')
        constraints = [
            models.UniqueConstraint(fields=('contest', 'award'),
                                    name='unique_grant_per_award'),
        ]
        verbose_name = 'марапат'
        verbose_name_plural = 'марапаттар'

    def __str__(self):
        return f'{self.award.title} — {self.story.title}'

    @property
    def author(self):
        return self.story.author


class Submission(models.Model):
    """Заявка автора на конкурс (BR-23, BR-41). Один автор — одна работа;
    ограничение базы, а не только формы: вторая заявка ломает счёт
    участников и конкурсную биографию."""

    STATUS_CHOICES = [(s, s) for s in SUBMISSION_STATUSES]
    AI_DECLARATION_CHOICES = [(v, v) for v in AI_DECLARATIONS]

    contest = models.ForeignKey(Contest, verbose_name='байқау',
                                on_delete=models.CASCADE,
                                related_name='submission_set')
    author = models.ForeignKey('core.User', verbose_name='авторы',
                               on_delete=models.CASCADE,
                               related_name='submissions')
    story = models.ForeignKey(Story, verbose_name='шығарма',
                              on_delete=models.CASCADE,
                              related_name='submissions')
    submitted_on = models.DateField('берілген күні')
    status = models.CharField('күйі', max_length=16, choices=STATUS_CHOICES,
                              default='reviewing')
    # Личный кабинет автора его показывает, чужой профиль — никогда (BR-74a).
    note = models.CharField('қазылар пікірі', max_length=300, blank=True)
    # Ответы формы подачи (DEC-21, DEC-24): пишутся один раз, дальше видны
    # только жюри и модератору.
    ai_declaration = models.CharField('AI көмегі', max_length=8,
                                      choices=AI_DECLARATION_CHOICES,
                                      default='no')
    age_confirmed = models.BooleanField('жасын растады', default=False)
    rules_confirmed = models.BooleanField('ережені растады', default=False)

    class Meta:
        ordering = ('-submitted_on',)
        constraints = [
            models.UniqueConstraint(fields=('contest', 'author'),
                                    name='one_submission_per_author_per_contest'),
        ]
        verbose_name = 'өтінім'
        verbose_name_plural = 'өтінімдер'

    def __str__(self):
        return f'{self.author.username} → {self.contest.slug}'


class Follow(models.Model):
    """Подписка одного автора на другого (FR-PROF-10, BR-75). Списки
    «Жазылымдар» и «Жазылушылар» публичны, но входа в контент из них нет:
    читать зовут жинақтар и каталог (DEC-31)."""

    follower = models.ForeignKey('core.User', verbose_name='кім жазылды',
                                 on_delete=models.CASCADE,
                                 related_name='following_set')
    following = models.ForeignKey('core.User', verbose_name='кімге жазылды',
                                  on_delete=models.CASCADE,
                                  related_name='follower_set')
    created_at = models.DateTimeField('жазылған күні', auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.UniqueConstraint(fields=('follower', 'following'),
                                    name='unique_follow_pair'),
            # На себя не подписываются. Проверка в базе, потому что такая
            # строка ломает счётчики тихо, а не громко.
            models.CheckConstraint(
                condition=~models.Q(follower=models.F('following')),
                name='no_self_follow'),
        ]
        verbose_name = 'жазылым'
        verbose_name_plural = 'жазылымдар'

    def __str__(self):
        return f'{self.follower.username} → {self.following.username}'


class Collection(models.Model):
    """Редакционная подборка — первичный вход в чтение (DEC-31). Создаёт
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
    story = models.ForeignKey(Story, verbose_name='шығарма',
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
    """Книга недели (FR-HOME-03) — редакционный выбор с двумя цитатами.
    Таблицей, а не флагом у произведения: неделя проходит, и выбор
    становится историей, а флаг пришлось бы снимать руками."""

    story = models.ForeignKey(Story, verbose_name='шығарма',
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


class LibraryEntry(models.Model):
    """Запись в библиотеке читателя (BR-60/61). Три вида — «сақталған»,
    «оқу үстінде», «оқылған» — не пересекаются: работа лежит ровно в одном,
    и это ограничение базы. Номера главы здесь нет (DEC-52) — его знает
    `ReadingProgress`, а полка получает аннотацией."""

    KIND_CHOICES = [(k, k) for k in LIBRARY_KINDS]

    user = models.ForeignKey('core.User', verbose_name='оқырман',
                             on_delete=models.CASCADE,
                             related_name='library')
    story = models.ForeignKey(Story, verbose_name='шығарма',
                              on_delete=models.CASCADE,
                              related_name='library_entries')
    kind = models.CharField('түрі', max_length=16, choices=KIND_CHOICES)
    added_on = models.DateField('қосылған күні', default=timezone.localdate)

    class Meta:
        ordering = ('-added_on', 'pk')
        indexes = [
            # «Полка такого-то читателя» — единственный способ, которым
            # в эту таблицу ходят.
            models.Index(fields=['user', 'kind']),
        ]
        constraints = [
            models.UniqueConstraint(fields=('user', 'story'),
                                    name='one_library_entry_per_story'),
        ]
        verbose_name = 'кітапхана жазбасы'
        verbose_name_plural = 'кітапхана жазбалары'

    def __str__(self):
        return f'{self.user.username} · {self.story.slug} ({self.kind})'


class ReadingProgress(models.Model):
    """Где читатель остановился — двигатель «Оқуды жалғастыру» (FR-HOME-02).
    Цитата хранится, потому что позиции в тексте у нас нет: читалка не
    сообщает, где закрыли страницу."""

    user = models.ForeignKey('core.User', verbose_name='оқырман',
                             on_delete=models.CASCADE,
                             related_name='reading_progress')
    story = models.ForeignKey(Story, verbose_name='шығарма',
                              on_delete=models.CASCADE,
                              related_name='reading_progress')
    current_chapter = models.PositiveSmallIntegerField('бөлім', default=1)
    quote = models.TextField('соңғы абзац', blank=True)
    minutes_left = models.PositiveSmallIntegerField('қалған минут', default=0)
    last_read_on = models.DateField('соңғы оқыған күні', default=timezone.localdate)

    class Meta:
        ordering = ('-last_read_on',)
        constraints = [
            models.UniqueConstraint(fields=('user', 'story'),
                                    name='one_progress_per_story'),
        ]
        verbose_name = 'оқу барысы'
        verbose_name_plural = 'оқу барысы'

    def __str__(self):
        return f'{self.user.username} · {self.story.slug} → {self.current_chapter}'


class StoryComment(models.Model):
    """Комментарий к произведению или к главе (BR-30, BR-33). Вложенность
    ровно одна: ответ на ответ даёт дерево, которое на телефоне не читается
    и которое некому модерировать."""

    story = models.ForeignKey(Story, verbose_name='шығарма',
                              on_delete=models.CASCADE,
                              related_name='comment_set')
    author = models.ForeignKey('core.User', verbose_name='авторы',
                               on_delete=models.CASCADE,
                               related_name='comments')
    # К какой главе пришвартован; пусто — комментарий ко всему произведению.
    chapter_number = models.PositiveSmallIntegerField('бөлім', null=True,
                                                      blank=True)
    parent = models.ForeignKey('self', verbose_name='жауап',
                               on_delete=models.CASCADE, null=True, blank=True,
                               related_name='reply_set')
    text = models.TextField('мәтіні')
    # Агрегат по `CommentLike` — колонка: пересчитывается в момент нажатия,
    # а не подзапросом на каждый комментарий страницы.
    likes = models.PositiveIntegerField('ұнату', default=0)
    created_at = models.DateTimeField('жазылған', default=timezone.now)

    class Meta:
        ordering = ('pk',)
        verbose_name = 'пікір'
        verbose_name_plural = 'пікірлер'

    def __str__(self):
        return f'{self.author.username}: {self.text[:40]}'

    @cached_property
    def replies(self) -> list:
        """Ответы на комментарий, по `pk`. `cached_property`, потому что
        метку `.liked` (BR-31) ставит `queries/story` на уже полученных
        объектах; без своего `select_related` — он рвёт кэш prefetch'а."""
        return list(self.reply_set.all())

    @property
    def is_author_badge(self) -> bool:
        """Пишет автор произведения — выводится, не проставляется руками."""
        return self.author_id == self.story.author_id

    def belongs_to(self, username: str) -> bool:
        """Свой комментарий: меню предлагает «Жою», а не «Шағым» (BR-33)."""
        return bool(username) and self.author.username == username


class CommentLike(models.Model):
    """Кто лайкнул какой комментарий (BR-31). Повторный клик снимает
    отклик, а для этого надо знать, кто нажимал: счётчик этого не несёт."""

    user = models.ForeignKey('core.User', verbose_name='оқырман',
                             on_delete=models.CASCADE, related_name='comment_likes')
    comment = models.ForeignKey(StoryComment, verbose_name='пікір',
                                on_delete=models.CASCADE, related_name='like_set')
    created_at = models.DateTimeField('басылған', auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('user', 'comment'),
                                    name='unique_like_per_user_per_comment'),
        ]
        verbose_name = 'пікір ұнатуы'
        verbose_name_plural = 'пікір ұнатулары'

    def __str__(self):
        return f'{self.user.username} ♥ #{self.comment_id}'


class Report(models.Model):
    """Жалоба читателя на уже опубликованный контент (BR-33, FR-STORY-09).

    Не про очередь `/moderation/` (та — про ревизии до публикации, BR-82):
    цель здесь — история или комментарий, уже показанные читателю. Ровно
    одно из `story`/`comment` заполнено — проверяется в
    `queries.moderation.create_report`, а не ограничением базы: тот же
    приём, что у `Notification.story`/`contest`.

    Рассмотрение — акт с автором и датой, как `ModerationDecision`: без
    этого «кто отклонил жалобу» осталось бы без ответа. Снятие контента
    жалоба не делает сама — решает `queries.moderation.resolve_report`
    (`Story.take_down` или удаление комментария).
    """

    REASON_CHOICES = [(r, REPORT_REASON_LABELS[r]) for r in REPORT_REASONS]
    OUTCOME_CHOICES = [
        ('dismissed', 'Бұзушылық жоқ'),
        ('upheld',    'Расталды'),
    ]

    reporter = models.ForeignKey('core.User', verbose_name='кімнен',
                                 on_delete=models.CASCADE,
                                 related_name='reports_filed')
    story = models.ForeignKey(Story, verbose_name='шығарма', null=True,
                              blank=True, on_delete=models.CASCADE,
                              related_name='reports')
    # SET_NULL, не CASCADE: снятие комментария по этой же жалобе (`uphold`)
    # не должно стирать акт рассмотрения, а открытая жалоба — пропадать
    # молча, если автор удалит комментарий раньше решения.
    comment = models.ForeignKey(StoryComment, verbose_name='пікір', null=True,
                                blank=True, on_delete=models.SET_NULL,
                                related_name='reports')
    reason = models.CharField('себебі', max_length=16, choices=REASON_CHOICES)
    note = models.CharField('түсініктеме', max_length=500, blank=True)
    created_at = models.DateTimeField('жіберілген', default=timezone.now)
    outcome = models.CharField('нәтижесі', max_length=16, blank=True,
                               choices=OUTCOME_CHOICES)
    resolved_at = models.DateTimeField('қаралған', null=True, blank=True)
    # Модератор мог уйти с портала; шешім қалады — ол болып қойды.
    resolved_by = models.ForeignKey('core.User', verbose_name='қараған',
                                    null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ('created_at',)
        verbose_name = 'шағым'
        verbose_name_plural = 'шағымдар'

    def __str__(self):
        target = f'шығарма #{self.story_id}' if self.story_id else f'пікір #{self.comment_id}'
        return f'{self.reporter_id} → {target}'

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None


class ChapterPoll(models.Model):
    """Необязательный вопрос автора под главой (FR-STORY-13, BR-POLL-01). Не
    квиз: правильного ответа нет и очков не бывает. Опрос закрывается
    публикацией следующей главы (BR-POLL-05), поэтому `closed` вычисляется."""

    chapter = models.OneToOneField(Chapter, verbose_name='бөлім',
                                   on_delete=models.CASCADE,
                                   related_name='poll')
    question = models.CharField('сұрақ', max_length=200)

    class Meta:
        verbose_name = 'бөлім сауалнамасы'
        verbose_name_plural = 'бөлім сауалнамалары'

    def __str__(self):
        return self.question

    @cached_property
    def closed(self) -> bool:
        """Опрос закрыт публикацией следующей главы (BR-POLL-05).

        `cached_property`, а не `property`: страница спрашивает это пять
        раз — сам блок, подпись «жауап келесі бөлімде», ссылка на неё и
        вид каждого варианта, — и каждое обращение шло в базу отдельным
        `EXISTS`. Тот же приём, что у состава конкурса (DEC-46).
        """
        # По `story_id`, а не через `self.chapter.story`: сама работа здесь
        # не нужна, а её загрузка — отдельный запрос за объектом, из
        # которого прочитали бы один ключ.
        return Chapter.objects.filter(story_id=self.chapter.story_id,
                                      number__gt=self.chapter.number).exists()

    @property
    def answer_chapter(self):
        """Глава, где ответ уже есть, — куда вести дочитавшего."""
        return self.chapter.number + 1 if self.closed else None

    @cached_property
    def options(self) -> list:
        """Варианты ответа. Кэш обязателен: их перебирают `total_votes`,
        `results` и сам шаблон, а `option_set.all()` каждый раз новый."""
        return list(self.option_set.all())

    @property
    def total_votes(self) -> int:
        return sum(o.votes for o in self.options)

    @property
    def my_vote(self) -> str:
        """Slug варианта текущего читателя, '' — не голосовал. Метку
        ставит `queries/story._attach_my_vote`, как у `my_reaction`."""
        return viewer_choice(self, '_my_vote')

    @property
    def results(self) -> list:
        total = self.total_votes or 1
        mine = self.my_vote
        return [
            {
                'slug':    o.slug,
                'text':    o.text,
                'count':   o.votes,
                'percent': round(o.votes * 100 / total),
                'mine':    o.slug == mine,
            }
            for o in self.options
        ]


class PollOption(models.Model):
    """Вариант ответа. До четырёх на опрос (BR-POLL-02) — лимит формы, а не
    схемы."""

    poll = models.ForeignKey(ChapterPoll, verbose_name='сауалнама',
                             on_delete=models.CASCADE,
                             related_name='option_set')
    slug = models.SlugField('slug', max_length=32)
    text = models.CharField('мәтіні', max_length=160)
    # Агрегат по `PollVote` — колонка, обновляемая в момент голосования.
    votes = models.PositiveIntegerField('дауыс', default=0)
    position = models.PositiveSmallIntegerField('реті', default=0)

    class Meta:
        ordering = ('position', 'pk')
        constraints = [
            models.UniqueConstraint(fields=('poll', 'slug'),
                                    name='unique_option_slug_per_poll'),
        ]
        verbose_name = 'сауалнама нұсқасы'
        verbose_name_plural = 'сауалнама нұсқалары'

    def __str__(self):
        return self.text


class PollVote(models.Model):
    """Голос читателя в опросе главы (BR-POLL-*). Одна ставка на весь опрос,
    не на вариант, и после отправки не меняется — ограничение базы."""

    user = models.ForeignKey('core.User', verbose_name='оқырман',
                             on_delete=models.CASCADE,
                             related_name='poll_votes')
    poll = models.ForeignKey(ChapterPoll, verbose_name='сауалнама',
                             on_delete=models.CASCADE,
                             related_name='vote_set')
    option = models.ForeignKey(PollOption, verbose_name='нұсқа',
                               on_delete=models.CASCADE,
                               related_name='vote_set')
    created_at = models.DateTimeField('дауыс берген', auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('user', 'poll'),
                                    name='one_vote_per_user_per_poll'),
        ]
        verbose_name = 'сауалнама дауысы'
        verbose_name_plural = 'сауалнама дауыстары'

    def __str__(self):
        return f'{self.user.username} · {self.poll_id} · {self.option.slug}'


class Notification(models.Model):
    """Событие в ленте автора (FR-NOTIF-01, BR-70…72). Уведомление ведёт к
    своему предмету (BR-72a): имя приходит из объекта, а в `text` лежит
    только событие. Исключения — чужие слова: цитата читателя у
    комментария и причина модератора у отказа (BR-11)."""

    KIND_CHOICES = [(k, k) for k in NOTIF_KINDS]
    OUTCOME_CHOICES = [(o, MODERATION_OUTCOME_LABELS[o])
                       for o in MODERATION_OUTCOMES]

    user = models.ForeignKey('core.User', verbose_name='кімге',
                             on_delete=models.CASCADE,
                             related_name='notifications')
    kind = models.CharField('түрі', max_length=16, choices=KIND_CHOICES)
    created_at = models.DateTimeField('болған уақыты', default=timezone.now)
    # Кто инициатор; пусто — системное событие.
    actor = models.ForeignKey('core.User', verbose_name='кім', null=True,
                              blank=True, on_delete=models.CASCADE,
                              related_name='caused_notifications')
    story = models.ForeignKey(Story, verbose_name='шығарма', null=True,
                              blank=True, on_delete=models.CASCADE,
                              related_name='notifications')
    contest = models.ForeignKey(Contest, verbose_name='байқау', null=True,
                                blank=True, on_delete=models.CASCADE,
                                related_name='notifications')
    # Хранится (BR-72b): это акт модератора, а не состояние работы. Из
    # `Story.status` не выводится — статус живёт дальше события, и
    # вчерашний отказ сказал бы «Модерацияда».
    outcome = models.CharField('модерация нәтижесі', max_length=16, blank=True,
                               choices=OUTCOME_CHOICES)
    text = models.CharField('оқиға', max_length=300, blank=True)
    read = models.BooleanField('оқылды', default=False)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'хабарлама'
        verbose_name_plural = 'хабарламалар'
        indexes = [
            # Лента и бейдж в шапке спрашивают одно: «этого автора за
            # последнюю неделю». Бейдж — на каждой странице у каждого
            # вошедшего, так что этот индекс трогают чаще прочих.
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f'{self.user.username} · {self.kind}'

    @property
    def days_ago(self) -> int:
        """Сколько календарных дней назад. Именно календарных: лента
        группирует по «сегодня / вчера / за неделю», а не по суткам."""
        return (timezone.localdate() - timezone.localtime(self.created_at).date()).days

    @property
    def bucket(self) -> str:
        """Группа FR-NOTIF-01 или '' у события старше недели: групп ровно
        три, четвёртой («раньше») в требовании нет — значит неделя и есть
        глубина ленты."""
        days = self.days_ago
        if days <= 0:
            return 'today'
        if days == 1:
            return 'yesterday'
        return 'past_week' if days <= 7 else ''


class SchoolLink(models.Model):
    """Ссылка «Авторлар мектебі» (DEC-22). Страницы школы у платформы нет и
    не будет — есть блок ссылок на написанное другими. Таблицей, потому что
    список меняется чаще, чем выходит релиз."""

    # Площадка: по ней компонент берёт иконку и фирменный цвет.
    channel = models.CharField('арна', max_length=32)
    title = models.CharField('атауы', max_length=120)
    subtitle = models.CharField('мазмұны', max_length=120, blank=True)
    url = models.URLField('сілтеме')
    position = models.PositiveSmallIntegerField('реті', default=0)

    class Meta:
        ordering = ('position', 'pk')
        verbose_name = 'мектеп сілтемесі'
        verbose_name_plural = 'мектеп сілтемелері'

    def __str__(self):
        return self.title
