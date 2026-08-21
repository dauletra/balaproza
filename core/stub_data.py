"""
Стаб-данные для дизайн-фазы. Здесь живут все «как будто из БД» сущности,
которые рисует UI. После Ф14 этот файл заменится на Django-модели.

Не импортировать в продакшен-логику — это сугубо для рендера шаблонов.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ───────────────────────── Жанры (docs/03 — 12 шт) ─────────────────────────

@dataclass(frozen=True)
class Genre:
    slug: str
    name: str       # казахское название
    hue: int        # OKLCH hue 0-360
    count: int      # сколько произведений
    icon: str = ""  # slug SVG-иконки из спрайта (без префикса icon-)


GENRES = [
    Genre("fantastika", "Фантастика", 250, 124, icon="planet"),
    Genre("fantezi",    "Фэнтези",    295,  87, icon="feather"),
    Genre("triller",    "Триллер",    210,  56, icon="skull"),
    Genre("romantika",  "Романтика",    8, 142, icon="heart"),
    Genre("drama",      "Драма",      195,  91, icon="drop"),
    Genre("horror",     "Хоррор",      25,  34, icon="fir"),
    Genre("erteg",      "Ертегі",      75,  48, icon="book"),
    Genre("tarih",      "Тарихи",      40,  29, icon="book"),
    Genre("komediya",   "Комедия",     55,  61, icon="smile"),
    Genre("fanfik",     "Фанфик",     330,  38, icon="pen"),
    Genre("balalar",    "Балалар",    180,  77, icon="backpack"),
    Genre("shyttyrman", "Шытырман",   145,  53, icon="cityscape"),
]

GENRES_BY_SLUG = {g.slug: g for g in GENRES}

# Витринные счётчики для hero главной: подросток должен с первого экрана понять
# масштаб портала. Genre.count — единственный согласованный «объём» в стабе,
# число авторов пока отдельной константой (в Ф14 заменится агрегатом по БД).
STUB_AUTHOR_COUNT = 214


def portal_stats() -> dict:
    return {
        'stories': sum(g.count for g in GENRES),
        'authors': STUB_AUTHOR_COUNT,
        'genres': len(GENRES),
    }


# ───────────────────────── Теги (docs/11 — UGC-таксономия) ─────────────────
# Параллельно жанрам: до 10 на произведение (BR-TAG-01). Авторы создают
# свободно, модератор пост-фактум переводит pending → accepted (тег попадает
# в автокомплит) или rejected (тег удаляется из произведения).

@dataclass(frozen=True)
class Tag:
    slug: str
    name: str           # оригинал, отображается; в Ф14 — original input автора
    status: str         # 'pending' | 'accepted' | 'rejected'
    usage_count: int    # денормализовано, для сортировки автокомплита/виджета
    weekly_count: int = 0   # использований за последние 7 дней — «осы аптада»


# usage_count — накопленное за всё время, weekly_count — срез недели. Две разные
# витрины: первая показывает опоры портала, вторая — о чём пишут прямо сейчас
# (DEC-31). У «сиқыр-академиясы» накоплено мало, а на неделе много — именно
# такие всплески теги и должны ловить.
TAGS = [
    Tag('mektep',           'мектеп',           'accepted', 42, weekly_count=6),
    Tag('dostyk',           'достық',           'accepted', 38, weekly_count=4),
    Tag('sayahat',          'саяхат',           'accepted', 24, weekly_count=2),
    Tag('jasospirim',       'жасөспірім',       'accepted', 56, weekly_count=9),
    Tag('gashyqtyq',        'ғашықтық',         'accepted', 31, weekly_count=11),
    Tag('mistika',          'мистика',          'accepted', 18, weekly_count=7),
    Tag('syikyr-akademiya', 'сиқыр-академиясы', 'accepted', 12, weekly_count=13),
    Tag('arman',            'арман',            'accepted', 27, weekly_count=3),
    Tag('detektiv-jas',     'жас детектив',     'accepted',  9, weekly_count=5),
    Tag('aua-ralighi',      'ауыл-қала',        'accepted', 14, weekly_count=1),
    # pending — для иллюстрации работы модерации (BR-TAG-03/07)
    Tag('basqa-alem',       'басқа әлем',       'pending',   3, weekly_count=3),
    Tag('experimental',     'эксперимент',      'pending',   1, weekly_count=1),
]

TAGS_BY_SLUG = {t.slug: t for t in TAGS}

# Блок-лист (BR-TAG-05). В Ф14 — таблица, редактируется в Django admin.
BLOCKED_TAG_PATTERNS = frozenset({'spam', 'реклама', 'политика'})


def tag_by_slug(slug: str) -> Optional["Tag"]:
    return TAGS_BY_SLUG.get(slug)


def tags_of(story: "Story") -> list:
    """Resolve Story.tags (slug-tuple) в Tag-объекты.

    Возвращает ВСЕ теги, включая pending. Фильтрация по видимости (BR-TAG-07)
    делается в шаблоне `tag_list.html` по флагу viewer_is_author.
    """
    return [TAGS_BY_SLUG[s] for s in story.tags if s in TAGS_BY_SLUG]


def is_blocked(name: str) -> bool:
    """Проверка имени тега против блок-листа (BR-TAG-05). Case-insensitive."""
    return name.strip().lower() in BLOCKED_TAG_PATTERNS


def popular_tags(limit: int = 10) -> list:
    """Топ-N accepted-тегов по usage_count — для виджета «Танымал тегтер»."""
    return sorted(
        (t for t in TAGS if t.status == 'accepted'),
        key=lambda t: t.usage_count,
        reverse=True,
    )[:limit]


def trending_tags(limit: int = 6) -> list:
    """Топ-N accepted-тегов по weekly_count — виджет «Осы аптада».

    Теги — единственная ось, которая обновляется без участия редакции, поэтому
    именно они показывают актуальное. Теги без активности за неделю не
    показываем: иначе полоса вырождается в копию «Танымал тегтер».
    """
    return sorted(
        (t for t in TAGS if t.status == 'accepted' and t.weekly_count > 0),
        key=lambda t: t.weekly_count,
        reverse=True,
    )[:limit]


def accepted_tags_json() -> list:
    """Accepted-теги как plain dicts — для встраивания в Alpine-компонент
    через {% json_script %}. dataclass напрямую не json-serializable."""
    return [
        {'slug': t.slug, 'name': t.name, 'usage_count': t.usage_count}
        for t in TAGS if t.status == 'accepted'
    ]


def blocked_tag_patterns_list() -> list:
    """Блок-лист как отсортированный list[str] для встраивания в Alpine."""
    return sorted(BLOCKED_TAG_PATTERNS)


# ───────────────────────── Пользователи / Авторы ─────────────────────────

@dataclass(frozen=True)
class Author:
    username: str   # без @
    name: str       # реальное имя для кабинета/модерации/конкурсов
    pen_name: str   # публичное авторское имя / псевдоним
    bio: str
    works: int
    followers: int

    @property
    def public_name(self) -> str:
        return self.pen_name or f"@{self.username}"


AUTHORS = [
    Author("rudazov",   "Алмат Рысқали",     "Rudazov",       "Фэнтези, шытырман",      12, 8420),
    Author("aygerim_k", "Айгерім Қасенова",  "aiqalam",       "Жас прозаик · Алматы",    3,  184),
    Author("bekzhan_t", "Бекжан Тұрсынов",   "BekTor",        "Қалалық әңгімелер",       5,  312),
    Author("dina_books","Дина Айдарбекова",  "dina.books",    "Балалар әдебиеті",        8,  542),
    Author("sayyn",     "Сайын Нұрбекұлы",   "sayyn",         "Фантастика, шытырман",    2,   96),
    # Демо-пользователь, под которым логинимся через фейк-сессию (см. core.views.login_view).
    Author("aidana",    "Айдана Серікқызы",  "aidana",        "Жас прозаик · Тараз",     4,   23),
]

AUTHORS_BY_USERNAME = {a.username: a for a in AUTHORS}


def new_authors(limit: int = 4) -> list:
    """«Жаңа авторлар» для главной — те, у кого меньше всего подписчиков.

    Социальное доказательство: подросток должен видеть, что здесь пишут такие
    же начинающие, а не только авторы с восемью тысячами подписчиков.
    """
    return sorted(AUTHORS, key=lambda a: a.followers)[:limit]


# ───────────────────────── Произведения ─────────────────────────

@dataclass(frozen=True)
class Story:
    slug: str
    title: str
    author_username: str
    cover: str       # путь относительно static/
    genres: tuple    # (primary_slug, secondary_slug or None)
    chapters: int
    views: int
    likes: int
    comments: int
    # Статус произведения (docs/04.4 · BR-10/11). По умолч. — NotPublished (Draft).
    # Каталожные стории, попадающие в публичные списки, должны явно задать "Published".
    # Переход в Published только через модерацию (BR-11, DEC-23).
    status: str = "NotPublished"   # Published | NotPublished | OnProcess | Completed | OnModeration
    annotation: str = ""        # короткое описание для STORY/MANAGE/EDIT
    secondary_genre: str = ""   # если у произведения есть второй жанр — для форм
    # UGC-теги (docs/11, BR-TAG-01): до 10 slug-ов на произведение.
    # Pending фильтруются в шаблоне tag_list.html по viewer_is_author (BR-TAG-07).
    tags: tuple = ()
    audience: str = "10+"
    badges: tuple = ()
    format: str = "serial"  # single | serial

    @property
    def author(self) -> Author:
        return AUTHORS_BY_USERNAME[self.author_username]

    @property
    def primary_genre(self) -> Genre:
        return GENRES_BY_SLUG[self.genres[0]]

    @property
    def genres_resolved(self) -> list:
        """Все жанры произведения как объекты Genre, фильтруя None."""
        return [GENRES_BY_SLUG[s] for s in self.genres if s and s in GENRES_BY_SLUG]

    @property
    def tags_resolved(self) -> list:
        """UGC-теги произведения как объекты Tag."""
        return tags_of(self)

    @property
    def is_single(self) -> bool:
        return self.format == "single"

    @property
    def is_serial(self) -> bool:
        return self.format != "single"

    @property
    def format_label(self) -> str:
        return "Бір бөлімді" if self.is_single else "Көп бөлімді"

    @property
    def format_badge_label(self) -> str:
        return "Бір оқылым" if self.is_single else "Серия"

    @property
    def reading_meta_label(self) -> str:
        if self.is_single:
            return f"{self.read_minutes} минут оқу"
        return f"{self.chapters} бөлім"

    @property
    def total_chars(self) -> int:
        """Approximate rendered volume for UI badges; real value comes from chapters when present."""
        total = sum(c.char_count for c in chapters_of(self.slug))
        return total or self.chapters * 1800

    @property
    def read_minutes(self) -> int:
        """Reading-time badge for children and parents. 900 chars/min keeps Kazakh prose comfortable."""
        return max(3, (self.total_chars + 899) // 900)

    @property
    def length_bucket(self) -> str:
        if self.read_minutes <= 15:
            return "short"
        if self.read_minutes <= 35:
            return "medium"
        return "long"


STORIES = [
    Story("dalney-berega",  "Алыс жағалауларда",     "sayyn",      "ipad_19b0bc4bcd9c1a1dc4c3cc12cf20dce5.webp", ("fantastika",  None),         12, 12482, 4821, 312, status="Published", annotation="Үш дос жоғалған жолды іздеп шығады. Таудағы сапар оларды өз қорқынышымен, достықпен және белгісіз ауылдың құпиясымен беттестіреді.", tags=("arman", "sayahat", "jasospirim"), audience="10+", badges=("Редакция таңдауы",)),
    Story("temniy-lord",    "Күңгірт мырза",         "bekzhan_t",  "ipad_42f033cf1b9a2bcad744d05b9d429609.webp", ("fantezi",     "horror"),      3,  8920, 2440, 156, status="Published", annotation="Қараңғы патшалыққа түскен жас кейіпкер биліктің бағасын түсіне бастайды. Сиқыр, қорқыныш және таңдау туралы фэнтези.", tags=("mistika", "arman", "basqa-alem"), audience="14+"),
    Story("igra-kuklovoda", "Қуыршақшының ойыны",    "dina_books", "ipad_499539963221e0fe36b0888bf8601067.webp", ("triller",     "drama"),       3, 18102, 6230, 421, status="Published", annotation="Мектептегі тыныш күндер бір жұмбақ ойыннан кейін өзгереді. Әр белгі жаңа күдікке апарады, ал шындық жақын жерде жасырынып тұр.", tags=("mistika", "jasospirim", "detektiv-jas"), audience="14+", badges=("Байқауға қатысады",)),
    Story("kronchessii",    "Тас уәделер",           "rudazov",    "ipad_5916b4e19c616e74d008125ba9a1be8e.webp", ("shyttyrman",  "fantezi"),     3, 32540, 11200, 890, status="Published", annotation="Ескі қала қабырғаларындағы тасқа қашалған уәделер оянады. Кейіпкерлер өткеннің шартын бұзбай, болашақты сақтауға тырысады.", tags=("sayahat", "arman", "syikyr-akademiya")),
    Story("arhimag",        "Сиқыршы: бөтен әлемдер","rudazov",    "ipad_940e074d12d6c3657199601ca568f1b3.jpg",  ("fantezi",     "shyttyrman"),  3, 12482, 4821, 312, status="Published", annotation="Жас сиқыршы бөтен әлемдердің есігін ашқанда, әр әлем өз ережесін ұсынады. Үйге қайту үшін ол күштен бұрын жауапкершілікті үйренеді.", tags=("syikyr-akademiya", "arman", "dostyk", "jasospirim", "mektep")),
    Story("sila-imperii",   "Империя құдіреті",      "aygerim_k",  "ipad_992f1631a421d74ed5e1aa72717df374.webp", ("tarih",       "drama"),       1, 14200, 3890, 245, status="Published", annotation="Көне империяның шетінде өскен жас батыр тарихтың үлкен толқынына түседі. Бұл шығарма билік, адалдық және ел алдындағы таңдау туралы.", tags=("arman", "jasospirim"), format="single"),

    # ─ Витринный слой: заполняет ряды главной и покрывает пустые жанры ─
    # Без него «Қысқа оқылатын әңгімелер» рендерился одной карточкой, а половина
    # жанровых чипов вела в пустое состояние — раскладку было не на чем смотреть.
    # cover="" оставлен намеренно у части историй: проверяем типографическую
    # плашку cover_placeholder наравне с фото-обложками.
    Story(
        slug="kunnin-songy-sagaty", title="Күннің соңғы сағаты", author_username="sayyn",
        cover="ipad_f8f1ea3b7e8133f930825b2da92a135e.webp", genres=("fantastika", None),
        chapters=1, views=6410, likes=980, comments=64,
        status="Published", format="single",
        annotation="Күн батпай тұрып бір нәрсені үлгеру керек. Он жеті жасар бала уақыттың қалай тоқтайтынын біледі.",
        tags=("arman", "jasospirim"), audience="10+",
    ),
    Story(
        slug="mektep-koridory", title="Мектеп дәлізіндегі хат", author_username="aygerim_k",
        cover="", genres=("romantika", "drama"),
        chapters=1, views=9240, likes=2110, comments=188,
        status="Published", format="single", secondary_genre="drama",
        annotation="Партаның астынан табылған хат кімге жазылғаны белгісіз. Бірақ оны оқыған қыз енді бұрынғыдай жүре алмайды.",
        tags=("mektep", "gashyqtyq", "jasospirim"), audience="10+",
    ),
    Story(
        slug="atam-aityp-berdi", title="Атам айтып берген ертегі", author_username="dina_books",
        cover="", genres=("erteg", None),
        chapters=1, views=3120, likes=540, comments=41,
        status="Published", format="single",
        annotation="Ауылдағы жаз, кешкі шай және атаның бір ертегісі. Ол ертегіде жоғалған қой да, жоғалған бала да бар.",
        tags=("dostyk", "mektep"), audience="10+",
    ),
    Story(
        slug="konshi-bala", title="Көрші бала", author_username="bekzhan_t",
        cover="", genres=("komediya", None),
        chapters=1, views=7830, likes=1420, comments=133,
        status="Published", format="single",
        annotation="Көршінің баласы күнде бір нәрсе бүлдіреді. Бүгін ол менің велосипедімді ұрлады — бірақ себебі күлкілі.",
        tags=("dostyk", "mektep", "jasospirim"), audience="10+",
    ),
    Story(
        slug="tunge-deiin", title="Түнге дейін үш сағат", author_username="bekzhan_t",
        cover="ipad_fe6ce3337de7c1c1bf18ef8bb0f3f9a3.webp", genres=("triller", None),
        chapters=1, views=11470, likes=2890, comments=241,
        status="Published", format="single",
        annotation="Лифт екі қабат арасында тоқтады. Ішінде екеу, ал біреуі шындықты айтпай тұр.",
        tags=("mistika", "detektiv-jas"), audience="14+",
    ),
    Story(
        slug="almaty-ayazy", title="Алматы аязы", author_username="aygerim_k",
        cover="", genres=("drama", None),
        chapters=1, views=4980, likes=760, comments=58,
        status="Published", format="single",
        annotation="Қаңтардағы қала, жылымаған автобус және әкесімен алғаш рет ашық сөйлескен күн.",
        tags=("jasospirim", "arman"), audience="14+",
    ),
    Story(
        slug="balkonnan-korinetin", title="Балконнан көрінетін әлем", author_username="dina_books",
        cover="", genres=("balalar", None),
        chapters=1, views=2640, likes=430, comments=27,
        status="Published", format="single",
        annotation="Тоғызыншы қабаттан бүкіл ауланы көруге болады. Ал кейде — өзіңді де.",
        tags=("dostyk", "arman"), audience="10+",
    ),
    Story(
        slug="korkynyshty-koilek", title="Қорқынышты көйлек", author_username="bekzhan_t",
        cover="", genres=("horror", None),
        chapters=1, views=8150, likes=1630, comments=204,
        status="Published", format="single",
        annotation="Ескі шкафтан табылған көйлекті киген адам түнде өз атын ұмытады.",
        tags=("mistika",), audience="14+",
    ),
    Story(
        slug="zhuldyz-kartasy", title="Жұлдыз картасы", author_username="rudazov",
        cover="", genres=("fantastika", "shyttyrman"),
        chapters=9, views=15320, likes=3940, comments=387,
        status="Published", secondary_genre="shyttyrman",
        annotation="Ғарыш кемесінің картасында болмауға тиіс бір нүкте бар. Экипаж соған қарай бет алады.",
        tags=("aua-ralighi", "sayahat", "arman"), audience="10+",
        badges=("Редакция таңдауы",),
    ),
    Story(
        slug="kokjal-anyzy", title="Көкжал аңызы", author_username="dina_books",
        cover="", genres=("tarih", "erteg"),
        chapters=6, views=6720, likes=1180, comments=94,
        status="Published", secondary_genre="erteg",
        annotation="Далада бір қасқыр туралы аңыз жүреді. Оны естіген әр ұрпақ басқаша айтады.",
        tags=("sayahat", "dostyk"), audience="10+",
    ),
    Story(
        slug="keiipkerge-hat", title="Кейіпкерге жазылған хат", author_username="aygerim_k",
        cover="", genres=("fanfik", "romantika"),
        chapters=5, views=10940, likes=3210, comments=452,
        status="Published", secondary_genre="romantika",
        annotation="Сүйікті кітабының кейіпкеріне хат жазған қыз кенет жауап алады.",
        tags=("gashyqtyq", "syikyr-akademiya", "jasospirim"), audience="14+",
    ),
    Story(
        slug="arqadagy-jaz", title="Арқадағы жаз", author_username="sayyn",
        cover="", genres=("balalar", "drama"),
        chapters=7, views=3890, likes=610, comments=45,
        status="Published", secondary_genre="drama",
        annotation="Жазғы каникул, ескі велосипед және ауылдағы жеті апта. Әр бөлім — бір апта.",
        tags=("dostyk", "sayahat", "mektep"), audience="10+",
    ),

    # ─ Произведения демо-пользователя «Айдана» (для WRITE-страниц) ─
    Story(
        slug="aidana-tan",    title="Таң алдында",            author_username="aidana",
        cover="ipad_c9217632f98051fd88ca5763f218a9e3.webp", genres=("drama", None),
        chapters=8, views=1042, likes=87, comments=12,
        status="Published", annotation="Жас қыздың Алматыдан Таразға қайту туралы әңгімесі. Сегіз бөлімде, әр бөлім — жаңа қала.",
        tags=("sayahat", "jasospirim", "arman", "experimental"),
    ),
    Story(
        slug="aidana-koshe",  title="Көше әндері",            author_username="aidana",
        cover="ipad_e655bb59097d8f25698466168d385969.webp", genres=("drama", "komediya"),
        chapters=1, views=203, likes=18, comments=4,
        status="OnProcess", annotation="Қаладағы бес адамның бір күні. Әрқайсысының өз әні.",
        secondary_genre="komediya",
        tags=("aua-ralighi", "dostyk", "mektep"),
        format="single",
    ),
    Story(
        slug="aidana-erteg",  title="Ертегі ертеректегі",      author_username="aidana",
        cover="ipad_eec6a1375d9124c7348c7579b8d2db33.jpg", genres=("erteg", None),
        chapters=3, views=0, likes=0, comments=0,
        status="OnModeration", annotation="Дәстүрлі ертегі формасында жазылған заманауи тарих.",
    ),
    Story(
        slug="aidana-kysh",   title="Қыстың үнсіздігі",        author_username="aidana",
        cover="ipad_f0e918b204613b38cc0e04ba74e3e3ab.webp", genres=("drama", None),
        chapters=1, views=872, likes=64, comments=9,
        status="Completed", annotation="Қыстағы ауылда қалған әжемен өткізген бір ай. Аяқталған кітап.",
        format="single",
    ),
]

STORIES_BY_SLUG = {s.slug: s for s in STORIES}


# ───────────────────────── Главы (для STORY/READ) ─────────────────────────

@dataclass(frozen=True)
class Chapter:
    number: int            # 1-based
    title: str
    char_count: int        # для «X / N» прогресса
    body: str = ""         # длинный текст для режима чтения
    likes: int = 0         # лайки именно этой главы (FR-STORY-12)
    liked: bool = False    # текущий пользователь лайкнул эту главу

    @property
    def char_count_formatted(self) -> str:
        n = self.char_count
        if n >= 1000:
            return f"{n // 1000},{(n % 1000) // 100} мың"
        return str(n)


STORY_TEXTS_DIR = Path(__file__).resolve().parent / "story_texts"


def _story_text(story_slug: str, chapter_number: int) -> str:
    path = STORY_TEXTS_DIR / story_slug / f"{chapter_number:02d}.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _chapter(story_slug: str, number: int, title: str, *, likes: int = 0, liked: bool = False) -> Chapter:
    body = _story_text(story_slug, number)
    return Chapter(number, title, len(body), body, likes=likes, liked=liked)



CHAPTERS_BY_STORY: dict = {
    # Айдана / aidana — главы для manage_story и chapter_editor
    "aidana-tan": [
        _chapter("aidana-tan", 1, "Алматыдан шығу"),
        _chapter("aidana-tan", 2, "Шу станциясы"),
        _chapter("aidana-tan", 3, "Поезд жолдастары"),
        _chapter("aidana-tan", 4, "Кешкі ас"),
        _chapter("aidana-tan", 5, "Қап-қараңғы"),
        _chapter("aidana-tan", 6, "Таң алдында"),
        _chapter("aidana-tan", 7, "Тараз"),
        _chapter("aidana-tan", 8, "Үй"),
    ],
    "kunnin-songy-sagaty": [
        _chapter("kunnin-songy-sagaty", 1, "Толық мәтін"),
    ],
    "mektep-koridory": [
        _chapter("mektep-koridory", 1, "Толық мәтін"),
    ],
    "atam-aityp-berdi": [
        _chapter("atam-aityp-berdi", 1, "Толық мәтін"),
    ],
    "konshi-bala": [
        _chapter("konshi-bala", 1, "Толық мәтін"),
    ],
    "tunge-deiin": [
        _chapter("tunge-deiin", 1, "Толық мәтін"),
    ],
    "almaty-ayazy": [
        _chapter("almaty-ayazy", 1, "Толық мәтін"),
    ],
    "balkonnan-korinetin": [
        _chapter("balkonnan-korinetin", 1, "Толық мәтін"),
    ],
    "korkynyshty-koilek": [
        _chapter("korkynyshty-koilek", 1, "Толық мәтін"),
    ],
    "aidana-koshe": [
        _chapter("aidana-koshe", 1, "Толық мәтін"),
    ],
    "aidana-kysh": [
        _chapter("aidana-kysh", 1, "Толық мәтін"),
    ],
    "temniy-lord": [
        _chapter("temniy-lord", 1, "Қара тәж"),
        _chapter("temniy-lord", 2, "Айна залы"),
        _chapter("temniy-lord", 3, "Таңдау бағасы"),
    ],
    "igra-kuklovoda": [
        _chapter("igra-kuklovoda", 1, "Бірінші белгі"),
        _chapter("igra-kuklovoda", 2, "Жіптер"),
        _chapter("igra-kuklovoda", 3, "Сахна артында"),
    ],
    "kronchessii": [
        _chapter("kronchessii", 1, "Оянған қабырға"),
        _chapter("kronchessii", 2, "Тасқа жазылған шарт"),
        _chapter("kronchessii", 3, "Уәденің салмағы"),
    ],
    "arhimag": [
        _chapter("arhimag", 1, "Бірінші есік"),
        _chapter("arhimag", 2, "Бөтен заң"),
        _chapter("arhimag", 3, "Үйге қайту шарты"),
    ],
    "dalney-berega": [
        # FR-STORY-12: лайки — на главу, не на произведение целиком.
        # Прогрессия лайков иллюстрирует «крючок»: первые главы заходят, к середине пик,
        # глава 4 — текущая для возвращающегося читателя (liked=True), последние ещё впереди.
        _chapter("dalney-berega", 1, "Жолға шығу", likes=842),
        _chapter("dalney-berega", 2, "Тауға көтерілу", likes=719),
        _chapter("dalney-berega", 3, "Алғашқы кездесу", likes=1024),
        _chapter("dalney-berega", 4, "Депрессия", likes=687, liked=True),
        _chapter("dalney-berega", 5, "Жаңа карта", likes=512),
        _chapter("dalney-berega", 6, "Жаңбыр түн", likes=438),
        _chapter("dalney-berega", 7, "Тас үй", likes=391),
        _chapter("dalney-berega", 8, "Кездесу", likes=287),
        _chapter("dalney-berega", 9, "Жасырын есік", likes=176),
        _chapter("dalney-berega", 10, "Қайту", likes=94),
        _chapter("dalney-berega", 11, "Соңғы кеш", likes=42),
        _chapter("dalney-berega", 12, "Шеп", likes=18),
    ],
    "sila-imperii": [
        _chapter("sila-imperii", 1, "Толық мәтін", likes=245),
    ],
}


def chapters_of(story_slug: str) -> list:
    """Список глав произведения. Пусто если у произведения ещё нет глав в стабе."""
    return CHAPTERS_BY_STORY.get(story_slug, [])


def chapter_of(story_slug: str, number: int):
    """Конкретная глава, либо None."""
    for c in chapters_of(story_slug):
        if c.number == number:
            return c
    return None


# ───────────────────────── Комментарии (для STORY) ────────────────────────

@dataclass(frozen=True)
class StoryComment:
    author_username: str
    date: str               # «2 сағат бұрын», «5 қаңтар»
    text: str
    likes: int = 0
    is_author_badge: bool = False
    liked: bool = False             # текущий пользователь поставил лайк
    replies: tuple = ()             # один уровень вложенности (BR-30); tuple[StoryComment]
    chapter_number: int | None = None   # к какой главе пришвартован; None = общий, на всё произведение

    @property
    def author(self):
        return AUTHORS_BY_USERNAME.get(self.author_username)


COMMENTS_BY_STORY: dict = {
    # Богатый набор — иллюстрирует все кейсы дизайна:
    # короткий/длинный, лайкнутый текущим юзером, бейдж «Автор»,
    # нить с одним и двумя ответами (BR-30: только 1 уровень).
    "dalney-berega": [
        # 1) Длинный читательский с нитью из 2 ответов — про 3-й бөлім
        StoryComment(
            "aygerim_k", "2 сағат бұрын",
            "Тамаша шығарма! Әсіресе үшінші бөлімдегі қарттың сұрағы — «жүректің не дейтіні?» — әлі есімде. "
            "Авторға айтарым: тіл өте таза, метафоралары жанды. Сирек кездесетін сапа. "
            "Жалғасын асыға күтемін, тағы 4 бөлім жетеді деп үміттенемін.",
            likes=24,
            chapter_number=3,
            replies=(
                StoryComment(
                    "sayyn", "1 сағат бұрын",
                    "Рахмет, Айгерім! Үшінші бөлім — менің ең қиналған сәтім болды. "
                    "Сезімің мен үшін маңызды.",
                    likes=18, is_author_badge=True,
                ),
                StoryComment(
                    "bekzhan_t", "45 мин бұрын",
                    "Айгерімнің пікіріне қосыламын.",
                    likes=3,
                ),
            ),
        ),
        # 2) Ответ автора верхнеуровневый — общее объявление, не привязано к главе
        StoryComment(
            "sayyn", "1 күн бұрын",
            "Пікірлерге рахмет. Келесі бөлім жұма күні шығады, дайындап жатырмын.",
            likes=87, is_author_badge=True,
        ),
        # 3) Короткий, лайкнут текущим пользователем — про 1-ю главу
        StoryComment(
            "bekzhan_t", "3 күн бұрын",
            "Тіл өте таза, метафоралары жанды.",
            likes=12, liked=True,
            chapter_number=1,
        ),
        # 4) Очень короткий — на 4-ю главу (где SAMPLE_PROGRESS)
        StoryComment(
            "dina_books", "5 күн бұрын",
            "Бұл бөлім — шедевр.",
            chapter_number=4,
        ),
        # 5) С одним ответом от автора — на 2-ю главу
        StoryComment(
            "rudazov", "1 апта бұрын",
            "Стилистика Брэдбериге ұқсайды — бұл мен үшін үлкен мадақ. Жалғастыр!",
            likes=9,
            chapter_number=2,
            replies=(
                StoryComment(
                    "sayyn", "6 күн бұрын",
                    "Рудазов, рахмет! Брэдбериді жасөспірім кезімде оқыған едім — әсері қалған шығар.",
                    likes=4, is_author_badge=True,
                ),
            ),
        ),
    ],
    # Вторая история — менее активная, для проверки разных story_detail
    "kronchessii": [
        StoryComment(
            "aygerim_k", "5 сағат бұрын",
            "Бірінші тарау қызықтыра түсті, бірақ кейіпкерлердің мотивациясы әлі түсініксіз. "
            "Авторға сұрақ: бұл қасақана ма?",
            likes=6,
            chapter_number=1,
            replies=(
                StoryComment(
                    "rudazov", "3 сағат бұрын",
                    "Иә, бұл әдейі. Кейіпкерлер 4-бөлімде ашылады. Шыдамдылықпен оқы.",
                    likes=11, is_author_badge=True,
                ),
            ),
        ),
        # Общий — без главы
        StoryComment(
            "sayyn", "2 күн бұрын",
            "Кронцессиялардың тілі — нағыз олжа. Әрбір сөз орнында.",
            likes=22, liked=True,
        ),
    ],
}


def comments_of(story_slug: str) -> list:
    """Все комментарии произведения (story-level + per-chapter), плоский список."""
    return COMMENTS_BY_STORY.get(story_slug, [])


def comments_of_chapter(story_slug: str, chapter_number: int) -> list:
    """Комментарии конкретной главы + «общие» (chapter_number=None) этого произведения.

    Общие показываем всегда — это объявления автора / отзывы на всё произведение,
    у них нет «правильной» главы; пусть видны под каждой.
    """
    out = []
    for c in COMMENTS_BY_STORY.get(story_slug, []):
        if c.chapter_number is None or c.chapter_number == chapter_number:
            out.append(c)
    return out


# ───────────────────────── Поиск/фильтрация (CAT-модуль) ───────────────────

def stories_by_genre(genre_slug: str) -> list:
    """Произведения, где genre_slug — основной или дополнительный."""
    return [s for s in STORIES if genre_slug in s.genres]


def search_stories(query: str) -> list:
    """Тривиальный case-insensitive substring-поиск по title и автору."""
    q = (query or "").strip().lower()
    if not q:
        return []
    return [
        s for s in STORIES
        if q in s.title.lower() or q in s.author.public_name.lower() or q in s.author.username.lower() or q in s.author.name.lower()
    ]


def search_authors(query: str, limit: int = 5) -> list:
    """Substring-поиск по public_name, username и real name автора (для search popup)."""
    q = (query or "").strip().lower()
    if not q:
        return []
    return [
        a for a in AUTHORS
        if q in a.public_name.lower() or q in a.username.lower() or q in a.name.lower()
    ][:limit]


CATALOG_SORTS = (
    ("popularity", "Танымалдары"),
    ("recent",     "Жаңалары"),
    ("alphabet",   "Әліпби бойынша"),
)

CATALOG_STATUS_FILTERS = (
    ("",           "Барлығы"),
    ("Published",  "Жарияланған"),
    ("Completed",  "Аяқталды"),
    ("OnProcess",  "Жазылып жатыр"),
)

CATALOG_AUDIENCE_FILTERS = (
    ("",    "Барлығы"),
    ("10+", "10+"),
    ("14+", "14+"),
)

CATALOG_LENGTH_FILTERS = (
    ("",       "Барлығы"),
    ("short",  "15 минутқа дейін"),
    ("medium", "15-35 минут"),
    ("long",   "35 минуттан ұзақ"),
)

CATALOG_FORMAT_FILTERS = (
    ("",       "Барлығы"),
    ("single", "Бір бөлімді"),
    ("serial", "Көп бөлімді"),
)

def apply_catalog_filters(stories: list, sort: str = "popularity", status: str = "",
                          audience: str = "", length: str = "",
                          format: str = "") -> list:
    """Применяет сорт + status-фильтр к списку Story.

    Используется search_results и genre_detail. Sort:
      - popularity: по views (desc)
      - recent: фейково — обратный порядок (нет created_at в stub)
      - alphabet: по title
    Status: пустой → все; иначе точный match Story.status.
    """
    out = list(stories)
    if status:
        out = [s for s in out if s.status == status]
    if audience:
        out = [s for s in out if s.audience == audience]
    if length:
        out = [s for s in out if s.length_bucket == length]
    if format:
        out = [s for s in out if s.format == format]

    if sort == "alphabet":
        out.sort(key=lambda s: s.title.lower())
    elif sort == "recent":
        out.reverse()
    else:  # popularity (default)
        out.sort(key=lambda s: s.views, reverse=True)
    return out


def filter_catalog(*, query: str = "", genre: str = "", tag: str = "",
                   status: str = "", sort: str = "popularity",
                   audience: str = "", length: str = "",
                   format: str = "") -> list:
    """Единый фильтр-пайплайн для унифицированного каталога (DEC-27).

    Применяет все источники AND-комбинацией. Для пустых параметров — no-op.
    Tag учитывает BR-TAG-07 (только accepted-теги показываются в публичной выборке).
    """
    # Стартуем с полного источника (или с search-результата если есть query)
    out = search_stories(query) if query else list(STORIES)

    if genre:
        out = [s for s in out if genre in s.genres]

    if tag:
        # Pending-теги не фильтруют публичный каталог (BR-TAG-07).
        t = TAGS_BY_SLUG.get(tag)
        if t and t.status == 'accepted':
            out = [s for s in out if tag in s.tags]
        else:
            out = []  # неизвестный/непринятый тег → пусто

    return apply_catalog_filters(out, sort=sort, status=status,
                                 audience=audience, length=length,
                                 format=format)


def related_stories(slug: str, limit: int = 6) -> list:
    """Рекомендации внизу страницы произведения (FR-STORY-02).

    Логика: тот же основной жанр, исключаем себя и того же автора (чтобы
    подталкивать к знакомству с другими). Если набирается меньше limit —
    добиваем по второстепенному жанру, затем по популярности.
    Только Published.
    """
    source = STORIES_BY_SLUG.get(slug)
    if not source:
        return []

    primary = source.genres[0] if source.genres else None
    own_author = source.author_username

    def _key(s):  # сортировка по популярности
        return s.views

    same_primary = [
        s for s in STORIES
        if s.slug != slug
        and s.author_username != own_author
        and s.status == "Published"
        and primary and primary in s.genres
    ]
    same_primary.sort(key=_key, reverse=True)

    result = same_primary[:limit]

    # Добиваем по любым другим Published-произведениям, если не хватило
    if len(result) < limit:
        existing_slugs = {s.slug for s in result}
        existing_slugs.add(slug)
        fillers = [
            s for s in STORIES
            if s.slug not in existing_slugs
            and s.author_username != own_author
            and s.status == "Published"
        ]
        fillers.sort(key=_key, reverse=True)
        result += fillers[: limit - len(result)]

    return result


# ───────────────────────── WRITE: «мои произведения» ───────────────────────

def my_stories_of(username: str) -> list:
    """Все произведения данного автора (любого статуса)."""
    return [s for s in STORIES if s.author_username == username]


def writer_stats(username: str) -> dict:
    """Агрегированная статистика автора — для правого рейла WRITE."""
    mine = my_stories_of(username)
    published = [s for s in mine if s.status == "Published"]
    return {
        "total":      len(mine),
        "published":  len(published),
        "on_moderation": sum(1 for s in mine if s.status == "OnModeration"),
        "drafts":     sum(1 for s in mine if s.status == "OnProcess"),
        "views":      sum(s.views for s in mine),
        "likes":      sum(s.likes for s in mine),
        "comments":   sum(s.comments for s in mine),
        "followers":  AUTHORS_BY_USERNAME[username].followers if username in AUTHORS_BY_USERNAME else 0,
    }


# ───────────────────────── Прогресс чтения (для returning hero) ────────────

@dataclass(frozen=True)
class ReadingProgress:
    story_slug: str
    current_chapter: int        # сейчас на этой главе
    quote: str                  # последний абзац, на котором остановился
    minutes_left: int           # приблизительно
    last_read_days: int         # «N күн бұрын»

    @property
    def story(self) -> Story:
        return STORIES_BY_SLUG[self.story_slug]


SAMPLE_PROGRESS = ReadingProgress(
    story_slug="dalney-berega",
    current_chapter=4,
    quote="«…қалай ойлайсыз, бұл саяхатымыздың соңына жеттік пе?» — деді Сандр, біраз үнсіз отырып.",
    minutes_left=18,
    last_read_days=2,
)


# ───────────────────────── Книга недели (FR-HOME-03) ──────────────────────

@dataclass(frozen=True)
class BookOfWeek:
    story_slug: str
    editorial_note: str          # цитата от редакции
    quote: str                   # цитата из книги

    @property
    def story(self) -> Story:
        return STORIES_BY_SLUG[self.story_slug]


BOOK_OF_WEEK = BookOfWeek(
    story_slug="arhimag",
    editorial_note=(
        "Редакциядан: бұл апта мүлдем жаңа басталған туындыға арналды. "
        "«Сиқыршы» сериясының сегізінші кітабы — Алмат Рысқали оқырмандарының ұзақ күткен жалғасы."
    ),
    quote=(
        "«Уақыт ағады, бірақ Сиқыршы үшін бір ғасыр — бір сәт. Ол өзі ойлап тапқан "
        "құдай үшін мың әлемді кезеді — тағы бір сүйікті оқырманын тауып алу үшін.»"
    ),
)


# ───────────────────────── Коллекции (FR-HOME-06) ─────────────────────────

@dataclass(frozen=True)
class Collection:
    """Редакционная подборка — первичный вход в чтение (DEC-31).

    Создаётся только редакцией/админом: пользовательских подборок на портале
    нет (личное хранение — это «Кітапхана»). Подборка отвечает на вопрос
    «зачем читать сейчас», поэтому имя — фраза-состояние, а не жанр.
    """
    slug: str
    name: str
    tint_hue: int                # OKLCH hue для тонировки карточки и иконки
    icon: str                    # slug SVG-иконки из спрайта (без префикса icon-)
    story_slugs: tuple           # все произведения внутри, в порядке подачи
    curator: str = "редакция"    # «Құрастырған: …»
    description: str = ""        # описание подборки на детальной

    @property
    def stories(self) -> list:
        """Все произведения подборки (для детальной)."""
        return [STORIES_BY_SLUG[s] for s in self.story_slugs if s in STORIES_BY_SLUG]

    @property
    def covers(self) -> list:
        """Стопка обложек на карточке — первые три из подборки.

        Отдельного `cover_slugs` нет намеренно: два списка одних и тех же
        слагов рано или поздно разъезжаются. Порядок в `story_slugs` и есть
        редакционный порядок, первые три — витрина.
        """
        return self.stories[:3]

    @property
    def count(self) -> int:
        """Считается по факту, а не хранится: число в UI не может соврать."""
        return len(self.stories)


COLLECTIONS = [
    Collection(
        slug="kulki-kerek", name="Күлкі керек болғанда",
        tint_hue=60, icon="smile", curator="редакция",
        description="Күнің ауыр болса да, бір-екі беттен кейін тынысың ашылатын жеңіл, жылы, тапқыр оқиғалар.",
        story_slugs=(
            "konshi-bala", "balkonnan-korinetin", "atam-aityp-berdi",
            "arqadagy-jaz", "mektep-koridory", "kunnin-songy-sagaty",
        ),
    ),
    Collection(
        slug="auyr-kun", name="Бәрі ауыр болып тұрғанда",
        tint_hue=250, icon="drop", curator="редакция",
        description="Ішіңде көп сөз қалып, бірақ ешкімге айтқың келмейтін күндерге арналған тыныш әрі терең мәтіндер.",
        story_slugs=(
            "almaty-ayazy", "aidana-tan", "sila-imperii",
            "kunnin-songy-sagaty", "balkonnan-korinetin", "arqadagy-jaz",
            "atam-aityp-berdi",
        ),
    ),
    Collection(
        slug="algashky-mahabbat", name="Алғашқы махаббат",
        tint_hue=8, icon="heart", curator="редакция",
        description="Айтылмай қалған сөздер, ыңғайсыз үнсіздік, қызғаныш және бірінші рет біреуді қатты ойлау туралы.",
        story_slugs=(
            "mektep-koridory", "keiipkerge-hat", "aidana-tan",
            "almaty-ayazy", "kunnin-songy-sagaty", "dalney-berega",
        ),
    ),
    Collection(
        slug="kazak-avt", name="Өзіңді бөтен сезінгенде",
        tint_hue=195, icon="feather", curator="редакция",
        description="Сыныпта, үйде немесе өз ойыңның ішінде жалғыз қалғандай сезілген сәттерге арналған оқиғалар.",
        story_slugs=(
            "almaty-ayazy", "temniy-lord", "balkonnan-korinetin",
            "aidana-tan", "kunnin-songy-sagaty", "mektep-koridory", "arhimag",
        ),
    ),
    Collection(
        slug="aramyzda-qubyzhyq", name="Арамыздағы құбыжықтар",
        tint_hue=25, icon="skull", curator="редакция",
        description="Қорқыныш сыртта емес, кейде адамдардың ішінде жүргенін сездіретін триллер мен қараңғы фэнтези.",
        story_slugs=(
            "korkynyshty-koilek", "igra-kuklovoda", "tunge-deiin",
            "temniy-lord", "kronchessii",
        ),
    ),
    Collection(
        slug="kala-anyzdary", name="Қала аңыздары",
        tint_hue=15, icon="cityscape", curator="редакция",
        description="Түнгі көше, жабық подъезд, ескі мектеп, біреу айтып берген сияқты көрінетін қауіпті әңгімелер.",
        story_slugs=(
            "tunge-deiin", "almaty-ayazy", "igra-kuklovoda",
            "korkynyshty-koilek", "aidana-tan", "kronchessii",
        ),
    ),
    Collection(
        slug="geimerler-turaly", name="Ойыннан кейін де ойда қалатын",
        tint_hue=280, icon="planet", curator="редакция",
        description="Виртуал әлем, команда, жеңіс құмарлығы және экран сөнгеннен кейін басталатын шынайы таңдау.",
        story_slugs=(
            "zhuldyz-kartasy", "kronchessii", "arhimag",
            "temniy-lord", "dalney-berega", "igra-kuklovoda",
        ),
    ),
    Collection(
        slug="sport-minez", name="Спорт мінезді шыңдағанда",
        tint_hue=130, icon="trophy", curator="редакция",
        description="Жаттығу, жарыс, қысым, жеңіліс және өзіңді қайта жинап шығу туралы жігерлі мәтіндер.",
        story_slugs=(
            "arqadagy-jaz", "sila-imperii", "dalney-berega",
            "kunnin-songy-sagaty", "balkonnan-korinetin",
        ),
    ),
    Collection(
        slug="mektep-qupiyalary", name="Мектептегі құпиялар",
        tint_hue=145, icon="backpack", curator="редакция",
        description="Күнделік, сыныптағы сыбыс, жоғалған заттар және сабақтан кейін ашылатын кішкентай детективтер.",
        story_slugs=(
            "mektep-koridory", "igra-kuklovoda", "tunge-deiin",
            "konshi-bala", "arqadagy-jaz", "balkonnan-korinetin", "arhimag",
        ),
    ),
    Collection(
        slug="bir-keshke", name="Бір кешке жететін қысқа мәтіндер",
        tint_hue=210, icon="book", curator="редакция",
        description="Ұзақ серияға кірмей-ақ, бүгін бастап бүгін аяқтағың келетін қысқа әрі жинақы оқиғалар.",
        story_slugs=(
            "kunnin-songy-sagaty", "tunge-deiin", "konshi-bala",
            "mektep-koridory", "atam-aityp-berdi", "almaty-ayazy",
            "korkynyshty-koilek", "balkonnan-korinetin", "sila-imperii",
        ),
    ),
]


def collections_of(story: "Story") -> list:
    """Подборки, в которых лежит произведение (обратный вход с STORY-страницы).

    Порядок — как в COLLECTIONS: он редакционный, а не по релевантности.
    """
    return [c for c in COLLECTIONS if story.slug in c.story_slugs]


COLLECTIONS_BY_SLUG = {c.slug: c for c in COLLECTIONS}


# ───────────────────────── Конкурсы (CONT) ─────────────────────────────────

@dataclass(frozen=True)
class JuryMember:
    name: str
    role: str   # «Төраға», «Мүше», ...


@dataclass(frozen=True)
class TimelineStage:
    label: str          # «Өтінім қабылдау»
    period: str         # «10 қаз — 5 жел»
    state: str          # 'done' | 'active' | 'upcoming'


@dataclass(frozen=True)
class Contest:
    slug: str
    name: str
    subtitle: str                # категория/подзаголовок
    status: str                  # 'active' | 'finished'
    days_left: Optional[int]     # для active
    prize_kzt: Optional[int]     # для active
    submissions: int
    cover: str = "img/book1.jpg"
    description: str = ""
    conditions: tuple = ()       # bullet points
    timeline: tuple = ()         # TimelineStage[]
    jury: tuple = ()             # JuryMember[]
    # BR-22: пороги объёма для подачи (знаки)
    min_chars: int = 5_000
    max_chars: int = 15_000


CONTESTS = [
    Contest(
        "bolashak-mektebi", "«Болашақтың мектебі»", "Оқушыларға арналған әдеби байқау",
        status="active", days_left=12, prize_kzt=500_000, submissions=87,
        cover="img/book1.jpg",
        description=(
            "Республикалық мектеп оқушыларына арналған әдеби байқау. Мақсаты — "
            "жас прозаиктерді табу әрі қолдау. Қазақ және орыс тілдеріндегі шығармалар қабылданады."
        ),
        conditions=(
            "Қатысушы жасы — 14-18 жас",
            "Жанры еркін, көлемі 5 000-15 000 таңба",
            "Шығарма бұған дейін басқа платформаларда жарияланбауы керек",
            "Бір автор — бір өтінім (BR-23)",
        ),
        timeline=(
            TimelineStage("Өтінім қабылдау", "10 қаз — 5 жел", "active"),
            TimelineStage("Қазылар қарауы", "6 жел — 15 жел", "upcoming"),
            TimelineStage("Жеңімпаздар", "20 жел", "upcoming"),
        ),
        jury=(
            JuryMember("Алмат Рысқали", "Төраға"),
            JuryMember("Бекжан Тұрсынов",   "Мүше"),
            JuryMember("Дина Айдарбекова",  "Мүше"),
        ),
    ),
    Contest(
        "altyn-qalam-2024", "Алтын қалам — 2024", "Жас прозаиктер байқауы",
        status="active", days_left=14, prize_kzt=300_000, submissions=42,
        cover="img/book2.jpg",
        description=(
            "Қазақ тіліндегі жас прозаиктердің ұлттық байқауы. "
            "Үздік үш шығарма платформаның басты бетінде жарияланып, "
            "сыйақы алады."
        ),
        conditions=(
            "Қатысушы жасы — 14-18 жас",
            "Тек қазақ тілінде",
            "Көлемі 5 000-15 000 таңба",
            "AI-декларация міндетті (DEC-21)",
        ),
        timeline=(
            TimelineStage("Жарияланды", "1 қыр", "done"),
            TimelineStage("Өтінім қабылдау", "1 қыр — 1 жел", "active"),
            TimelineStage("Шорт-лист", "5 жел", "upcoming"),
            TimelineStage("Финал", "15 жел", "upcoming"),
        ),
        jury=(
            JuryMember("Айгерім Қасенова", "Төраға"),
            JuryMember("Сайын Нұрбекұлы",  "Мүше"),
        ),
    ),
    Contest(
        "zhas-aldym-2023", "Жас алдым — 2023", "Жабылды",
        status="finished", days_left=None, prize_kzt=None, submissions=156,
        cover="img/book3.jpg",
        description="2023 жылғы байқау аяқталды. Жеңімпаздар: «Күңгірт мырза», «Қуыршақшының ойыны».",
        conditions=(),
        timeline=(
            TimelineStage("Өтінім қабылдау", "1 қыр — 1 жел", "done"),
            TimelineStage("Финал", "15 жел", "done"),
        ),
        jury=(JuryMember("Алмат Рысқали", "Төраға"),),
    ),
]

CONTESTS_BY_SLUG = {c.slug: c for c in CONTESTS}

ACTIVE_CONTESTS = [c for c in CONTESTS if c.status == "active"]
HERO_CONTEST = ACTIVE_CONTESTS[0]


# ───────────────────────── CONT — заявки автора ───────────────────────────

@dataclass(frozen=True)
class Submission:
    contest_slug: str
    story_slug: str
    submitted_relative: str    # «3 күн бұрын», «бүгін»
    status: str                # 'reviewing' | 'accepted' | 'rejected'
    note: str = ""             # жюри-комментарий (для rejected/accepted)

    @property
    def contest(self):
        return CONTESTS_BY_SLUG.get(self.contest_slug)

    @property
    def story(self):
        return STORIES_BY_SLUG.get(self.story_slug)


SUBMISSIONS_BY_USER: dict = {
    "aidana": [
        Submission(
            contest_slug="altyn-qalam-2024", story_slug="aidana-tan",
            submitted_relative="5 күн бұрын", status="reviewing",
        ),
        Submission(
            contest_slug="zhas-aldym-2023", story_slug="aidana-kysh",
            submitted_relative="6 ай бұрын", status="rejected",
            note="Көлемі шарттан асып кеткен.",
        ),
    ],
}


def submissions_of(username: str) -> list:
    return SUBMISSIONS_BY_USER.get(username, [])


def has_submission(username: str, contest_slug: str) -> bool:
    """BR-23: один автор — одна работа на конкретный конкурс."""
    return any(s.contest_slug == contest_slug for s in submissions_of(username))


def submission_checklist(story: "Story", contest: "Contest") -> list:
    """BR-22: чек-лист соответствия конкретного произведения требованиям конкурса.

    Возвращает список dict'ов: [{key, label, passed, hint}, ...].
    Сейчас «объём» — единственная авто-проверка; остальное — статичные подсказки
    либо требуют декларации автора (AI/возраст/оригинальность).
    """
    # Считаем объём по сумме char_count глав (если есть) или по фикс-аппрокс
    total_chars = sum(c.char_count for c in chapters_of(story.slug)) or 0
    if total_chars < contest.min_chars:
        vol_passed, vol_hint = False, f"Көлемі тым аз — {total_chars} таңба (мин. {contest.min_chars})"
    elif total_chars > contest.max_chars:
        vol_passed, vol_hint = False, f"Көлемі тым үлкен — {total_chars} таңба (макс. {contest.max_chars})"
    else:
        vol_passed, vol_hint = True, f"{total_chars} таңба — нормада"

    return [
        {"key": "volume",    "label": "Көлемі (5 000-15 000 таңба)", "passed": vol_passed,
         "hint": vol_hint, "auto": True},
        {"key": "language",  "label": "Тіл — қазақша немесе орысша", "passed": True,
         "hint": "Платформа екі тілді қолдайды.", "auto": False},
        {"key": "original",  "label": "Оригиналдылық", "passed": True,
         "hint": "Шығарма басқа платформаларда жарияланбаған.", "auto": False},
        {"key": "ai_decl",   "label": "AI-декларация (DEC-21)", "passed": False,
         "hint": "AI-көмек қолданылды ма? — өтінім бергенде анық белгілеу қажет.", "auto": False, "required": True},
        {"key": "age",       "label": "Жас 14-18", "passed": True,
         "hint": "Профильдегі жасқа сәйкес тексеріледі.", "auto": False},
    ]


def eligible_for_contest(username: str, contest_slug: str) -> list:
    """Произведения пользователя, проходящие порог объёма (BR-24).

    Возвращает [(story, total_chars, eligible_bool), ...] — UI сам решает рендер.
    """
    contest = CONTESTS_BY_SLUG.get(contest_slug)
    if not contest:
        return []
    result = []
    for s in my_stories_of(username):
        total = sum(c.char_count for c in chapters_of(s.slug))
        is_ok = contest.min_chars <= total <= contest.max_chars
        result.append({"story": s, "chars": total, "eligible": is_ok})
    return result


# ───────────────────────── Авторлар мектебі — внешние ссылки (FR-LINKS) ────

@dataclass(frozen=True)
class SchoolLink:
    channel: str   # 'youtube' | 'instagram' | 'tiktok' | 'telegram'
    title: str     # «YouTube», «Instagram», …
    subtitle: str  # тип контента
    url: str


SCHOOL_LINKS = [
    SchoolLink("youtube",   "YouTube",   "Вебинарлар мен курстар",     "#"),
    SchoolLink("instagram", "Instagram", "Интервью, сұрақ-жауап",      "#"),
    SchoolLink("tiktok",    "TikTok",    "Пайдалы кеңес, идеялар",     "#"),
    SchoolLink("telegram",  "Telegram",  "Ең қызық шығармалар",         "#"),
]


# ───────────────────────── LIB — библиотека читателя ──────────────────────

@dataclass(frozen=True)
class LibraryEntry:
    """Запись в библиотеке пользователя. Тип задаётся `kind`.

    - 'saved'   — Сақталған (отложил «на потом»)
    - 'reading' — Оқу үстіндегі (читает сейчас); progress_chapter — текущая глава
    - 'done'    — Оқылғаны (прочитал)
    """
    story_slug: str
    kind: str                       # 'saved' | 'reading' | 'done'
    added_relative: str             # «бүгін», «3 күн бұрын» и т.п.
    progress_chapter: int = 1       # имеет смысл только для 'reading'

    @property
    def story(self) -> Story:
        return STORIES_BY_SLUG[self.story_slug]


# Библиотека Айданы. Используется PROF/LIB.
LIBRARY_BY_USER: dict = {
    "aidana": [
        # ── Оқу үстіндегі ──
        LibraryEntry("dalney-berega",  "reading", "2 күн бұрын", progress_chapter=4),
        LibraryEntry("kronchessii",    "reading", "1 апта бұрын", progress_chapter=2),
        # ── Сақталған ──
        LibraryEntry("temniy-lord",    "saved",   "бүгін"),
        LibraryEntry("igra-kuklovoda", "saved",   "3 күн бұрын"),
        LibraryEntry("arhimag",        "saved",   "2 апта бұрын"),
        # ── Оқылғаны ──
        LibraryEntry("sila-imperii",   "done",    "1 ай бұрын"),
    ],
}


def library_of(username: str, kind: str = "") -> list:
    """Записи библиотеки. Если kind задан — фильтр по типу."""
    entries = LIBRARY_BY_USER.get(username, [])
    if kind:
        return [e for e in entries if e.kind == kind]
    return entries


def reader_stats(username: str) -> dict:
    """Сводка для PROF: своя статистика читателя/автора."""
    mine = my_stories_of(username)
    lib  = library_of(username)
    return {
        # «Шығарма» — собственные произведения
        "works":     len(mine),
        # «Ұнатулар» — лайки на собственных произведениях (сумма)
        "likes":     sum(s.likes for s in mine),
        # «Оқылды» — сколько прочитал (записей с kind='done')
        "read":      sum(1 for e in lib if e.kind == "done"),
        # «Жазылулар» — подписчики автора (если автор)
        "followers": AUTHORS_BY_USERNAME[username].followers if username in AUTHORS_BY_USERNAME else 0,
    }


# ───────────────────────── PROF — граф подписок ───────────────────────────

# username → set[username]; «X подписан на Y» означает Y ∈ FOLLOWING[X].
FOLLOWING: dict = {
    "aidana":    {"rudazov", "sayyn", "dina_books"},
    "bekzhan_t": {"rudazov"},
    "aygerim_k": {"rudazov", "aidana"},
}


def is_following(me: str, them: str) -> bool:
    return them in FOLLOWING.get(me, set())


def followers_of(username: str) -> list:
    """Authors, которые подписаны на username — выводим в PROF (для своего профиля)."""
    return [AUTHORS_BY_USERNAME[u] for u in FOLLOWING if username in FOLLOWING[u]]


def following_of(username: str) -> list:
    """Authors, на которых подписан username."""
    return [AUTHORS_BY_USERNAME[u] for u in FOLLOWING.get(username, set()) if u in AUTHORS_BY_USERNAME]


# ───────────────────────── NOTIF — уведомления ────────────────────────────

# Типы (FR-NOTIF-03):
#   comment      — новый комментарий к твоему произведению
#   like         — лайк твоему произведению
#   new_chapter  — новая глава у отслеживаемого автора/произведения
#   follower     — новый подписчик
#   moderation   — результат модерации (одобрено / отклонено)
#   contest      — статус заявки на конкурс
NOTIF_KINDS = ("comment", "like", "new_chapter", "follower", "moderation", "contest")

# Группы по времени (FR-NOTIF-01).
NOTIF_BUCKETS = ("today", "yesterday", "past_week")
NOTIF_BUCKET_LABELS = {
    "today":     "Бүгін",
    "yesterday": "Кеше",
    "past_week": "Өткен аптада",
}


@dataclass(frozen=True)
class Notification:
    kind: str               # см. NOTIF_KINDS
    bucket: str             # 'today' | 'yesterday' | 'past_week'
    when: str               # «2 сағат бұрын», «кеше 18:40», «5 қаңтар»
    actor_username: str = ""    # кто инициатор (для comment/like/follower); '' если системное
    story_slug: str = ""        # к чему относится (для comment/like/new_chapter); '' если нет
    text: str = ""              # короткое тело (для comment — выдержка, для остальных — auto-build)
    read: bool = False          # прочитано ли

    @property
    def actor(self):
        return AUTHORS_BY_USERNAME.get(self.actor_username) if self.actor_username else None

    @property
    def story(self):
        return STORIES_BY_SLUG.get(self.story_slug) if self.story_slug else None


NOTIFICATIONS_BY_USER: dict = {
    "aidana": [
        # ── Бүгін ──
        Notification(
            kind="comment", bucket="today", when="2 сағат бұрын",
            actor_username="aygerim_k", story_slug="aidana-tan",
            text="Соңғы бөлім жанға тиді. Сегізіншіде Айданың Таразға қайтуы — нағыз қазақша драма!",
        ),
        Notification(
            kind="like", bucket="today", when="4 сағат бұрын",
            actor_username="bekzhan_t", story_slug="aidana-tan",
        ),
        Notification(
            kind="moderation", bucket="today", when="бүгін 09:15",
            story_slug="aidana-erteg",
            text="«Ертегі ертеректегі» — модерациядан өтуде. 1-2 күн қажет.",
        ),
        # ── Кеше ──
        Notification(
            kind="follower", bucket="yesterday", when="кеше 18:40",
            actor_username="dina_books", read=True,
        ),
        Notification(
            kind="new_chapter", bucket="yesterday", when="кеше 14:20",
            actor_username="rudazov", story_slug="arhimag",
            text="«Сиқыршы: бөтен әлемдер» — жаңа бөлім қосылды.",
            read=True,
        ),
        # ── Өткен аптада ──
        Notification(
            kind="like", bucket="past_week", when="3 күн бұрын",
            actor_username="sayyn", story_slug="aidana-kysh", read=True,
        ),
        Notification(
            kind="contest", bucket="past_week", when="5 күн бұрын",
            text="«Алтын қалам — 2024» байқауына өтінімің қабылданды.",
            read=True,
        ),
        Notification(
            kind="comment", bucket="past_week", when="6 күн бұрын",
            actor_username="rudazov", story_slug="aidana-tan",
            text="Жас автордың тілі жаңа да жанды. Әрі қарай жалғастыр.",
            read=True,
        ),
    ],
}


def notifications_for_user(username: str) -> dict:
    """Уведомления, сгруппированные по бакетам времени (FR-NOTIF-01).

    Возвращает {'today': [...], 'yesterday': [...], 'past_week': [...]}.
    """
    items = NOTIFICATIONS_BY_USER.get(username, [])
    grouped = {b: [] for b in NOTIF_BUCKETS}
    for n in items:
        if n.bucket in grouped:
            grouped[n.bucket].append(n)
    return grouped


def unread_count_for_user(username: str) -> int:
    """Сколько непрочитанных уведомлений у пользователя (для бейджа в шапке)."""
    return sum(1 for n in NOTIFICATIONS_BY_USER.get(username, []) if not n.read)


# ───────────────────────── Глобальные «цифры платформы» ────────────────────

PLATFORM_STATS = {
    "stories":  12_384,
    "authors":   4_821,
    "contests":      3,
}

