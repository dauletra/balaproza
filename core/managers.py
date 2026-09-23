"""QuerySet'ы моделей: выдача, выраженная там, где она исполняется.

Цепочка `Story.objects.public().for_card()` комбинируется: её можно
продолжить фильтром, посчитать `.count()` и нарезать на странице.

Аннотации живут тоже здесь: свойства модели читают их и без них уходят в
запрос на каждую строку — приезжая вместе с выдачей, аннотация перестаёт
быть тем, что надо вспомнить.

Модели импортируются внутри методов: `core/models/` подключает этот модуль, и
верхнеуровневый импорт был бы циклом.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db.models import (
    BooleanField,
    Count,
    DateTimeField,
    Exists,
    F,
    IntegerField,
    Max,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce, Lower
from django.utils import timezone

from .domain.catalog import AUDIENCE_ORDER, NEW_AUTHOR_DAYS, PUBLIC_STATUSES

logger = logging.getLogger(__name__)

# Знаков в минуту: темп, комфортный для казахской прозы. То же число, что в
# `Story.read_minutes`, в двух видах — одна форма нужна объекту, вторая базе.
CHARS_PER_MINUTE = 900


def from_annotation(instance, annotation: str, compute):
    """Готовое из выдачи — или свой запрос, но не молча.

    Одна дверь контракта «аннотация или запрос»: промах пишется в лог в
    `DEBUG`, а в проде отвечает правильно ценой запроса. Строка в логе не
    объявляет ошибку — у одиночного объекта запрос законен; ошибку
    показывает **повтор**, двадцать одинаковых строк и есть N+1.
    """
    value = getattr(instance, annotation, None)
    if value is not None:
        return value
    if settings.DEBUG:
        logger.warning('%s без аннотации `%s` — значение считается отдельным '
                       'запросом (%s)', type(instance).__name__, annotation,
                       instance)
    return compute()


def viewer_mark(instance, mark: str, default):
    """Метка «что сделал именно этот читатель» — или умолчание, но не тихо.

    Отличие от `from_annotation` принципиальное: там промах стоит запроса,
    здесь его **нельзя досчитать** — объект не знает, кто на него смотрит,
    и любой ответ будет про кого-то другого. Поэтому метка ставится
    всегда, гостю тоже (`for_viewer(None)` проставляет её значениями), а
    промах пишется в лог как расхождение, а не как цена.
    """
    if hasattr(instance, mark):
        return getattr(instance, mark)
    if settings.DEBUG:
        logger.warning('Метка `%s` не проставлена на %s — действие читателя '
                       'показано несделанным', mark, type(instance).__name__)
    return default


def viewer_choice(instance, mark: str) -> str:
    """Что выбрал этот читатель: реакция на главе, голос в опросе. Метку
    ставит `queries/story.py`, и промах здесь не удорожает страницу, а
    **врёт** — пустая строка значит «не голосовал»."""
    return viewer_mark(instance, mark, '')


def chapter_count_subquery(story_ref: str = 'pk', *, published_only: bool = False):
    """Сколько частей у работы — подзапросом, для аннотации `chapter_count`.

    `story_ref` — чем внешняя выдача ссылается на произведение; выдачам, где
    строка **про** работу (полка, прогресс), передаётся `'story'`.
    Подзапросом, а не `Count` по join: фильтр по тегам размножил бы строки.

    `published_only` разводит два разных вопроса. Читателю «N бөлім»
    означает «столько я могу прочесть», и недописанная глава в это число не
    входит; автору в кабинете — «столько у меня есть», включая ту, что ещё
    у модератора. До разделения ревизий вопрос был один, потому что и
    ответ был один.
    """
    from .models import Chapter

    rows = Chapter.objects.filter(story=OuterRef(story_ref))
    if published_only:
        rows = rows.filter(published_revision__isnull=False)

    return Coalesce(
        Subquery(
            rows.values('story').annotate(n=Count('pk')).values('n')[:1],
            output_field=IntegerField(),
        ),
        Value(0),
    )


class StoryQuerySet(QuerySet):
    """Произведения: публичность, карточка, объём чтения, порядок."""

    def public(self):
        """Только то, что видит читатель. По
        `PUBLIC_STATUSES`, а не по литералу `'Published'`: публичный сериал
        носит `Completed` или `OnProcess`, и сравнение со строкой
        молча выкидывает из выдачи все сериалы, отдавая 200."""
        return self.filter(status__in=PUBLIC_STATUSES)

    def for_row(self):
        """Карточка **без тегов**: автор и жанры.

        Узкая карточка ряда (`book_card_small.html`) тегов не показывает
        вовсе, а `prefetch_related` стоит отдельного запроса на каждую
        выдачу — три ряда главной платили три запроса за то, чего на
        экране нет.
        """
        return self.select_related('author', 'primary_genre', 'secondary_genre')

    def for_card(self):
        """Всё, что спрашивает карточка каталога: автор, жанры, теги. Без
        этого страница из двадцати карточек делает под сотню запросов."""
        return self.for_row().prefetch_related('tags')

    def with_reading_effort(self):
        """«Сколько это читать» и три знака карточки — одной выдачей. Объём
        подзапросом, а не `Sum` по join: с фильтром по тегам join размножит
        строки, и сумма знаков вырастет кратно их числу — беззвучно."""
        from .models import Chapter, Submission

        # Объём **опубликованного**: считается по одобренной
        # ревизии, а не по рабочей копии главы. Иначе карточка обещала бы
        # читателю знаки, которых он не увидит, — недописанная глава
        # сериала прибавляла бы минуты чтения ещё до модерации.
        written = Subquery(
            Chapter.objects.filter(story=OuterRef('pk'),
                                   published_revision__isnull=False)
            .values('story')
            .annotate(total=Sum('published_revision__char_count'))
            .values('total')[:1],
            output_field=IntegerField(),
        )
        return self.annotate(
            effective_chars=Coalesce(written, Value(0)),
            # Два разных числа, потому что это два разных вопроса:
            # `chapter_count` — сколько читатель может прочесть, и оно
            # обязано сходиться с `effective_chars` рядом; `written_*` —
            # сколько автор написал, включая то, что ждёт модератора.
            chapter_count=chapter_count_subquery(published_only=True),
            written_chapter_count=chapter_count_subquery(),
        ).annotate(
            # Округление вверх целочисленным делением — тот же расчёт, что в
            # `Story.read_minutes`.
            read_minutes_db=(F('effective_chars') + Value(CHARS_PER_MINUTE - 1))
            / Value(CHARS_PER_MINUTE),
            # Знак «Байқауға қатысады» — участие в **незавершённом**
            # конкурсе. Подхватывает `Story.badges`.
            in_open_contest=Exists(
                Submission.objects.filter(
                    story=OuterRef('pk'),
                    contest__results_on__gt=timezone.localdate())),
            # Отдельно от объёма: глава с пустым телом даёт ноль знаков, но
            # работа уже не пустой черновик, и полоса внимания звала бы
            # автора писать то, что он начал.
            has_any_chapter=Exists(Chapter.objects.filter(story=OuterRef('pk'))),
            # «Когда читателю показали последнюю часть» — не `updated_at`:
            # тот двигает любое сохранение строки, включая пересчёт статуса
            # и решение модератора о чём угодно, и «жаңарды» врало бы на
            # работе, где ничего нового не вышло. Берём дату решения по
            # опубликованной ревизии — ровно момент, когда часть
            # стала видна. Подзапросом, как и всё здесь: `Max` по join
            # размножился бы фильтром по тегам.
            last_published=Subquery(
                Chapter.objects.filter(story=OuterRef('pk'),
                                       published_revision__isnull=False)
                .values('story')
                .annotate(last=Max('published_revision__decided_at'))
                .values('last')[:1],
                output_field=DateTimeField(),
            ),
        )

    def for_viewer(self, viewer):
        """Метки этого читателя на карточке: лежит ли работа у него на
        полке и докуда он её прочёл.

        Обе — `for_viewer(None)` тоже, значениями: карточка спрашивает их
        всегда, и незаданная метка не «неизвестно», а молчаливое «нет»
        (см. `viewer_mark`). Гость получает `False`/`0` от базы, а не от
        пропущенной аннотации, и промах остаётся видимым.

        `Exists`, а не `Count`: вопрос булев, а `UniqueConstraint`
        `one_library_entry_per_story` и так не даёт второй строки. Прогресс
        по умолчанию 0, а не 1, как у полки: там «на полке, но не открыта»
        честно первая глава, здесь ноль означает «не начинал», и полосы
        прогресса не будет вовсе.
        """
        from .models import LibraryEntry, ReadingProgress

        if viewer is None:
            return self.annotate(
                viewer_saved=Value(False, output_field=BooleanField()),
                viewer_chapter=Value(0, output_field=IntegerField()))

        return self.annotate(
            viewer_saved=Exists(LibraryEntry.objects.filter(
                user=viewer, story=OuterRef('pk'))),
            viewer_chapter=Coalesce(
                Subquery(
                    ReadingProgress.objects.filter(
                        user=viewer, story=OuterRef('pk'),
                    ).values('current_chapter')[:1],
                    output_field=IntegerField(),
                ),
                Value(0),
            ),
        )

    def by_author(self, author):
        """Работы одного автора. Принимает `User` или ник строкой — строка
        ради вызовов, у которых объекта на руках нет."""
        if not author:
            return self.none()
        if isinstance(author, str):
            return self.filter(author__username=author)
        return self.filter(author=author)

    def sorted_by(self, sort: str):
        """Порядок выдачи. `pk` вторым ключом везде, где первый допускает
        ничью: без него Postgres вправе вернуть равные строки в любом
        порядке, и каталог перетасовывался бы между запросами."""
        if sort == 'alphabet':
            return self.order_by(Lower('title'), 'pk')
        if sort == 'recent':
            return self.order_by('-created_at', '-pk')
        if sort == 'popularity':
            return self.order_by('-views', 'pk')
        return self.order_by('-recent_views', 'pk')

    def latest_edited(self):
        """«Что я трогал последним» — порядок авторского кабинета.
        `nulls_last` обязателен: Postgres при `DESC` ставит `NULL` первыми,
        и работы без даты правки уехали бы наверх вместо конца."""
        return self.order_by(F('updated_at').desc(nulls_last=True), 'pk')

    # ── Оси каталога ─────────────────────────────────────────────────────
    def with_audience(self, audience: str):
        """Ось «Жасың» — **накопительная**: читателю четырнадцати лет
        доступно и то, что помечено 10+. Безопасное направление сохраняется —
        младшая вилка старших отметок не видит."""
        if audience not in AUDIENCE_ORDER:
            return self
        allowed = AUDIENCE_ORDER[:AUDIENCE_ORDER.index(audience) + 1]
        return self.filter(audience__in=allowed)

    def with_length(self, length: str):
        """Ось «Оқу уақыты». Требует `with_reading_effort()` до себя."""
        if length == 'short':
            return self.filter(read_minutes_db__lte=10)
        if length == 'medium':
            return self.filter(read_minutes_db__gt=10, read_minutes_db__lte=30)
        if length == 'long':
            return self.filter(read_minutes_db__gt=30)
        return self

    def of_kind(self, kind: str):
        """Ось «Түрі». Значения «любой сериал» нет намеренно."""
        if kind == 'single':
            return self.filter(format='single')
        if kind == 'done':
            return self.filter(format='serial', status='Completed')
        if kind == 'ongoing':
            return self.filter(format='serial', status='OnProcess')
        return self

    def with_badge(self, badge: str):
        """Ось «Белгі»: знак редакции хранится, знак конкурса выводится."""
        if badge == 'editorial':
            return self.filter(is_editorial_pick=True)
        if badge == 'contest':
            # Участие в **незавершённом** конкурсе, а не в идущем приёме:
            # работа, ушедшая к жюри, всё ещё в конкурсе.
            return self.filter(
                submissions__contest__results_on__gt=timezone.localdate()
            ).distinct()
        return self

    def by_author_tier(self, tier: str):
        """Ось «Автор»: работы тех, кто пришёл недавно.

        Граница считается от сегодня, а не хранится: «новое имя» — это
        возраст аккаунта, и колонка с ним устаревала бы каждые сутки.
        """
        if tier == 'new':
            edge = timezone.now() - timedelta(days=NEW_AUTHOR_DAYS)
            return self.filter(author__date_joined__gte=edge)
        return self

    def matching(self, query: str):
        """Поиск подстрокой (`ILIKE`, триграммные индексы) по четырём
        местам: название, аннотация, имя автора и тег.

        Названия и автора не хватало. Читатель ищет не по имени работы,
        которого он не знает, а по тому, о чём она: «мектеп туралы»,
        «қорқынышты». Аннотация — единственное место, где это написано
        словами автора, а тег — единственное, где это написано коротко.

        Заодно это чинило расхождение: быстрый поиск (Cmd+K) теги искал,
        а каталог — нет, и одно и то же слово давало разный результат в
        двух местах одного портала.

        Тег — `Exists`, а не join: у работы их до десяти, и совпади два,
        join вернул бы её дважды. `distinct()` решил бы то же, но ценой
        дедупликации всей выдачи с её аннотациями.

        Только **принятые** теги: непринятый публично не существует, и
        находиться по нему работа не должна.
        """
        from .models import StoryTag

        q = (query or '').strip()
        if not q:
            return self
        tagged = Exists(StoryTag.objects.filter(
            story=OuterRef('pk'), tag__status='accepted',
        ).filter(Q(tag__name__icontains=q) | Q(tag__slug__icontains=q)))
        return self.filter(Q(title__icontains=q)
                           | Q(annotation__icontains=q)
                           | Q(author__pen_name__icontains=q)
                           | Q(author__username__icontains=q)
                           | tagged)

    def in_genre(self, slug: str):
        if not slug:
            return self
        return self.filter(Q(primary_genre__slug=slug)
                           | Q(secondary_genre__slug=slug))

    def with_tag(self, slug: str):
        """Оба условия — на одной связке: у многозначного
        отношения это «тег с таким слагом И принятый», то есть непринятый
        слаг не находит ничего. Отдельным `.exists()` та же проверка стоила
        бы запроса на каждый из семи вызовов страницы тега."""
        if not slug:
            return self
        return self.filter(tags__slug=slug, tags__status='accepted')


def _winner_cards() -> Prefetch:
    """Работы-победители той же выборкой, что карточка каталога — только для
    страницы конкурса, где победитель показан карточкой. Списку конкурсов не
    даётся: его карточка называет победителя строкой."""
    from .models import Story

    return Prefetch('grant_set__story',
                    queryset=Story.objects.for_card().with_reading_effort())


class ContestQuerySet(QuerySet):
    """Конкурсы: число заявок и три календарных вопроса. Фазы выражены для
    базы теми же тремя датами, что и `Contest.phase` — разное «идёт
    ли приём» в выдаче и на странице читатель увидит сразу."""

    def with_counts(self):
        """Число заявок аннотацией — его подхватывает `Contest.submissions`.
        Без неё каждая карточка списка спрашивает своё `COUNT`."""
        return self.annotate(submission_count=Count('submission_set'))

    def for_card(self):
        """Конкурс для карточки списка: фаза, приз, победители. Номинации,
        этапы, жюри и условия карточка не показывает — тянуть их значит
        платить четыре запроса за то, чего на экране нет."""
        return self.with_counts().prefetch_related('grant_set__story')

    def full(self):
        """Конкурс со всем составом — для его собственной страницы."""
        return self.with_counts().prefetch_related(
            'award_set', 'stage_set', 'jury_set', 'condition_set',
            'grant_set__award', _winner_cards())

    def accepting(self):
        """Идёт приём работ — это и решает кнопку «Қатысу»."""
        today = timezone.localdate()
        return self.filter(opens_on__lte=today, closes_on__gte=today)

    def unfinished(self):
        """Итоги ещё не объявлены. **Не то же самое, что `accepting`**: в
        судействе конкурс тоже не завершён, но подать в него уже нельзя."""
        return self.filter(results_on__gt=timezone.localdate())

    def finished(self):
        return self.filter(results_on__lte=timezone.localdate())
