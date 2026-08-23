"""Модели Ф14. Порядок появления — docs/19 §19.4.

Здесь все таблицы Ф14: пользователь и справочники, произведения и главы,
конкурсы, подписки, жинақтар, библиотека, комментарии, опросы и
уведомления.

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
from .domain.contests import CONTEST_PHASE_LABELS, SUBMISSION_STATUSES
from .domain.formatting import kk_ago, kk_date, kk_period, kk_updated
from .domain.library import LIBRARY_KINDS
from .domain.notifications import (
    MODERATION_OUTCOME_LABELS,
    MODERATION_OUTCOMES,
    NOTIF_KINDS,
)
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
    # Число подписчиков. Колонка, а не `follower_set.count()`, по той же
    # причине, что `Story.likes`: у демо-корпуса счётчик есть, а строк под
    # ним нет — восемь тысяч подписчиков `rudazov` некому создать. Строки
    # `Follow` при этом настоящие и обслуживают «подписан ли я» и списки
    # (FR-PROF-10). После Ф15 колонка становится агрегатом.
    followers = models.PositiveIntegerField('оқырман саны', default=0)

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
    def works(self) -> int:
        """Сколько работ автора видит читатель.

        Считается, а не хранится: колонка врала у всех шести авторов сразу
        и рендерилась в шести местах, включая карточку автора на странице
        произведения (DEC-40). Черновики сюда не входят — иначе число
        выдаёт читателю, что у автора есть неопубликованное.

        Списки авторов подставляют готовую аннотацию: без неё ряд «Жаңа
        авторлар» на главной — это по запросу на каждое имя.
        """
        annotated = getattr(self, 'works_count', None)
        if annotated is not None:
            return annotated
        return self.stories.filter(status__in=PUBLIC_STATUSES).count()

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

    Оба счётчика — колонки, и это уступка, а не замысел. `usage_count`
    вычислим (работ с тегом), `weekly_count` — нет: когда тег появился на
    работе, нигде не записано. А DEC-31 держится ровно на расхождении
    этих двух чисел: «Осы аптада» имеет смысл, только пока она не копия
    «Танымал тегтер». Вычислить одно и хранить другое нельзя — недельный
    счётчик оказался бы больше общего.

    Правильный ответ — дата в связке «работа-тег»; она появится вместе с
    возможностью проставлять теги (Ф15), и тогда оба числа станут
    агрегатами. Пока это та же уступка демо-корпусу, что `User.followers`.
    """

    STATUS_CHOICES = [(s, s) for s in TAG_STATUSES]

    slug = models.SlugField('slug', max_length=48, unique=True,
                            allow_unicode=True)
    # Оригинал в том виде, как его ввёл автор: он и показывается.
    name = models.CharField('атауы', max_length=48)
    status = models.CharField('күйі', max_length=16, choices=STATUS_CHOICES,
                              default='pending')
    usage_count = models.PositiveIntegerField('қолданылған саны', default=0)
    weekly_count = models.PositiveIntegerField('осы аптада', default=0)
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

        Редакционный знак хранится — это акт человека. Конкурсный
        выводится из заявки в **незавершённый** конкурс: работа, ушедшая
        к жюри, ещё участвует, и снимать с неё знак до объявления итогов
        рано (DEC-45).

        Выдача каталога подставляет ответ аннотацией `in_open_contest`:
        без неё двадцать карточек — это двадцать лишних запросов, а с ней
        свойство остаётся верным и у одиночного объекта.
        """
        out = []
        if self.is_editorial_pick:
            out.append(BADGE_LABELS['editorial'])
        in_contest = getattr(self, 'in_open_contest', None)
        if in_contest is None:
            in_contest = self.submissions.filter(
                contest__results_on__gt=timezone.localdate()).exists()
        if in_contest:
            out.append(BADGE_LABELS['contest'])
        return tuple(out)

    # ── Объём чтения ─────────────────────────────────────────────────────
    @property
    def total_chars(self) -> int:
        """Объём текста. Без написанных глав — оценка по заявленным частям:
        у четырёх сериалов каталога текста нет, и ноль знаков превратил бы
        их в «3 минут оқу».

        Выдача каталога считает то же самое аннотацией и подставляет её
        сюда: карточка спрашивает время чтения, и без подстановки страница
        каталога делала по запросу за главы на каждую карточку — сорок
        два запроса на двадцать одну работу.
        """
        annotated = getattr(self, 'effective_chars', None)
        if annotated is not None:
            return annotated
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


class Contest(models.Model):
    """Конкурс. Заводит админ; всё, что можно вывести, выводится (DEC-45).

    Хранятся **три даты** — открытие приёма, дедлайн, объявление итогов.
    Из них считаются фаза, отсчёт дней и год; число заявок считается по
    самим заявкам. Колонок `status`, `days_left`, `year` и `submissions`
    нет и заводить их нельзя: «87 өтінім» стояло при одной настоящей
    заявке, а `days_left=12` протухал назавтра (BR-40a).

    Списки — номинации, этапы, жюри, условия — вынесены в отдельные
    таблицы: админ добавляет строки, а не редактирует кортеж в коде.
    Каждый список отдан наружу свойством (`awards`, `timeline`, `jury`,
    `conditions`), потому что шаблон перебирает их напрямую, а менеджер
    связи в шаблоне не перебирается.
    """

    slug = models.SlugField('slug', max_length=64, unique=True)
    name = models.CharField('атауы', max_length=120)
    subtitle = models.CharField('санаты', max_length=160, blank=True)

    opens_on = models.DateField('қабылдау басталады')
    closes_on = models.DateField('қабылдау жабылады')
    results_on = models.DateField('қорытынды жарияланады')

    # None — конкурс без денежного приза. Ноль означал бы «приз есть, но
    # он нулевой», а это разные вещи.
    prize_kzt = models.PositiveIntegerField('сыйлық (₸)', null=True, blank=True)
    # Афиша — файл в MEDIA_ROOT (`contests/<slug>.png`), грузит админ
    # (BR-47a). Пусто — платформа рисует типографическую афишу по названию.
    poster = models.CharField('афиша', max_length=200, blank=True)
    # Слаг семейства повторяющегося конкурса (BR-47). Пусто — разовый.
    # Связь по слагу, а не по совпадению имён: у выпусков имена расходятся
    # («Жас алдым — 2023» против «Жас алдым — 2026»).
    series = models.SlugField('серия', max_length=64, blank=True)
    description = models.TextField('сипаттамасы', blank=True)

    # Пороги объёма для подачи (BR-22). У конкурса свои — подпись чек-листа
    # берёт числа отсюда, а не вписывает литералом (FR-CONT-07).
    min_chars = models.PositiveIntegerField('ең аз көлемі', default=5_000)
    max_chars = models.PositiveIntegerField('ең көп көлемі', default=15_000)
    # Возрастная вилка **этого конкурса** (BR-48). Любая граница может
    # отсутствовать, обе — тоже: у платформы своего ценза нет и быть не
    # может (DEC-47).
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
    @property
    def awards(self) -> list:
        return list(self.award_set.all())

    @property
    def timeline(self) -> list:
        return list(self.stage_set.all())

    @property
    def jury(self) -> list:
        return list(self.jury_set.all())

    @property
    def conditions(self) -> list:
        """Условия именно этого конкурса, строками. Общие для всех живут
        в `common_rules` и здесь не повторяются (BR-48a)."""
        return [c.text for c in self.condition_set.all()]

    # ── Фаза и сроки (DEC-45) ────────────────────────────────────────────
    @property
    def phase(self) -> str:
        """Одна из `CONTEST_PHASES`. Единственный источник — три даты.

        Четвёртая фаза («қазылар қарауда») заведена потому, что двух не
        хватало: между дедлайном и итогами конкурс либо врал «Белсенді,
        0 күн қалды», либо резко становился «Аяқталды» без победителей.
        """
        today = timezone.localdate()
        if today < self.opens_on:
            return 'upcoming'
        if today <= self.closes_on:
            return 'accepting'
        if today < self.results_on:
            return 'judging'
        return 'finished'

    @property
    def phase_label(self) -> str:
        return CONTEST_PHASE_LABELS[self.phase]

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
    def opens_on_label(self) -> str:
        return kk_date(self.opens_on)

    @property
    def closes_on_label(self) -> str:
        return kk_date(self.closes_on)

    @property
    def results_on_label(self) -> str:
        return kk_date(self.results_on)

    @property
    def year(self) -> int:
        """Год проведения — год объявления итогов. Нужен конкурсной
        биографии автора: «1 жыл бұрын» устаревает каждый день."""
        return self.results_on.year

    @property
    def eligibility_line(self) -> str:
        """Возрастное требование словами. Пусто — конкурс его не ставит.

        Собирать эту строку в шаблоне запрещено: её показывают чек-лист
        подачи, секция условий и чекбокс подтверждения.
        """
        lo, hi = self.min_age, self.max_age
        if lo and hi:
            return f'{lo}-{hi} жас'
        if lo:
            return f'{lo} жастан бастап'
        if hi:
            return f'{hi} жасқа дейін'
        return ''

    @property
    def timing_line(self) -> str:
        """«Что дальше и когда» одной строкой. У завершённого — пусто.

        Спрашивают об этом из трёх мест сразу: строка заявки, конкурсное
        уведомление и рейл. Отсчёта в днях здесь нет — он протухает
        назавтра (BR-40a).
        """
        if self.phase == 'upcoming':
            return f'Қабылдау {self.opens_on_label} басталады'
        if self.phase == 'accepting':
            return (f'Қабылдау {self.closes_on_label} жабылады · '
                    f'жеңімпаздар {self.results_on_label} жарияланады')
        if self.phase == 'judging':
            return f'Жеңімпаздар {self.results_on_label} жарияланады'
        return ''

    # ── Производное от состава ───────────────────────────────────────────
    @property
    def submissions(self) -> int:
        """Число поданных работ — по самим заявкам, а не хранимым числом."""
        return self.submission_set.count()

    @property
    def awards_by_slug(self) -> dict:
        return {a.slug: a for a in self.awards}

    @property
    def grants(self) -> list:
        """Присуждения этого конкурса, в порядке номинаций (DEC-46)."""
        return list(self.grant_set.all())

    @property
    def winner_stories(self) -> list:
        """Произведения-победители, в порядке номинаций, без повторов.

        Автор выводится через работу: второй литерал с именем разошёлся бы
        с первым так же, как хранимый `Author.works` разошёлся с числом
        произведений.
        """
        seen, out = set(), []
        for grant in self.grants:
            if grant.story_id not in seen:
                seen.add(grant.story_id)
                out.append(grant.story)
        return out

    @property
    def winners(self) -> tuple:
        """Слаги победителей — производное от присуждений, не хранимый кортеж."""
        return tuple(s.slug for s in self.winner_stories)

    @property
    def other_editions(self) -> list:
        """Другие выпуски того же семейства, свежие сверху (BR-47).

        Без них завершённый конкурс — тупик: страница кончалась составом
        жюри, и пришедший из поиска уходил ни с чем, хотя приём в выпуск
        этого года шёл прямо сейчас.
        """
        if not self.series:
            return []
        return list(Contest.objects.filter(series=self.series)
                    .exclude(pk=self.pk).order_by('-results_on'))

    @property
    def current_stage(self):
        """Этап, идущий сейчас. Нужен рейлу (FR-CONT-09) — «что происходит
        прямо сейчас» единственное, чего нет в хиро."""
        return next((s for s in self.timeline if s.state == 'active'), None)

    @property
    def next_stage(self):
        return next((s for s in self.timeline if s.state == 'upcoming'), None)


class ContestCondition(models.Model):
    """Условие конкретного конкурса, одной строкой.

    Здесь только то, чем этот конкурс отличается. Общие правила («бір
    автор — бір өтінім» и прочие) живут одним списком в слое запросов и
    в каждый конкурс не переписываются: две рукописные копии одних правил
    уже расходились (BR-48a).
    """

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
    """Этап конкурса. Хранятся даты, состояние выводится.

    Раньше `state` лежал в данных руками и устаревал молча: этап «Өтінім
    қабылдау» конкурса 2023 года стоял `active` в 2026-м.
    """

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
        return f'{self.label} ({self.period})'

    @property
    def period(self) -> str:
        return kk_period(self.starts, self.ends)

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
    """Номинация конкурса и её награда (DEC-46, BR-44/46).

    Набор произвольный: у одного конкурса «Бас жүлде» и «Оқырман
    таңдауы», у другого четыре места. Общего реестра номинаций нет и быть
    не может — он и есть то, чем один конкурс отличается от другого.

    `image` — файл эмблемы в MEDIA_ROOT (`awards/<contest>/<award>.png`),
    его загружает админ; растр, не SVG (файл из `/media/` открывается в
    origin сайта). Пусто — типографическая заглушка. Раму — медальон,
    кольцо, тень — рисует платформа: иначе через десять конкурсов ряд
    наград станет коллекцией чужих JPEG.
    """

    contest = models.ForeignKey(Contest, verbose_name='байқау',
                                on_delete=models.CASCADE,
                                related_name='award_set')
    slug = models.SlugField('slug', max_length=48)
    title = models.CharField('атауы', max_length=80)
    image = models.CharField('эмблема', max_length=200, blank=True)
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

    **Хранится сам акт**, а не список наград у автора. Разница
    принципиальная: «Бас жүлде в Алтын қалам» из данных не вычисляется —
    это решение жюри, и в этом конкурсные награды отличаются от системных
    знаков, которые выводятся (BR-ACH-01). Производной остаётся выдача:
    ряд наград в профиле — запрос по присуждениям.

    Автор не хранится: он у работы. Второе имя разошлось бы с первым.
    """

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
    """Заявка автора на конкурс (BR-23, BR-41).

    Один автор — одна работа на конкретный конкурс; это ограничение
    базы, а не только формы, потому что вторая заявка ломает счёт
    участников и конкурсную биографию.

    Хранится дата подачи, подпись выводится (BR-41a): строка
    «6 ай бұрын» стояла у заявки на конкурс, закрывшийся двумя годами
    раньше, — то есть подача приходилась на полгода позже дедлайна.
    """

    STATUS_CHOICES = [(s, s) for s in SUBMISSION_STATUSES]

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
    # Комментарий жюри. Личный кабинет автора его показывает, чужой
    # профиль — никогда (BR-74a).
    note = models.CharField('қазылар пікірі', max_length=300, blank=True)

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

    @property
    def submitted_label(self) -> str:
        """«5 күн бұрын» — производное от даты, а не хранимая строка."""
        return kk_ago((timezone.localdate() - self.submitted_on).days)


