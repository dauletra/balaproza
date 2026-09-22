"""Каталог, поиск, жанры: сборка выдачи и справочники.

Сама выдача выражена `Story.objects`: оси, публичность и объём чтения живут
в `core/managers.py`, где их можно продолжить фильтром и посчитать.

Четыре правила раздела названы там по одному методу queryset'а: в публичную
выдачу идут только публичные статусы, ось «Жасың» накопительная,
 дефолт сортировки — окно в 14 дней, pending-тег
публичную выдачу не фильтрует.
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
    Value,
    When,
)

from ..domain.catalog import CATALOG_DEFAULT_SORT, PUBLIC_STATUSES
from ..models import Genre, Story, Tag, User
from .site import REFERENCE_TTL
from .tags import with_counts as with_tag_counts


def catalog_base(viewer=None):
    """Базовая выдача каталога: публичное, со всем, что рисует карточка.

    `viewer` — кто смотрит, для меток на карточке. `None` значит
    «гость», и метки всё равно проставляются, значениями: карточка
    спрашивает их всегда, а пропущенная аннотация молча читается как
    «не сохранено» (`managers.viewer_mark`).
    """
    return (Story.objects.public().for_card().with_reading_effort()
            .for_viewer(viewer))


def all_stories():
    """Все произведения, включая непубличные. Для витрин и кабинета, которые
    сами решают, что показать."""
    return Story.objects.for_card().with_reading_effort()


def public_stories(viewer=None):
    return catalog_base(viewer)


# Сколько карточек в ряду главной. Пять — четыре видны на широком экране,
# пятая торчит краем и говорит, что ряд прокручивается.
HOME_ROW = 5


def home_rows(viewer=None) -> dict:
    """Три тематических ряда главной — тремя ограниченными выборками.

    Раньше страница делала `list(public_stories())` и резала результат в
    Python: **весь публичный каталог** в память, с пятью подзапросами и
    prefetch тегов на каждую работу, ради пятнадцати карточек. На демо-
    корпусе незаметно, на тысяче работ главная становится самой медленной
    страницей портала — и именно она самая посещаемая.

    Оси не изобретаются заново: `popularity`, `single`+`short`, `ongoing`
    уже выражены в `managers.py` и означают ровно то же, что одноимённые
    ссылки «показать все» под рядами. До этого ряд коротких брал 15 минут,
    а ссылка под ним вела на каталог с порогом в 10, — читатель, нажавший
    «все», видел меньше, чем в ряду.

    Порядок внутри ряда, кроме «Көп оқылған», — умолчание модели, то есть
    «сейчас популярно».

    `for_row`, а не `for_card`: узкая карточка ряда тегов не показывает, а
    их предзагрузка — отдельный запрос на каждую выдачу, то есть три
    запроса за то, чего на экране нет.
    """
    base = (Story.objects.public().for_row().with_reading_effort()
            .for_viewer(viewer))
    return {
        'top': list(base.sorted_by('popularity')[:HOME_ROW]),
        'short': list(base.of_kind('single').with_length('short')[:HOME_ROW]),
        'ongoing': list(base.of_kind('ongoing')[:HOME_ROW]),
    }


def sitemap_stories():
    """Слаг и дата правки — для `sitemap.xml`. Не `catalog_base()`: карточные
    `for_card()`/`with_reading_effort()` тут не нужны и только лишний JOIN на
    выдаче в тысячи строк, которую читает краулер, а не читатель."""
    return Story.objects.public().only('slug', 'updated_at')


def sitemap_authors():
    """Авторы для `sitemap.xml` — только те, у кого есть публичная работа.

    Пустой профиль в поиске работает против платформы: человек приходит
    по запросу с именем и попадает туда, где читать нечего. Тот же отбор,
    что у ряда «Жаңа авторлар».
    """
    return (User.objects
            .filter(Exists(Story.objects.filter(author=OuterRef('pk'),
                                                status__in=PUBLIC_STATUSES)))
            .only('username').order_by('username'))


def sitemap_genres():
    """Жанры для карты сайта — голыми слагами.

    Не `all_genres()`: тот считает по два агрегата на жанр ради счётчика
    на витрине, а краулеру нужен адрес. Та же ошибка, что была на
    главной, только дешевле.
    """
    return Genre.objects.only('slug').order_by('position', 'slug')


def story_by_slug(slug: str, viewer=None):
    """Работа по слагу для читательской стороны — и только та, которую
    этому зрителю можно показать.

    Без зрителя дверь закрыта до публичного: `None` значит «гость», и
    новый вызов, забывший спросить, кто смотрит, по умолчанию получает
    минимум, а не всё. Раньше здесь стоял `filter(slug=...)` без единого
    условия — черновик и работа на модерации отдавались целиком любому,
    кто угадал слаг, а слаг собирается из названия (`slugify_kz`), то есть
    подбирается. Заодно черновику копились оқылым и он ложился на полку
    читателя.

    Три исключения из публичности, и все три — про людей, которым работа
    и так открыта:

    - **автор** видит своё в любом статусе: это его предпросмотр,
      «Сайтта қарау» из кабинета ведёт сюда же;
    - **модератор** (`is_staff`) видит всё — иначе решение по работе
      принимать не по чему: в админке лежат номера глав, а не их текст;
    - публичное видят все, включая гостя.

    Порядок проверок именно такой: публичность дешевле прав, а автор
    чаще модератора.
    """
    story = all_stories().filter(slug=slug).first()
    if story is None or story.is_public:
        return story
    if viewer is None:
        return None
    return story if (story.author_id == viewer.pk or viewer.is_staff) else None


_GENRES_KEY = 'catalog:genres'


def all_genres() -> list:
    """Жанры со счётчиком произведений.

    `count` считается, а не хранится: колонка разошлась бы с выдачей на
    первой же смене статуса работы. Только публичные — читатель не должен
    по счётчику догадываться о чужом черновике.

    Кэшируется на пять минут: запрос с двумя агрегатами по всему каталогу
    спрашивается трижды на одной странице — полосой жанров, списком опций
    панели и резолвом жанра.
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


