"""Работа и её главы: рабочая копия, ревизии, реакции и опросы в конце главы."""

from functools import cached_property

from django.contrib.postgres.indexes import GinIndex
from django.db import models, transaction
from django.utils import timezone

from ..domain.catalog import BADGE_LABELS, PUBLIC_STATUSES
from ..domain.notifications import MODERATION_OUTCOMES
from ..domain.story import (
    REACTIONS,
    REACTIONS_BY_SLUG,
    REVISION_STATE_LABELS,
    REVISION_STATES,
    STORY_FORMAT_LABELS,
    STORY_FORMATS,
    STORY_STATUS_LABELS,
    STORY_STATUSES,
    story_status,
)
from ..managers import StoryQuerySet, from_annotation, viewer_choice, viewer_mark
from ..uploads import _ext, validate_raster_image
from .moderation import ModerationClaim, ModerationDecision
from .social import Notification


def story_cover_path(instance, filename):
    """`covers/<slug>.<ext>`: загруженное имя попало бы в публичный URL
    навсегда, а слаг уникален и читается."""
    return f'covers/{instance.slug}{_ext(filename)}'


class Story(models.Model):
    """Произведение. Центральный объект портала.

    Что здесь не хранится и почему — docs/architecture.md. Что хранится
    вопреки правилу «производное не хранится» — отмечено на месте.
    """

    STATUS_CHOICES = [(s, STORY_STATUS_LABELS[s]) for s in STORY_STATUSES]
    FORMAT_CHOICES = [(f, STORY_FORMAT_LABELS[f]) for f in STORY_FORMATS]

    objects = StoryQuerySet.as_manager()

    slug = models.SlugField('slug', max_length=64, unique=True)
    title = models.CharField('атауы', max_length=120)
    author = models.ForeignKey('core.User', verbose_name='авторы',
                               on_delete=models.CASCADE, related_name='stories')
    # Пусто — `cover_placeholder.html` рисует плашку по тону жанра.
    cover = models.FileField('мұқаба', upload_to=story_cover_path, blank=True,
                             max_length=200, validators=[validate_raster_image])
    annotation = models.TextField('аннотация', blank=True)

    primary_genre = models.ForeignKey('core.Genre', verbose_name='негізгі жанр',
                                      on_delete=models.PROTECT,
                                      related_name='primary_stories')
    # Второй жанр необязателен: у произведения бывает один.
    secondary_genre = models.ForeignKey('core.Genre', verbose_name='қосымша жанр',
                                        on_delete=models.PROTECT,
                                        related_name='secondary_stories',
                                        null=True, blank=True)
    # До 10 на произведение — правило формы, а не схемы.
    # `through='core.StoryTag'`, а не голое M2M: «Жаңалары» у тега держится
    # на дате связки.
    tags = models.ManyToManyField('core.Tag', through='core.StoryTag', verbose_name='тегтер',
                                  blank=True, related_name='stories')

    status = models.CharField('мәртебесі', max_length=16,
                              choices=STATUS_CHOICES, default='NotPublished')
    # Без дефолта: пустая строка значит «автор ещё не выбрал» —
    # отдельное состояние, а не синоним «10+». На детской платформе дефолт
    # проставлял бы отметку за человека.
    audience = models.CharField('жас белгісі', max_length=8, blank=True)
    format = models.CharField('түрі', max_length=8, choices=FORMAT_CHOICES,
                              default='serial')

    # Накопленный счёт за всё время. Колонка, а не COUNT по журналу: журнал
    # держит только окно, за его пределами считать уже нечего.
    views = models.PositiveIntegerField('оқылым', default=0)
    # Просмотры за окно — ось «Қазір танымал». Денормализовано:
    # агрегат по журналу с окном считался бы на каждой странице каталога.
    # Инвариант `recent_views <= views`. Растёт по строкам `StoryView` и
    # ими же пересчитывается вниз (`recount_views`) — как `Story.likes` и
    # `User.followers`, колонка под ORDER BY, а не независимое число.
    recent_views = models.PositiveIntegerField('14 күндегі оқылым', default=0)
    # Голоса за реакции по всем главам и комментарии — обе
    # колонки, а не вычисление: у работы без текста глав нет вовсе, и счёт
    # по главам обнулил бы ей метрику в каталоге.
    likes = models.PositiveIntegerField('лайк', default=0)
    comments = models.PositiveIntegerField('пікір', default=0)

    # «Дописано» — слово автора о своей работе, а не исход модерации.
    # Отдельным полем, потому что `status` теперь пересчитывается
    # по главам и хранить в нём авторское решение больше негде.
    completed_by_author = models.BooleanField('аяқталды деп белгіленген',
                                              default=False)

    # Акт редакции, из данных не выводится, как `AwardGrant`.
    # Второй знак каталога, «Байқауға қатысады», наоборот выводится.
    is_editorial_pick = models.BooleanField('редакция таңдауы', default=False)

    created_at = models.DateTimeField('жасалған', auto_now_add=True)
    # «Когда трогали» — дата, а не число дней: дельта устаревает
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
            # «Ең көп оқылған», «Жаңалары» (она же дефолт тега).
            models.Index(fields=['-recent_views']),
            models.Index(fields=['-views']),
            models.Index(fields=['-created_at']),
            # Поиск по названию — тот же ILIKE с подстрокой, что и по автору.
            GinIndex(fields=['title'], name='story_title_trgm',
                     opclasses=['gin_trgm_ops']),
            # И по аннотации: читатель ищет не по имени работы, которого
            # он не знает, а по тому, о чём она. Аннотация — единственное
            # место, где это написано словами автора, и без индекса
            # подстрока по ней читает таблицу целиком.
            GinIndex(fields=['annotation'], name='story_annotation_trgm',
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

    # ── Формат ───────────────────────────────────────────────────────────
    @property
    def is_single(self) -> bool:
        return self.format == 'single'

    @property
    def is_serial(self) -> bool:
        return self.format != 'single'

    @property
    def chapters(self) -> int:
        """Сколько частей **может прочесть читатель**.

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
        """Лежит ли работа на полке того, кто смотрит. Метку ставит
        `for_viewer`; незаданная значит «нет», и это молчаливо неверный
        ответ, поэтому промах пишется в лог (`viewer_mark`), а не
        досчитывается: объект не знает, кто на него смотрит.
        """
        return viewer_mark(self, 'viewer_saved', False)

    @property
    def read_up_to(self) -> int:
        """Докуда дочитал тот, кто смотрит; 0 — не начинал."""
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
        дата решения по опубликованной ревизии, ровно момент, с
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
        определению. Отдаёт `pk`, а не `number`: адрес кабинета
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
        'Published' — иначе из выдачи молча пропадают все сериалы."""
        return self.status in PUBLIC_STATUSES

    def refresh_status(self) -> str:
        """Пересчитать `status` по главам и сохранить, если сдвинулся.

        Единственная дверь, через которую колонка меняется. Раньше статус
        назначали — модерация, форма настроек, админка, — и каждое из мест
        отвечало за свой кусок правды. Теперь правда одна: что опубликовано
        и что ждёт очереди.
        """
        chapters = list(self.chapter_set.all())
        # Возвращённое отличается от нетронутого черновика, и
        # отличие это — последнее решение модератора, а не отдельная
        # колонка: колонка разошлась бы с журналом, где то же решение уже
        # записано.
        #
        # Из журнала решений, а не из ленты уведомлений. Лента чистится
        # (`prune_notifications`, 30 дней), и возвращённая работа, которую
        # автор открыл через месяц, при первом же пересчёте молча
        # становилась черновиком — без следа того, что её возвращали.
        last_outcome = (ModerationDecision.objects
                        .filter(story=self)
                        .order_by('-decided_at', '-pk')
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
        статус без уведомления оставляет автора гадать. Здесь, а не во
        вью раздела `/moderation/`: решение одно, откуда бы его ни приняли.
        Причина обязательна у обоих отрицательных исходов.

        Решается **поданный текст**, а не работа целиком:
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
            raise ValueError('Себепсіз қайтаруға болмайды.')

        from ..queries.notifications import notify_new_chapter

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
            # Акт решения — с тем, кто его принял. Пишется рядом с
            # уведомлением и в той же транзакции: это две стороны одного
            # события, и разойтись они не должны.
            ModerationDecision.objects.create(
                story=self, moderator=moderator, outcome=outcome,
                reason=reason, chapters=len(pending))
            # Метка «взял в работу» снимается решением: она про намерение
            # прочесть, а прочтение состоялось.
            ModerationClaim.objects.filter(story=self).delete()
            # Акт выше пишется **до** пересчёта: статус `NeedsWork`
            # выводится из последнего решения в журнале. Обратный порядок
            # оставлял бы возвращённую работу неотличимой от нетронутого
            # черновика до следующей правки.
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

    def take_down(self, reason: str, moderator=None) -> 'Notification':
        """Снять уже опубликованное с публикации по жалобе.

        Не `apply_moderation`: та решает поданную ревизию и без
        `pending` падает — здесь наоборот, ревизии может не быть вовсе,
        решается то, что уже стоит у читателя. Общее с ней — форма: акт в
        журнале, уведомление и пересчёт статуса одной транзакцией. Текст
        остаётся у автора, снимается только видимость (`published_revision`),
        тем же способом, каким её даёт публикация ревизии, — поэтому
        `refresh_status()` по акту `rejected` сам приводит работу в
        `NeedsWork`, ничего изобретать не пришлось.

        Акт в журнале обязателен, и не ради истории: без него статус
        держался на одном уведомлении, и через месяц, когда ленту чистят,
        снятая работа становилась черновиком, а причина снятия пропадала с
        экрана автора. Имя модератора пишется в акт, а не в уведомление:
        решение платформы автору не подписывается, как и у
        `apply_moderation`.
        """
        reason = reason.strip()
        if not reason:
            raise ValueError('Себепсіз алып тастауға болмайды.')
        with transaction.atomic():
            taken = self.chapter_set.filter(published_revision__isnull=False) \
                .update(published_revision=None)
            ModerationDecision.objects.create(
                story=self, moderator=moderator, outcome='rejected',
                reason=reason, chapters=taken)
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
        """Подписи знаков на карточке. Редакционный хранится — это
        акт человека; конкурсный выводится из заявки в **незавершённый**
        конкурс: ушедшая к жюри работа ещё участвует."""
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

    Ось «Қазір танымал» обещает просмотры за две недели, но без дат
    убывать им было
    не от чего: оба счётчика росли вместе, и окно со временем сходилось с
    «Ең көп оқылған» — две оси показывали бы один и тот же порядок.

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
    viewer = models.ForeignKey('core.User', verbose_name='оқырман', null=True,
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
    """Глава — единица публикации.

    Здесь лежит **рабочая копия** автора: `title`/`body`/`char_count` — то,
    что он сейчас пишет, и то, что правит автосохранение. Читателю она не
    показывается никогда. Читатель видит `published_revision` — снимок,
    который прошёл модератора.

    Разделение появилось потому, что до него это была одна строка: правка
    одобренного текста доезжала до читателя мгновенно, а новая глава
    публичного сериала публиковалась сама.
    Модерация выдавалась работе один раз и дальше ни на что не влияла.
    """

    # Метка зрителя, её ставит `queries/story.chapters_of`. По умолчанию
    # **читатель**: промах метки должен приводить к «показать меньше», а не
    # к утечке неодобренного текста.
    as_author = False

    story = models.ForeignKey(Story, verbose_name='шығарма',
                              on_delete=models.CASCADE)
    # Читательский номер — контиг 1..N, пересчитывается вслед за `position`
    # (`queries/write._renumber_chapters`). Кабинет адресует главу
    # не им, а `pk`: номер сдвигается при удалении/перестановке
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
        # Автор видел 1588 при наборе и 1646 после
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
        `queries/story._attach_my_reaction`, гостю тоже."""
        return viewer_choice(self, '_my_reaction')

    # ── Опубликованное против рабочего ───────────────────────────
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

        Читателю — одобренное; автору и модератору, открывшим предпросмотр,
 — рабочая копия: они смотрят на то, что пишется, иначе
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
    """Один снимок текста главы и его судьба.

    Ревизия — то, что модератор читает и одобряет. Именно она, а не глава,
    проходит модерацию: у главы за жизнь их много, и каждая правка
    опубликованного текста заводит новую, пока не одобренную.

    Причина отказа здесь не хранится — она живёт в `Notification.text`:
 у события есть автор и адресат, у снимка текста их нет.
    """

    STATE_CHOICES = [(s, REVISION_STATE_LABELS[s]) for s in REVISION_STATES]

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


class ChapterReaction(models.Model):
    """Счётчик одной реакции на главе: агрегат по
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
    """Кто поставил какую реакцию на главе. Одна активная
    на пользователя и главу — ограничение базы: повторный клик снимает,
    клик по другой заменяет. `Story.likes` считает голоса."""

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


class ChapterPoll(models.Model):
    """Необязательный вопрос автора под главой. Не
    квиз: правильного ответа нет и очков не бывает. Опрос закрывается
    публикацией следующей главы, поэтому `closed` вычисляется."""

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
        """Опрос закрыт публикацией следующей главы.

        `cached_property`, а не `property`: страница спрашивает это пять
        раз — сам блок, подпись «жауап келесі бөлімде», ссылка на неё и
        вид каждого варианта, — и каждое обращение шло в базу отдельным
        `EXISTS`. Тот же приём, что у состава конкурса.
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
    """Вариант ответа. До четырёх на опрос — лимит формы, а не
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
    """Голос читателя в опросе главы. Одна ставка на весь опрос,
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