class Follow(models.Model):
    """Подписка одного автора на другого (FR-PROF-10, BR-75).

    Связь маленькая и навигацию не двигает: списки «Жазылулар» и
    «Оқырмандар» публичны, но входа в контент из них нет — читать зовут
    жинақтар и каталог (DEC-31).
    """

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
    """Редакционная подборка — первичный вход в чтение (DEC-31).

    Создаёт **только редакция**: пользовательских подборок на портале нет,
    личное хранение — это «Кітапхана». Подборка отвечает на вопрос «зачем
    читать сейчас», поэтому имя у неё — фраза-состояние, а не жанр.

    Ни `count`, ни `covers` не хранятся: два списка одних и тех же работ
    рано или поздно разъезжаются, а число в интерфейсе не имеет права
    соврать.
    """

    slug = models.SlugField('slug', max_length=64, unique=True)
    name = models.CharField('атауы', max_length=120)
    # OKLCH hue для тонировки карточки и иконки (docs/03 §3.3).
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

    @property
    def stories(self) -> list:
        """Работы подборки в редакционном порядке.

        Через `item_set.all()`, а не через свой `select_related`: свой
        запрос игнорирует `prefetch_related` вызывающей стороны, и десять
        карточек на главной превращаются в десять лишних запросов.
        """
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

    Отдельной таблицей, а не флагом у произведения: неделя проходит, и
    выбор становится историей. Флаг же пришлось бы снимать руками, и
    главная однажды показала бы двух «книг недели» сразу.
    """

    story = models.ForeignKey(Story, verbose_name='шығарма',
                              on_delete=models.CASCADE,
                              related_name='weeks')
    # Голос редакции: почему именно это и почему сейчас.
    editorial_note = models.TextField('редакциядан')
    # Цитата из самой книги — приглашение, а не пересказ.
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
    """Запись в библиотеке читателя (BR-60/61).

    Три вида — «сақталған», «оқу үстінде», «оқылған» — **не
    пересекаются**: работа лежит ровно в одном из них, и это ограничение
    базы, а не только формы.

    Давность хранится датой, подпись выводится: «3 күн бұрын» в колонке
    устаревало бы каждые сутки — та же ошибка, что с `days_left` (DEC-45).
    """

    KIND_CHOICES = [(k, k) for k in LIBRARY_KINDS]

    user = models.ForeignKey('core.User', verbose_name='оқырман',
                             on_delete=models.CASCADE,
                             related_name='library')
    story = models.ForeignKey(Story, verbose_name='шығарма',
                              on_delete=models.CASCADE,
                              related_name='library_entries')
    kind = models.CharField('түрі', max_length=16, choices=KIND_CHOICES)
    added_on = models.DateField('қосылған күні', default=timezone.localdate)
    # Имеет смысл только у «оқу үстінде».
    progress_chapter = models.PositiveSmallIntegerField('бөлім', default=1)

    class Meta:
        ordering = ('-added_on', 'pk')
        constraints = [
            models.UniqueConstraint(fields=('user', 'story'),
                                    name='one_library_entry_per_story'),
        ]
        verbose_name = 'кітапхана жазбасы'
        verbose_name_plural = 'кітапхана жазбалары'

    def __str__(self):
        return f'{self.user.username} · {self.story.slug} ({self.kind})'

    @property
    def added_relative(self) -> str:
        return kk_updated((timezone.localdate() - self.added_on).days)


class ReadingProgress(models.Model):
    """Где читатель остановился. Двигатель «Оқуды жалғастыру» (FR-HOME-02).

    Цитата хранится, хотя в идеале выводится из позиции в тексте: позиции
    у нас пока нет — читалка не сообщает, где закрыли страницу. Когда
    появится, это поле уступит ей место.
    """

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

    @property
    def last_read_days(self) -> int:
        return (timezone.localdate() - self.last_read_on).days


class StoryComment(models.Model):
    """Комментарий к произведению или к конкретной главе (BR-30, BR-33).

    Вложенность **ровно одна**: ответ на ответ превращает обсуждение в
    ветвящееся дерево, которое на телефоне не читается и которое некому
    модерировать.

    Время хранится моментом, подпись выводится. В стабе здесь лежала
    строка («45 мин бұрын», «1 апта бұрын»), написанная руками, — то же
    хранимое производное, что и у уведомления, только заметнее: свежий
    комментарий обязан выглядеть свежим.
    """

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
    # Лайки комментария — счётчик по той же причине, что реакции главы:
    # ставить их пока негде (Ф15), а показывать надо.
    likes = models.PositiveIntegerField('ұнату', default=0)
    created_at = models.DateTimeField('жазылған', default=timezone.now)

    class Meta:
        ordering = ('pk',)
        verbose_name = 'пікір'
        verbose_name_plural = 'пікірлер'

    def __str__(self):
        return f'{self.author.username}: {self.text[:40]}'

    @property
    def replies(self) -> list:
        return list(self.reply_set.select_related('author'))

    @property
    def is_author_badge(self) -> bool:
        """Пишет автор произведения — выводится, не проставляется руками."""
        return self.author_id == self.story.author_id

    @property
    def date(self) -> str:
        """«45 мин бұрын», «2 сағат бұрын», «3 күн бұрын» — из момента."""
        delta = timezone.now() - self.created_at
        return kk_ago(delta.days, delta.seconds // 3600,
                      (delta.seconds % 3600) // 60)

    def belongs_to(self, username: str) -> bool:
        """Свой комментарий: меню предлагает «Жою», а не «Шағым» (BR-33)."""
        return bool(username) and self.author.username == username


class ChapterPoll(models.Model):
    """Необязательный вопрос автора под главой (FR-STORY-13, BR-POLL-01).

    Не квиз: правильного ответа нет и очков не бывает. Смысл в другом — у
    сериальной прозы появляется повод вернуться («кого он выберет?»), а у
    автора обязательство дописать.

    Опрос закрывается публикацией следующей главы (BR-POLL-05): ответ
    приходит там, сюжетом. Поэтому `closed` вычисляется.
    """

    chapter = models.OneToOneField(Chapter, verbose_name='бөлім',
                                   on_delete=models.CASCADE,
                                   related_name='poll')
    question = models.CharField('сұрақ', max_length=200)

    class Meta:
        verbose_name = 'бөлім сауалнамасы'
        verbose_name_plural = 'бөлім сауалнамалары'

    def __str__(self):
        return self.question

    @property
    def closed(self) -> bool:
        return self.chapter.story.chapter_set.filter(
            number__gt=self.chapter.number).exists()

    @property
    def answer_chapter(self):
        """Глава, где ответ уже есть, — куда вести дочитавшего."""
        return self.chapter.number + 1 if self.closed else None

    @property
    def options(self) -> list:
        return list(self.option_set.all())

    @property
    def total_votes(self) -> int:
        return sum(o.votes for o in self.options)

    @property
    def results(self) -> list:
        total = self.total_votes or 1
        return [
            {
                'slug':    o.slug,
                'text':    o.text,
                'count':   o.votes,
                'percent': round(o.votes * 100 / total),
                # Свой голос появится вместе с возможностью голосовать (Ф15):
                # сейчас его негде поставить, и «мой вариант» ничей.
                'mine':    False,
            }
            for o in self.options
        ]


class PollOption(models.Model):
    """Вариант ответа. До четырёх на опрос (BR-POLL-02) — лимит формы, а не
    схемы: база не то место, где автору отказывают в пятом варианте."""

    poll = models.ForeignKey(ChapterPoll, verbose_name='сауалнама',
                             on_delete=models.CASCADE,
                             related_name='option_set')
    slug = models.SlugField('slug', max_length=32)
    text = models.CharField('мәтіні', max_length=160)
    # Счётчик, а не голоса: голосовать пока негде (та же причина, что у
    # реакций главы).
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


class Notification(models.Model):
    """Событие в ленте автора (FR-NOTIF-01, BR-70…72).

    **Хранится «когда», выводится «как давно»** — подпись и группа
    считаются из момента. Прежние поля `when="5 күн бұрын"` и
    `bucket="past_week"` устаревали назавтра.

    **Уведомление ведёт к своему предмету** (BR-72a): имя конкурса или
    работы приходит из объекта, а в `text` лежит только событие.
    Исключений два, и оба про чужие слова: у комментария в тексте цитата
    читателя, у отклонённой модерации — причина от модератора (BR-11).
    """

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
    # Исход модерации **хранится** (BR-72b): это акт модератора, а не
    # состояние работы. Вывести его из `Story.status` нельзя — статус
    # живёт дальше события, и вчерашний отказ завтра сказал бы
    # «Модерацияда». Пусто — решения ещё нет.
    outcome = models.CharField('модерация нәтижесі', max_length=16, blank=True,
                               choices=OUTCOME_CHOICES)
    text = models.CharField('оқиға', max_length=300, blank=True)
    read = models.BooleanField('оқылды', default=False)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'хабарлама'
        verbose_name_plural = 'хабарламалар'

    def __str__(self):
        return f'{self.user.username} · {self.kind}'

    @property
    def days_ago(self) -> int:
        return (timezone.localdate() - timezone.localtime(self.created_at).date()).days

    @property
    def when(self) -> str:
        delta = timezone.now() - self.created_at
        return kk_ago(self.days_ago, delta.seconds // 3600)

    @property
    def bucket(self) -> str:
        """Группа FR-NOTIF-01 или '' — событие старше недели не попадает ни
        в одну: групп ровно три, и четвёртой («раньше») в требовании нет,
        значит неделя и есть глубина ленты."""
        days = self.days_ago
        if days <= 0:
            return 'today'
        if days == 1:
            return 'yesterday'
        return 'past_week' if days <= 7 else ''

    @property
    def outcome_label(self) -> str:
        """Подпись исхода — из реестра, а не из шаблона: то же правило, что
        у статусов работы (BR-10) и фаз конкурса (BR-40)."""
        return MODERATION_OUTCOME_LABELS.get(self.outcome, '')


class SchoolLink(models.Model):
    """Ссылка «Авторлар мектебі» (DEC-22).

    Страницы школы у платформы нет и не будет: есть блок ссылок на то,
    что уже написано другими. Таблицей — потому что список меняется чаще,
    чем выходит релиз.
    """

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