def all_authors():
    from .profile import with_works

    return with_works(User.objects.order_by('username'))


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
                   badge: str = '', author_tier: str = '', kind: str = '',
                   viewer=None):
    """Единый пайплайн каталога, поиска, жанра и тега. Оси
    комбинируются через AND; непубличное не попадает сюда никогда, какие бы
    оси ни выставили."""
    qs = catalog_base(viewer).matching(query).in_genre(genre).with_tag(tag)

    return apply_catalog_filters(qs, sort=sort, status=status,
                                 audience=audience, length=length,
                                 badge=badge, author_tier=author_tier,
                                 kind=kind)


# Быстрый поиск (Cmd+K): сколько показывать в каждой из трёх групп и с
# какой длины запроса вообще идти в базу. Одна буква находит половину
# каталога и ничего не подсказывает, а триграммный индекс на ней
# бесполезен.
SUGGEST_LIMIT = 5
SUGGEST_MIN_LENGTH = 2


def search_suggestions(query: str, limit: int = SUGGEST_LIMIT) -> dict:
    """Подсказки быстрого поиска: до пяти работ, авторов и тегов.

    Раньше вместо этого отдавался **весь индекс** одним JSON — все
    публичные работы, все авторы, все принятые теги, — а фильтровал его
    браузер. Кэш на пять минут спасал базу, но не читателя: в телефон
    подростка при первом же нажатии Cmd+K уезжал весь каталог. И
    подсказки отставали ровно настолько, насколько жил кэш: работа,
    опубликованная только что, не находилась.

    Поиск по работам — тот же `matching()`, что и в каталоге, то есть те
    же триграммные индексы и то же поведение: нашлось по названию или по
    имени автора. Второго механизма поиска у портала нет и не заводится.

    Авторы не сужаются до «у кого есть публичная работа»: человек ищет
    друга по нику чаще, чем подборку для чтения. Порядок — по числу
    подписчиков, чтобы сверху оказался тот, кого искали.
    """
    q = (query or '').strip()
    if len(q) < SUGGEST_MIN_LENGTH:
        return {'stories': [], 'authors': [], 'tags': []}

    stories = (Story.objects.public().matching(q)
               .select_related('author')
               .only('slug', 'title', 'cover',
                     'author__pen_name', 'author__username')
               .order_by('-recent_views', 'pk')[:limit])
    authors = (User.objects
               .filter(Q(pen_name__icontains=q) | Q(username__icontains=q))
               .only('username', 'pen_name')
               .order_by('-followers', 'username')[:limit])
    # И по слагу тоже: тег пишется по-казахски, а ищут его часто
    # латиницей («mektep»), — ровно так же вёл себя прежний клиентский
    # фильтр. Триграммного индекса у тегов нет и не нужно: их сотни, а не
    # десятки тысяч, как работ.
    tags = (with_tag_counts(
        Tag.objects.filter(Q(name__icontains=q) | Q(slug__icontains=q),
                           status='accepted'))
        .order_by('name')[:limit])
    return {'stories': list(stories), 'authors': list(authors),
            'tags': list(tags)}


def related_stories(slug: str, limit: int = 6):
    """«Что дальше» под произведением.

    Тот же основной жанр, **чужой автор** — знакомство с новым именем
    ценнее ещё одной книги того же; не хватило — добираем популярным.
    Публичность приходит из `catalog_base()`: своего сужения до литерала
    `'Published'` здесь быть не должно.

    «Сначала жанр, потом остальное» выражено ключом сортировки, а не двумя
    выборками: порядок тот же, а запрос один.
    """
    source = Story.objects.filter(slug=slug).first()
    if not source:
        return Story.objects.none()

    return (
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
