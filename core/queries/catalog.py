"""Каталог, поиск, жанры: единый движок выдачи (DEC-27, DEC-36).

Здесь остались только сборка выдачи и справочники. Сама выдача выражена
`Story.objects` — оси, публичность и объём чтения живут в
`core/managers.py`, потому что там их можно продолжить фильтром и посчитать,
а не только вернуть готовым списком.

Четыре правила этого раздела нарушались именно потому, что лежали не в одном
месте: в публичную выдачу идут только публичные статусы (DEC-23), ось «Жасың»
накопительная (DEC-38), дефолт сортировки — окно в 14 дней (DEC-36),
pending-тег публичную выдачу не фильтрует (BR-TAG-07). Каждое теперь названо
одним методом queryset'а.
"""

from django.core.cache import cache
from django.db.models import Case, Count, F, IntegerField, Q, Value, When

from ..domain.catalog import CATALOG_DEFAULT_SORT, PUBLIC_STATUSES
from ..models import Genre, Story, User
from .site import REFERENCE_TTL


def catalog_base():
    """Базовая выдача каталога: публичное, со всем, что рисует карточка."""
    return Story.objects.public().for_card().with_reading_effort()


def all_stories():
    """Все произведения, включая непубличные. Для витрин и кабинета, которые
    сами решают, что показать."""
    return Story.objects.for_card().with_reading_effort()


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
    qs = stories.filter(status=status) if status else stories
    return (qs.with_audience(audience)
              .with_length(length)
              .of_kind(kind)
              .with_badge(badge)
              .by_author_tier(author_tier)
              .sorted_by(sort))


def filter_catalog(*, query: str = '', genre: str = '', tag: str = '',
                   status: str = '', sort: str = CATALOG_DEFAULT_SORT,
                   audience: str = '', length: str = '',
                   badge: str = '', author_tier: str = '', kind: str = ''):
    """Единый пайплайн каталога, поиска, жанра и тега (DEC-27).

    Оси комбинируются через AND. Непубличное не попадает сюда никогда,
    какие бы оси ни выставили: черновик и работа на модерации — этапы
    авторского пути, а не публикация (DEC-23).
    """
    qs = catalog_base().matching(query).in_genre(genre).with_tag(tag)

    return apply_catalog_filters(qs, sort=sort, status=status,
                                 audience=audience, length=length,
                                 badge=badge, author_tier=author_tier,
                                 kind=kind)


def related_stories(slug: str, limit: int = 6) -> list:
    """«Что дальше» под произведением (FR-STORY-02).

    Тот же основной жанр, **чужой автор** — знакомство с новым именем
    ценнее ещё одной книги того же; не хватило — добираем популярным.

    Публичность приходит из `catalog_base()`, то есть по `PUBLIC_STATUSES`.
    Своего сужения до литерала `'Published'` здесь быть не должно: после
    DEC-37 публичный сериал носит `Completed` или `OnProcess`, и такое
    сужение молча выкидывало из блока **все** сериалы портала.

    «Сначала жанр, потом остальное» выражено ключом сортировки, а не двумя
    выборками. Порядок тот же, а запрос один: у второй выборки был свой
    `prefetch_related('tags')`, и блок из шести карточек стоил четырёх
    запросов вместо двух.
    """
    source = Story.objects.filter(slug=slug).first()
    if not source:
        return []

    return list(
        catalog_base()
        .exclude(slug=slug)
        .exclude(author=source.author)
        .annotate(other_genre=Case(
            When(Q(primary_genre=source.primary_genre)
                 | Q(secondary_genre=source.primary_genre), then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ))
        .order_by('other_genre', '-views', 'pk')[:limit]
    )
