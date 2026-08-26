"""Каталог, поиск, жанры: единый движок выдачи (DEC-27, DEC-36).

Здесь живут правила, по которым читателю показывают произведения. Их
четыре, и каждое однажды нарушалось именно потому, что лежало не в одном
месте:

- **в публичную выдачу идут только публичные статусы** (DEC-23) — до
  этого «Модерацияда» открыто лежала в каталоге;
- **ось «Жасың» накопительная** (DEC-38) — точное совпадение прятало от
  четырнадцатилетнего три четверти каталога;
- **дефолт сортировки — окно в 14 дней** (DEC-36), а не накопленные
  просмотры;
- **pending-тег публичную выдачу не фильтрует** (BR-TAG-07).

Объём чтения считается в базе, а не в Python. Соблазн отфильтровать
двадцать карточек на стороне приложения велик, но ось «оқу уақыты» —
это `WHERE`, и написанная списком она перестаёт работать ровно тогда,
когда в каталоге появится третья страница.
"""

from django.core.cache import cache
from django.db.models import (
    Case,
    Count,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Lower
from django.utils import timezone

from ..domain.catalog import (
    AUDIENCE_ORDER,
    CATALOG_DEFAULT_SORT,
    NEW_AUTHOR_FOLLOWERS,
    PUBLIC_STATUSES,
)
from ..models import Chapter, Genre, Story, Submission, Tag, User
from .site import REFERENCE_TTL

# Знаков в минуту: темп, комфортный для казахской прозы. Живёт рядом с
# моделью (`Story.read_minutes`) и здесь — одно и то же число в двух
# видах, потому что одна форма нужна объекту, вторая базе.
CHARS_PER_MINUTE = 900
# Оценка объёма ненаписанной части: у четырёх сериалов каталога текста
# нет вовсе, и ноль знаков превратил бы их в «3 минут оқу».
CHARS_PER_DECLARED_CHAPTER = 1800


def _reading_effort(qs):
    """Аннотация «сколько это читать» — минуты, как их видит читатель.

    Объём берётся **подзапросом**, а не `Sum` по join: как только к
    выдаче добавится фильтр по тегам, join размножит строки, и сумма
    знаков вырастет во столько раз, сколько у работы тегов. Ошибка
    беззвучная — просто часть каталога уезжает не в свой фильтр.
    """
    written = Subquery(
        Chapter.objects.filter(story=OuterRef('pk')).values('story')
        .annotate(total=Sum('char_count')).values('total')[:1],
        output_field=IntegerField(),
    )
    return qs.annotate(
        written_chars=Coalesce(written, Value(0)),
    ).annotate(
        effective_chars=Case(
            When(written_chars__gt=0, then=F('written_chars')),
            default=F('chapters') * Value(CHARS_PER_DECLARED_CHAPTER),
            output_field=IntegerField(),
        ),
    ).annotate(
        # Округление вверх целочисленным делением — тот же расчёт, что в
        # `Story.read_minutes`; нижняя граница в три минуты на бакеты не
        # влияет, короткое и так короткое.
        read_minutes_db=(F('effective_chars') + Value(CHARS_PER_MINUTE - 1))
        / Value(CHARS_PER_MINUTE),
        # Участвует ли работа в незавершённом конкурсе — знак «Байқауға
        # қатысады». `Story.badges` подхватывает эту аннотацию: без неё
        # каждая карточка спрашивала бы базу отдельно.
        in_open_contest=Exists(
            Submission.objects.filter(
                story=OuterRef('pk'),
                contest__results_on__gt=timezone.localdate())),
        # Есть ли хоть одна записанная глава — подхватывает
        # `Story.has_chapters`. Отдельно от объёма намеренно: глава с
        # пустым телом даёт ноль знаков, но работа при этом уже не пустой
        # черновик, и полоса внимания в кабинете позвала бы автора писать
        # то, что он начал.
        has_any_chapter=Exists(Chapter.objects.filter(story=OuterRef('pk'))),
    )


def catalog_base():
    """Базовая выдача каталога: публичное, со всем, что рисует карточка.

    `select_related` и `prefetch_related` здесь не оптимизация, а условие
    работоспособности: карточка спрашивает автора, жанр и теги, и без них
    страница из двадцати карточек делает под сотню запросов.
    """
    return _reading_effort(
        Story.objects.filter(status__in=PUBLIC_STATUSES)
        .select_related('author', 'primary_genre', 'secondary_genre')
        .prefetch_related('tags')
    )


def all_stories():
    """Все произведения, включая непубличные. Для витрин и поиска, которые
    сами решают, что показать."""
    return _reading_effort(
        Story.objects.select_related('author', 'primary_genre',
                                     'secondary_genre')
        .prefetch_related('tags')
    )


def public_stories():
    return catalog_base()


def story_by_slug(slug: str):
    return all_stories().filter(slug=slug).first()


_GENRES_KEY = 'catalog:genres'


def all_genres() -> list:
    """Жанры со счётчиком произведений.

    `count` считается, а не хранится: колонка разошлась бы с выдачей на
    первой же смене статуса работы. Считаются только публичные — читатель
    не должен по счётчику догадываться, что у кого-то есть черновик.

    Кэшируется на те же пять минут, что и остальные справочники: запрос с
    двумя агрегатами по всему каталогу спрашивается **трижды** на странице
    каталога — полосой жанров, списком опций панели и резолвом жанра, — и
    справочник из двенадцати строк этого не стоит. Счётчик отстаёт на
    минуты; это тот же порядок, что у самой выдачи с её `recent_views`.
    """
    genres = cache.get(_GENRES_KEY)
    if genres is None:
        genres = list(
            Genre.objects.annotate(
                primary_count=Count('primary_stories',
                                    filter=Q(primary_stories__status__in=PUBLIC_STATUSES),
                                    distinct=True),
                secondary_count=Count('secondary_stories',
                                      filter=Q(secondary_stories__status__in=PUBLIC_STATUSES),
                                      distinct=True),
            ).annotate(count=F('primary_count') + F('secondary_count'))
        )
        cache.set(_GENRES_KEY, genres, REFERENCE_TTL)
    return genres


def genre_by_slug(slug: str):
    """Жанр по слагу или None. Пустой слаг в базу не идёт: `tag_by_slug('')`
    честно делал `SELECT`, и каталог платил за него дважды на страницу."""
    if not slug:
        return None
    return next((g for g in all_genres() if g.slug == slug), None)


def all_authors() -> list:
    from .profile import with_works

    return list(with_works(User.objects.order_by('username')))


def apply_catalog_filters(stories, sort: str = CATALOG_DEFAULT_SORT,
                          status: str = '', audience: str = '',
                          length: str = '', badge: str = '',
                          author_tier: str = '', kind: str = ''):
    """Оси каталога поверх готовой выдачи. Пустая ось — no-op."""
    qs = stories
    if status:
        qs = qs.filter(status=status)
    if audience in AUDIENCE_ORDER:
        # Накопительно, а не точным совпадением (DEC-38): читателю
        # четырнадцати лет доступно и то, что помечено 10+. Безопасное
        # направление сохраняется — младшая вилка старших отметок не видит.
        allowed = AUDIENCE_ORDER[:AUDIENCE_ORDER.index(audience) + 1]
        qs = qs.filter(audience__in=allowed)
    if length == 'short':
        qs = qs.filter(read_minutes_db__lte=10)
    elif length == 'medium':
        qs = qs.filter(read_minutes_db__gt=10, read_minutes_db__lte=30)
    elif length == 'long':
        qs = qs.filter(read_minutes_db__gt=30)
    if kind == 'single':
        qs = qs.filter(format='single')
    elif kind == 'done':
        qs = qs.filter(format='serial', status='Completed')
    elif kind == 'ongoing':
        qs = qs.filter(format='serial', status='OnProcess')
    if badge == 'editorial':
        qs = qs.filter(is_editorial_pick=True)
    elif badge == 'contest':
        # «Байқауға қатысады» — участие в **незавершённом** конкурсе
        # (DEC-45). Не «в идущем приёме»: работа, ушедшая к жюри, всё ещё
        # в конкурсе, и снимать с неё знак до объявления итогов рано.
        qs = qs.filter(submissions__contest__results_on__gt=timezone.localdate()
                       ).distinct()
    if author_tier == 'new':
        qs = qs.filter(author__followers__lt=NEW_AUTHOR_FOLLOWERS)

    return _sorted(qs, sort)


def _sorted(qs, sort: str):
    """Порядок выдачи.

    `pk` вторым ключом везде, где первый допускает ничью: без него
    Postgres вправе вернуть равные строки в любом порядке, и страница
    каталога перетасовывалась бы между запросами.
    """
    if sort == 'alphabet':
        return qs.order_by(Lower('title'), 'pk')
    if sort == 'recent':
        return qs.order_by('-created_at', '-pk')
    if sort == 'popularity':
        return qs.order_by('-views', 'pk')
    return qs.order_by('-recent_views', 'pk')


def filter_catalog(*, query: str = '', genre: str = '', tag: str = '',
                   status: str = '', sort: str = CATALOG_DEFAULT_SORT,
                   audience: str = '', length: str = '',
                   badge: str = '', author_tier: str = '', kind: str = ''):
    """Единый пайплайн каталога, поиска, жанра и тега (DEC-27).

    Оси комбинируются через AND. Непубличное не попадает сюда никогда,
    какие бы оси ни выставили: черновик и работа на модерации — этапы
    авторского пути, а не публикация (DEC-23).
    """
    qs = catalog_base()

    q = (query or '').strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(author__pen_name__icontains=q)
            | Q(author__username__icontains=q)
            | Q(author__name__icontains=q)
        )

    if genre:
        qs = qs.filter(Q(primary_genre__slug=genre)
                       | Q(secondary_genre__slug=genre))

    if tag:
        # Pending-тег публичную выдачу не фильтрует (BR-TAG-07): он ещё не
        # прошёл модератора, и его страница для постороннего не существует.
        if Tag.objects.filter(slug=tag, status='accepted').exists():
            qs = qs.filter(tags__slug=tag)
        else:
            qs = qs.none()

    return apply_catalog_filters(qs, sort=sort, status=status,
                                 audience=audience, length=length,
                                 badge=badge, author_tier=author_tier,
                                 kind=kind)


def related_stories(slug: str, limit: int = 6) -> list:
    """«Что дальше» под произведением (FR-STORY-02).

    Тот же основной жанр, **чужой автор** — знакомство с новым именем
    ценнее ещё одной книги того же; не хватило — добираем популярным.
    """
    source = Story.objects.filter(slug=slug).first()
    if not source:
        return []

    others = (catalog_base().filter(status='Published')
              .exclude(slug=slug).exclude(author=source.author))
    same_genre = list(others.filter(
        Q(primary_genre=source.primary_genre)
        | Q(secondary_genre=source.primary_genre)
    ).order_by('-views', 'pk')[:limit])

    if len(same_genre) < limit:
        fillers = (others.exclude(pk__in=[s.pk for s in same_genre])
                   .order_by('-views', 'pk')[:limit - len(same_genre)])
        same_genre += list(fillers)
    return same_genre
