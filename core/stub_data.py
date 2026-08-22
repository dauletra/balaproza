"""
Стаб-данные для дизайн-фазы. Здесь живут все «как будто из БД» сущности,
которые рисует UI. После Ф14 этот файл заменится на Django-модели.

Не импортировать в продакшен-логику — это сугубо для рендера шаблонов.
"""

import zlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional


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
    followers: int
    # Год прихода на платформу — «2024 жылдан бері» в шапке профиля.
    # Единственный факт профиля, который нельзя вывести из данных: следов
    # регистрации в стабе нет. Год, а не полная дата: подростку важно «давно
    # или недавно», а не день; точная дата — лишние персональные данные.
    joined_year: int

    @property
    def public_name(self) -> str:
        return self.pen_name or f"@{self.username}"

    @property
    def works(self) -> int:
        """Сколько работ автора видит читатель.

        Было хранимым литералом и врало у всех шести авторов сразу: у
        `rudazov` стояло 12 при трёх произведениях, у `sayyn` — 2 при трёх.
        Число рендерится в шести местах, включая карточку автора на странице
        произведения и блок «Жаңа авторлар» на главной, — то есть ошибка была
        видна читателю везде, кроме того места, где её можно было заметить.
        Считается, как `Collection.count`: из данных, не рядом с ними.

        Считаются только публичные статусы: черновик публично не виден
        (BR-10), и попадать в публичный счётчик он не должен — иначе число
        выдаёт читателю, что у автора есть неопубликованное.
        """
        return sum(1 for s in STORIES
                   if s.author_username == self.username and s.is_public)


AUTHORS = [
    Author("rudazov",   "Алмат Рысқали",     "Rudazov",       "Фэнтези, шытырман",      8420, 2023),
    Author("aygerim_k", "Айгерім Қасенова",  "aiqalam",       "Жас прозаик · Алматы",    184, 2024),
    Author("bekzhan_t", "Бекжан Тұрсынов",   "BekTor",        "Қалалық әңгімелер",       312, 2024),
    Author("dina_books","Дина Айдарбекова",  "dina.books",    "Балалар әдебиеті",        542, 2023),
    Author("sayyn",     "Сайын Нұрбекұлы",   "sayyn",         "Фантастика, шытырман",     96, 2025),
    # Демо-пользователь, под которым логинимся через фейк-сессию (см. core.views.login_view).
    Author("aidana",    "Айдана Серікқызы",  "aidana",        "Жас прозаик · Тараз",      23, 2025),
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
    # Просмотры за последние 14 дней — ось «Қазір танымал» (DEC-36).
    # Накопленный `views` отвечает на «что читали когда-то», а каталог должен
    # отвечать на «что читают сейчас»: без окна первую страницу навсегда
    # занимают несколько старых хитов. После Ф14 — агрегат по логу просмотров.
    recent_views: int = 0
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
    # Сколько дней назад автор трогал работу в последний раз. None — не задано:
    # в кабинете показывается только своё, и заполнены только те произведения,
    # которые там бывают. В Ф14 это `updated_at` с auto_now, а не число дней —
    # хранить дельту нельзя, она устаревает каждые сутки. Ось «что я трогал
    # последним» держится на этом поле: до него порядок списка был порядком
    # объявления в STORIES.
    updated_days_ago: int | None = None

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
    def is_public(self) -> bool:
        """Видит ли работу читатель. По PUBLIC_STATUSES, а не по литералу
        'Published' — иначе из выдачи молча пропадают все сериалы (DEC-37)."""
        return self.status in PUBLIC_STATUSES

    @property
    def updated_label(self) -> str:
        """«кеше», «3 күн бұрын», «2 апта бұрын». Пусто, если дата не задана."""
        days = self.updated_days_ago
        if days is None:
            return ""
        if days <= 0:
            return "бүгін"
        if days == 1:
            return "кеше"
        if days < 7:
            return f"{days} күн бұрын"
        if days < 30:
            return f"{days // 7} апта бұрын"
        return f"{days // 30} ай бұрын"

    @property
    def text_chapter(self) -> int | None:
        """Номер главы с текстом одночастного произведения; None — текста ещё нет.

        У `single` глава ровно одна, и кнопка «Мәтін» обязана вести в неё, а не
        в пустой редактор: иначе автор сохранит вторую главу у книги, у которой
        текст один по определению. Для сериала возвращает None — там «Бөлім
        қосу» и правда создаёт новую главу.
        """
        if not self.is_single:
            return None
        chapters = chapters_of(self.slug)
        return chapters[0].number if chapters else None

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
        """Бакет времени чтения.

        Границы взяты из намерения читателя, а не из нынешнего корпуса: до
        десяти минут читают между делом — на перемене, в дороге; десять-тридцать
        это целый рассказ за один заход; дальше начинается чтение, которое не
        помещается в один присест и требует закладки. Прежние 15/35 были
        подобраны под романы: 95% стаба лежало в первом бакете, а третий не
        набирался никогда.

        Подгонять их под распределение нельзя — какие произведения реально
        опубликуют, мы не знаем, а намерение «хочу быстрое» / «хочу надолго»
        от состава каталога не зависит.
        """
        if self.read_minutes <= 10:
            return "short"
        if self.read_minutes <= 30:
            return "medium"
        return "long"


STORIES = [
    Story("dalney-berega",  "Алыс жағалауларда",     "sayyn",      "ipad_19b0bc4bcd9c1a1dc4c3cc12cf20dce5.webp", ("fantastika",  None),         12, 12482, 4821, 312, status="Completed", recent_views=2980, annotation="Үш дос жоғалған жолды іздеп шығады. Таудағы сапар оларды өз қорқынышымен, достықпен және белгісіз ауылдың құпиясымен беттестіреді.", tags=("arman", "sayahat", "jasospirim"), audience="10+", badges=("Редакция таңдауы",)),
    Story("temniy-lord",    "Күңгірт мырза",         "bekzhan_t",  "ipad_42f033cf1b9a2bcad744d05b9d429609.webp", ("fantezi",     "horror"),      3,  8920, 2440, 156, status="OnProcess", recent_views=1810, annotation="Қараңғы патшалыққа түскен жас кейіпкер биліктің бағасын түсіне бастайды. Сиқыр, қорқыныш және таңдау туралы фэнтези.", tags=("mistika", "arman", "basqa-alem"), audience="14+"),
    Story("igra-kuklovoda", "Қуыршақшының ойыны",    "dina_books", "ipad_499539963221e0fe36b0888bf8601067.webp", ("triller",     "drama"),       3, 18102, 6230, 421, status="OnProcess", recent_views=4120, annotation="Мектептегі тыныш күндер бір жұмбақ ойыннан кейін өзгереді. Әр белгі жаңа күдікке апарады, ал шындық жақын жерде жасырынып тұр.", tags=("mistika", "jasospirim", "detektiv-jas"), audience="14+", badges=("Байқауға қатысады",)),
    Story("kronchessii",    "Тас уәделер",           "rudazov",    "ipad_5916b4e19c616e74d008125ba9a1be8e.webp", ("shyttyrman",  "fantezi"),     3, 32540, 11200, 890, status="Completed", recent_views=890, annotation="Ескі қала қабырғаларындағы тасқа қашалған уәделер оянады. Кейіпкерлер өткеннің шартын бұзбай, болашақты сақтауға тырысады.", tags=("sayahat", "arman", "syikyr-akademiya")),
    Story("arhimag",        "Сиқыршы: бөтен әлемдер","rudazov",    "ipad_940e074d12d6c3657199601ca568f1b3.jpg",  ("fantezi",     "shyttyrman"),  3, 12482, 4821, 312, status="OnProcess", recent_views=740, annotation="Жас сиқыршы бөтен әлемдердің есігін ашқанда, әр әлем өз ережесін ұсынады. Үйге қайту үшін ол күштен бұрын жауапкершілікті үйренеді.", tags=("syikyr-akademiya", "arman", "dostyk", "jasospirim", "mektep")),
    Story("sila-imperii",   "Империя құдіреті",      "aygerim_k",  "ipad_992f1631a421d74ed5e1aa72717df374.webp", ("tarih",       "drama"),       1, 14200, 3890, 245, status="Published", recent_views=610, annotation="Көне империяның шетінде өскен жас батыр тарихтың үлкен толқынына түседі. Бұл шығарма билік, адалдық және ел алдындағы таңдау туралы.", tags=("arman", "jasospirim"), format="single"),

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
        recent_views=2210, annotation="Күн батпай тұрып бір нәрсені үлгеру керек. Он жеті жасар бала уақыттың қалай тоқтайтынын біледі.",
        tags=("arman", "jasospirim"), audience="10+",
    ),
    Story(
        slug="mektep-koridory", title="Мектеп дәлізіндегі хат", author_username="aygerim_k",
        cover="", genres=("romantika", "drama"),
        chapters=1, views=9240, likes=2110, comments=188,
        status="Published", format="single", secondary_genre="drama",
        recent_views=3450, annotation="Партаның астынан табылған хат кімге жазылғаны белгісіз. Бірақ оны оқыған қыз енді бұрынғыдай жүре алмайды.",
        tags=("mektep", "gashyqtyq", "jasospirim"), audience="10+",
    ),
    Story(
        slug="atam-aityp-berdi", title="Атам айтып берген ертегі", author_username="dina_books",
        cover="", genres=("erteg", None),
        chapters=1, views=3120, likes=540, comments=41,
        status="Published", format="single",
        recent_views=1620, annotation="Ауылдағы жаз, кешкі шай және атаның бір ертегісі. Ол ертегіде жоғалған қой да, жоғалған бала да бар.",
        tags=("dostyk", "mektep"), audience="10+",
    ),
    Story(
        slug="konshi-bala", title="Көрші бала", author_username="bekzhan_t",
        cover="", genres=("komediya", None),
        chapters=1, views=7830, likes=1420, comments=133,
        status="Published", format="single",
        recent_views=980, annotation="Көршінің баласы күнде бір нәрсе бүлдіреді. Бүгін ол менің велосипедімді ұрлады — бірақ себебі күлкілі.",
        tags=("dostyk", "mektep", "jasospirim"), audience="10+",
    ),
    Story(
        slug="tunge-deiin", title="Түнге дейін үш сағат", author_username="bekzhan_t",
        cover="ipad_fe6ce3337de7c1c1bf18ef8bb0f3f9a3.webp", genres=("triller", None),
        chapters=1, views=11470, likes=2890, comments=241,
        status="Published", format="single",
        recent_views=1150, annotation="Лифт екі қабат арасында тоқтады. Ішінде екеу, ал біреуі шындықты айтпай тұр.",
        tags=("mistika", "detektiv-jas"), audience="14+",
    ),
    Story(
        slug="almaty-ayazy", title="Алматы аязы", author_username="aygerim_k",
        cover="", genres=("drama", None),
        chapters=1, views=4980, likes=760, comments=58,
        status="Published", format="single",
        recent_views=2740, annotation="Қаңтардағы қала, жылымаған автобус және әкесімен алғаш рет ашық сөйлескен күн.",
        tags=("jasospirim", "arman"), audience="14+",
    ),
    Story(
        slug="balkonnan-korinetin", title="Балконнан көрінетін әлем", author_username="dina_books",
        cover="", genres=("balalar", None),
        chapters=1, views=2640, likes=430, comments=27,
        status="Published", format="single",
        recent_views=1490, annotation="Тоғызыншы қабаттан бүкіл ауланы көруге болады. Ал кейде — өзіңді де.",
        tags=("dostyk", "arman"), audience="10+",
    ),
    Story(
        slug="korkynyshty-koilek", title="Қорқынышты көйлек", author_username="bekzhan_t",
        cover="", genres=("horror", None),
        chapters=1, views=8150, likes=1630, comments=204,
        status="Published", format="single",
        recent_views=620, annotation="Ескі шкафтан табылған көйлекті киген адам түнде өз атын ұмытады.",
        tags=("mistika",), audience="14+",
    ),
    Story(
        slug="zhuldyz-kartasy", title="Жұлдыз картасы", author_username="rudazov",
        cover="", genres=("fantastika", "shyttyrman"),
        chapters=17, views=15320, likes=3940, comments=387,
        status="Completed", secondary_genre="shyttyrman",
        recent_views=1240, annotation="Ғарыш кемесінің картасында болмауға тиіс бір нүкте бар. Экипаж соған қарай бет алады.",
        tags=("aua-ralighi", "sayahat", "arman"), audience="10+",
        badges=("Редакция таңдауы",),
    ),
    Story(
        slug="kokjal-anyzy", title="Көкжал аңызы", author_username="dina_books",
        cover="", genres=("tarih", "erteg"),
        chapters=19, views=6720, likes=1180, comments=94,
        status="Completed", secondary_genre="erteg",
        recent_views=430, annotation="Далада бір қасқыр туралы аңыз жүреді. Оны естіген әр ұрпақ басқаша айтады.",
        tags=("sayahat", "dostyk"), audience="10+",
    ),
    Story(
        slug="keiipkerge-hat", title="Кейіпкерге жазылған хат", author_username="aygerim_k",
        cover="", genres=("fanfik", "romantika"),
        chapters=5, views=10940, likes=3210, comments=452,
        status="OnProcess", secondary_genre="romantika",
        recent_views=3120, annotation="Сүйікті кітабының кейіпкеріне хат жазған қыз кенет жауап алады.",
        tags=("gashyqtyq", "syikyr-akademiya", "jasospirim"), audience="14+",
    ),
    Story(
        slug="arqadagy-jaz", title="Арқадағы жаз", author_username="sayyn",
        cover="", genres=("balalar", "drama"),
        chapters=7, views=3890, likes=610, comments=45,
        status="OnProcess", secondary_genre="drama",
        recent_views=260, annotation="Жазғы каникул, ескі велосипед және ауылдағы жеті апта. Әр бөлім — бір апта.",
        tags=("dostyk", "sayahat", "mektep"), audience="10+",
    ),

    # ─ Произведения демо-пользователя «Айдана» (для WRITE-страниц) ─
    Story(
        slug="aidana-tan",    title="Таң алдында",            author_username="aidana",
        cover="ipad_c9217632f98051fd88ca5763f218a9e3.webp", genres=("drama", None),
        chapters=8, views=1042, likes=87, comments=12,
        status="OnProcess", recent_views=310, annotation="Жас қыздың Алматыдан Таразға қайту туралы әңгімесі. Сегіз бөлімде, әр бөлім — жаңа қала.",
        tags=("sayahat", "jasospirim", "arman", "experimental"),
        updated_days_ago=2,
        # Заявка на активный «Алтын қалам — 2024» лежала в SUBMISSIONS_BY_USER,
        # а бейджа на работе не было: каталог по оси badge=contest её не находил,
        # хотя автор в конкурсе участвует. Инвариант держит
        # test_stub_data.SubmissionsMatchContestBadges.
        badges=("Байқауға қатысады",),
    ),
    Story(
        slug="aidana-koshe",  title="Көше әндері",            author_username="aidana",
        cover="ipad_e655bb59097d8f25698466168d385969.webp", genres=("drama", "komediya"),
        chapters=1, views=203, likes=18, comments=4,
        status="Published", recent_views=203, annotation="Қаладағы бес адамның бір күні. Әрқайсысының өз әні.",
        secondary_genre="komediya",
        tags=("aua-ralighi", "dostyk", "mektep"),
        format="single",
        updated_days_ago=12,
    ),
    Story(
        slug="aidana-erteg",  title="Ертегі ертеректегі",      author_username="aidana",
        cover="ipad_eec6a1375d9124c7348c7579b8d2db33.jpg", genres=("erteg", None),
        # chapters=0 — это фикстура «произведение без глав» для manage_story
        # (test_write.ManageStoryEmptyChapters). Раньше здесь стояло 3: карточка
        # в «Менің шығармаларым» обещала 3 бөлім, а «Басқару» открывалась
        # пустой. Записи в CHAPTERS_BY_STORY обязаны нести текст
        # (test_stub_data.test_stub_chapters_have_loaded_body_text), поэтому
        # честное здесь — ноль, а не три пустые главы.
        chapters=0, views=0, likes=0, comments=0,
        status="OnModeration", recent_views=0, annotation="Дәстүрлі ертегі формасында жазылған заманауи тарих.",
        updated_days_ago=4,
    ),
    Story(
        slug="aidana-kysh",   title="Қыстың үнсіздігі",        author_username="aidana",
        cover="ipad_f0e918b204613b38cc0e04ba74e3e3ab.webp", genres=("drama", None),
        chapters=1, views=872, likes=64, comments=9,
        status="Published", recent_views=190, annotation="Қыстағы ауылда қалған әжемен өткізген бір ай. Аяқталған кітап.",
        format="single",
        updated_days_ago=45,
    ),
    # Черновик. В демо-наборе его не было вовсе, хотя NotPublished — дефолт
    # нового произведения (BR-10): нейтральный бейдж «Жоба» (DEC-39) и сигнал
    # «начата, но ни одного бөлім» негде было увидеть. Сериал, а не single:
    # у одночастного в стабе обязана быть ровно одна загруженная глава
    # (test_stub_data.test_single_stories_have_one_loaded_chapter).
    Story(
        slug="aidana-kus",    title="Құс жолы",                author_username="aidana",
        cover="", genres=("fantastika", None),
        chapters=0, views=0, likes=0, comments=0,
        status="NotPublished", recent_views=0,
        annotation="Ауыл баласы мен түнгі аспан туралы. Әзірге бас-аяғы ойда.",
        updated_days_ago=9,
    ),
]

STORIES_BY_SLUG = {s.slug: s for s in STORIES}


# ───────────────────────── Реакции на главу ───────────────────────────────

@dataclass(frozen=True)
class Reaction:
    """Одна реакция читателя на главу (FR-STORY-12, DEC-32).

    Словарь закрытый: пять штук, пользовательских реакций нет. Открытый
    список означал бы бесконечную модерацию и длинный хвост мёртвых кнопок.
    """
    slug: str
    label: str    # первое лицо — читатель говорит о себе, как в docs/16 («сен»)
    icon: str     # symbol в спрайте; эмодзи запрещены, поэтому только SVG
    hint: str     # как это читать автору в разбивке по главам


# Порядок фиксирован и в данных, и в интерфейсе: кнопки не должны прыгать
# местами по мере голосования.
REACTIONS = (
    Reaction("kuldim",    "Күлдім",    "smile",        "күлкілі болды"),
    Reaction("jyladym",   "Жыладым",   "drop",         "қатты әсер етті"),
    Reaction("juregim",   "Жүрегім",   "heart-filled", "романтикалық"),
    Reaction("shabyt",    "Шабыт",     "feather",      "жазуға шабыттандырды"),
    Reaction("tangaldym", "Таңғалдым", "sparkle",      "күтпеген бұрылыс"),
)

REACTIONS_BY_SLUG = {r.slug: r for r in REACTIONS}


# ───────────────────────── Главы (для STORY/READ) ─────────────────────────

@dataclass(frozen=True)
class Chapter:
    number: int            # 1-based
    title: str
    char_count: int        # для «X / N» прогресса
    body: str = ""         # длинный текст для режима чтения
    # Реакции главы: пары (reaction_slug, count). Кортеж, а не dict, —
    # Chapter заморожен и должен оставаться хешируемым.
    reactions: tuple = ()
    my_reaction: str = ""  # что поставил текущий пользователь; "" — ничего

    @property
    def char_count_formatted(self) -> str:
        n = self.char_count
        if n >= 1000:
            return f"{n // 1000},{(n % 1000) // 100} мың"
        return str(n)

    @property
    def reaction_counts(self) -> dict:
        return dict(self.reactions)

    @property
    def likes(self) -> int:
        """Совокупная реакция главы — число для карточек и шапки.

        Раскладка «чем зацепило» нужна автору и читателю внутри главы,
        но в каталоге пять цифр на карточке превратили бы сетку в дашборд.
        """
        return sum(count for _, count in self.reactions)

    @property
    def top_reaction(self) -> Reaction | None:
        """Самая частая реакция — «чем зацепило» одним словом."""
        if not self.reactions:
            return None
        slug = max(self.reactions, key=lambda pair: pair[1])[0]
        return REACTIONS_BY_SLUG.get(slug)


STORY_TEXTS_DIR = Path(__file__).resolve().parent / "story_texts"


def _story_text(story_slug: str, chapter_number: int) -> str:
    path = STORY_TEXTS_DIR / story_slug / f"{chapter_number:02d}.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _chapter(story_slug: str, number: int, title: str, *,
             reactions: tuple = (), mine: str = "") -> Chapter:
    body = _story_text(story_slug, number)
    return Chapter(number, title, len(body), body, reactions=reactions, my_reaction=mine)



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
        # FR-STORY-12 + DEC-32: реакции — на главу, не на произведение целиком.
        # Раскладка подобрана так, чтобы читалась не только высота столбика,
        # но и характер главы: «Алғашқы кездесу» собирает Жүрегім,
        # «Депрессия» — Жыладым, «Жасырын есік» — Таңғалдым. Именно это
        # и есть карта качества, которую автор не получит от одного лайка.
        # Глава 4 — текущая для возвращающегося читателя (mine="jyladym").
        _chapter("dalney-berega", 1, "Жолға шығу",
                 reactions=(("tangaldym", 310), ("shabyt", 240), ("kuldim", 160), ("juregim", 82), ("jyladym", 50))),
        _chapter("dalney-berega", 2, "Тауға көтерілу",
                 reactions=(("shabyt", 300), ("tangaldym", 190), ("kuldim", 120), ("jyladym", 69), ("juregim", 40))),
        _chapter("dalney-berega", 3, "Алғашқы кездесу",
                 reactions=(("juregim", 520), ("tangaldym", 210), ("kuldim", 160), ("shabyt", 84), ("jyladym", 50))),
        _chapter("dalney-berega", 4, "Депрессия", mine="jyladym",
                 reactions=(("jyladym", 420), ("shabyt", 130), ("juregim", 70), ("tangaldym", 47), ("kuldim", 20))),
        _chapter("dalney-berega", 5, "Жаңа карта",
                 reactions=(("tangaldym", 220), ("shabyt", 150), ("kuldim", 90), ("juregim", 32), ("jyladym", 20))),
        _chapter("dalney-berega", 6, "Жаңбыр түн",
                 reactions=(("jyladym", 180), ("juregim", 120), ("tangaldym", 80), ("shabyt", 40), ("kuldim", 18))),
        _chapter("dalney-berega", 7, "Тас үй",
                 reactions=(("tangaldym", 170), ("shabyt", 110), ("jyladym", 60), ("kuldim", 31), ("juregim", 20))),
        _chapter("dalney-berega", 8, "Кездесу",
                 reactions=(("juregim", 140), ("tangaldym", 70), ("jyladym", 40), ("kuldim", 22), ("shabyt", 15))),
        _chapter("dalney-berega", 9, "Жасырын есік",
                 reactions=(("tangaldym", 90), ("shabyt", 40), ("kuldim", 26), ("jyladym", 12), ("juregim", 8))),
        _chapter("dalney-berega", 10, "Қайту",
                 reactions=(("jyladym", 40), ("shabyt", 24), ("juregim", 15), ("tangaldym", 10), ("kuldim", 5))),
        _chapter("dalney-berega", 11, "Соңғы кеш",
                 reactions=(("jyladym", 18), ("juregim", 12), ("shabyt", 7), ("tangaldym", 3), ("kuldim", 2))),
        _chapter("dalney-berega", 12, "Шеп",
                 reactions=(("shabyt", 8), ("jyladym", 5), ("tangaldym", 3), ("juregim", 1), ("kuldim", 1))),
    ],
    "sila-imperii": [
        _chapter("sila-imperii", 1, "Толық мәтін",
                 reactions=(("tangaldym", 100), ("shabyt", 70), ("kuldim", 40), ("juregim", 20), ("jyladym", 15))),
    ],
}


def reactions_of(chapter) -> list:
    """Полный ряд реакций главы в каноническом порядке — включая нулевые.

    Нулевые не выбрасываются намеренно: набор из пяти кнопок должен
    выглядеть одинаково у первой главы и у сотой, иначе читатель каждый
    раз заново ищет нужную.
    """
    counts = chapter.reaction_counts if chapter else {}
    mine = chapter.my_reaction if chapter else ""
    return [
        {"reaction": r, "count": counts.get(r.slug, 0), "mine": r.slug == mine}
        for r in REACTIONS
    ]


def reaction_breakdown(story_slug: str) -> list:
    """Разбивка по главам для авторского кабинета: чем зацепила каждая глава."""
    return [
        {"chapter": c, "top": c.top_reaction, "total": c.likes}
        for c in chapters_of(story_slug)
    ]


# ───────────────────────── Опрос под главой (FR-STORY-13) ─────────────────

@dataclass(frozen=True)
class ChapterPoll:
    """Необязательный вопрос автора под главой.

    Это не квиз: правильного ответа нет и очков не бывает. Смысл в другом —
    у сериальной прозы появляется повод вернуться («кого он выберет?»),
    а у автора — обязательство дописать.

    Опрос закрывается публикацией следующей главы (BR-POLL-05): именно там
    ответ и приходит, сюжетом. Поэтому `closed` вычисляется, а не хранится.
    """
    story_slug: str
    chapter_number: int
    question: str
    options: tuple          # ((slug, text), …) — до 4 (BR-POLL-02)
    votes: tuple = ()       # ((slug, count), …)
    my_vote: str = ""       # что выбрал текущий пользователь

    @property
    def closed(self) -> bool:
        return len(CHAPTERS_BY_STORY.get(self.story_slug, [])) > self.chapter_number

    @property
    def answer_chapter(self) -> int | None:
        """Глава, в которой ответ уже есть — куда вести дочитавшего."""
        return self.chapter_number + 1 if self.closed else None

    @property
    def total_votes(self) -> int:
        return sum(count for _, count in self.votes)

    @property
    def results(self) -> list:
        counts = dict(self.votes)
        total = self.total_votes or 1
        return [
            {
                "slug":    slug,
                "text":    text,
                "count":   counts.get(slug, 0),
                "percent": round(counts.get(slug, 0) * 100 / total),
                "mine":    slug == self.my_vote,
            }
            for slug, text in self.options
        ]


POLLS_BY_CHAPTER: dict = {
    # Открытый опрос: последняя вышедшая глава, ответа ещё нет.
    ("dalney-berega", 12): ChapterPoll(
        story_slug="dalney-berega", chapter_number=12,
        question="Сенше, Дана кімге сенеді?",
        options=(
            ("almas",   "Алмасқа — ол ешқашан өтірік айтпаған"),
            ("qarttyq", "Қартқа — оның сөзінде салмақ бар"),
            ("ozine",   "Тек өзіне"),
        ),
        votes=(("almas", 184), ("qarttyq", 97), ("ozine", 233)),
    ),
    # Закрытый опрос: следующая глава вышла, ответ уже в ней.
    ("dalney-berega", 3): ChapterPoll(
        story_slug="dalney-berega", chapter_number=3,
        question="Үшеуі таңертең не істейді деп ойлайсың?",
        options=(
            ("tauga",  "Тауға көтеріледі"),
            ("qaitad", "Қайтады"),
            ("bolinu", "Бөлініп кетеді"),
        ),
        votes=(("tauga", 612), ("qaitad", 88), ("bolinu", 341)),
        my_vote="bolinu",
    ),
    # Однобөлімное произведение: опрос тоже уместен и остаётся открытым.
    ("tunge-deiin", 1): ChapterPoll(
        story_slug="tunge-deiin", chapter_number=1,
        question="Лифтіде екеудің қайсысы шындықты айтпай тұр?",
        options=(
            ("qyz",  "Қыз"),
            ("jigit", "Жігіт"),
            ("ekeui", "Екеуі де"),
        ),
        votes=(("qyz", 421), ("jigit", 96), ("ekeui", 188)),
    ),
}


def poll_of(story_slug: str, chapter_number: int):
    """Опрос главы или None — опрос необязателен (BR-POLL-01)."""
    return POLLS_BY_CHAPTER.get((story_slug, chapter_number))


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

    @property
    def id(self) -> str:
        """Устойчивый идентификатор комментария.

        Нужен трём вещам сразу: якорю `#comment-<id>` в ссылке на
        комментарий, цели `comment:<id>` для жалобы (BR-33) и цели
        удаления. Пока данных нет в БД, вычисляем из автора и даты —
        после Ф14 здесь будет первичный ключ.
        """
        # crc32, а не hash(): встроенный hash строк рандомизируется от
        # запуска к запуску, и скопированная сегодня ссылка завтра вела бы
        # в пустоту.
        digest = zlib.crc32(self.text.encode("utf-8")) % 10000
        return f"{self.author_username}-{digest:04d}"

    def belongs_to(self, username: str) -> bool:
        """Свой комментарий: меню предлагает «Жою», а не «Шағым» (BR-33)."""
        return bool(username) and self.author_username == username


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
        # 5) Свой комментарий демо-пользователя — на 3-ю главу.
        # Нужен, чтобы ветка «свой» в меню (Жою вместо Шағым, BR-33) вообще
        # была видна: без него дизайн-фаза показывала только чужие.
        StoryComment(
            "aidana", "4 сағат бұрын",
            "Қарттың «жүректерің не дейді?» деген сұрағынан кейін кітапты жауып, біраз ойланып отырдым.",
            likes=6,
            chapter_number=3,
        ),
        # 6) С одним ответом от автора — на 2-ю главу
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


# Порядок значим: первый ключ — дефолт каталога (DEC-36).
CATALOG_SORTS = (
    ("trending",   "Қазір танымал"),
    ("popularity", "Ең көп оқылған"),
    ("recent",     "Жаңалары"),
    ("alphabet",   "Әліпби бойынша"),
)

CATALOG_DEFAULT_SORT = CATALOG_SORTS[0][0]

# Знаки качества платформы (docs/13 §13.7). Ключ — для фильтра, подпись — для
# карточки. Единственная ось, где качество заявлено отдельно от просмотров:
# без неё «Редакция таңдауы» оставался незаметной подписью на карточке, а
# отобрать по нему было нельзя.
STORY_BADGES = (
    ("editorial", "Редакция таңдауы"),
    ("contest",   "Байқауға қатысады"),
)

BADGE_LABELS = dict(STORY_BADGES)

CATALOG_BADGE_FILTERS = (("", "Барлығы"),) + STORY_BADGES

CATALOG_STATUS_FILTERS = (
    ("",           "Барлығы"),
    ("Published",  "Жарияланған"),
    ("Completed",  "Аяқталды"),
    ("OnProcess",  "Жазылып жатыр"),
)

# Возрастные отметки произведения, от младшей к старшей. Порядок значим:
# фильтр сравнивает по индексу, а не по равенству (DEC-38).
AUDIENCE_ORDER = ("10+", "14+")

# Ось «Жасың» — про читателя, а не про произведение. Ключ остаётся отметкой
# произведения (это верхняя граница того, что читателю подходит), подпись —
# возрастная вилка самого читателя. Прежняя подпись «10+ / 14+» повторяла
# ключ и читалась как отметка работы, из-за чего выбор «14+» выглядел как
# «покажи только взрослое» и прятал 15 из 21 доступной работы.
CATALOG_AUDIENCE_FILTERS = (
    ("",    "Барлығы"),
    ("10+", "10-13"),
    ("14+", "14+"),
)

# Границы — в Story.length_bucket, там же и обоснование.
CATALOG_LENGTH_FILTERS = (
    ("",       "Барлығы"),
    ("short",  "10 минутқа дейін"),
    ("medium", "10-30 минут"),
    ("long",   "30 минуттан ұзақ"),
)

# Legacy-ось: в панели её больше нет, но параметр читается — на неё ведут
# старые ссылки. Читательский вопрос закрывает CATALOG_KIND_FILTERS.
CATALOG_FORMAT_FILTERS = (
    ("",       "Барлығы"),
    ("single", "Бір бөлімді"),
    ("serial", "Көп бөлімді"),
)

# «Түрі» (DEC-37) — одна ось вместо «Формат» + «Мәртебесі».
#
# Прежний `status` держал две несовместимые вещи: путь модерации (Жоба →
# Модерацияда → Жарияланды) и завершённость сериала. Первая читателю не нужна
# вовсе — в каталоге всё и так прошло модерацию, «Жарияланған» стоял у 90%
# выдачи и ничего не отбирал. Вторая нужна, но применима только к сериалу:
# у одночастевого произведения текст цел по определению.
#
# Три значения покрывают все осмысленные сочетания и отбрасывают невозможное
# (`single` + «пишется»), отвечая на «что я получу».
CATALOG_KIND_FILTERS = (
    ("",        "Барлығы"),
    ("single",  "Бір бөлімді"),
    ("done",    "Аяқталған сериал"),
    ("ongoing", "Жазылып жатыр"),
)

# kind → предикат. «Любого сериала» среди значений нет намеренно: оба места,
# которые раньше вели на `?format=serial` (ряд главной и пресет), означают
# «продолжается», а не «сериал любой».
KIND_PREDICATES = {
    "single":  lambda s: s.format == "single",
    "done":    lambda s: s.format == "serial" and s.status == "Completed",
    "ongoing": lambda s: s.format == "serial" and s.status == "OnProcess",
}

# Порог «нового имени». Значение стаб-условное: авторов здесь шесть, и любая
# граница между ними произвольна. После Ф14 это должен быть перцентиль по
# подписчикам или возраст аккаунта — не унаследовать это число как правило.
NEW_AUTHOR_FOLLOWERS = 150

# Ось «Автор». Ни одна другая ось не помогает найти того, кого ещё не читают,
# при том что вся культура портала построена вокруг растущего автора
# (docs/13 §13.2), а «новые авторы» стоят отдельным блоком на главной.
CATALOG_AUTHOR_FILTERS = (
    ("",    "Барлығы"),
    ("new", "Жаңа есімдер"),
)


def is_new_author(username: str) -> bool:
    """Автор, которого ещё не читают: подписчиков меньше порога."""
    a = AUTHORS_BY_USERNAME.get(username)
    return bool(a and a.followers < NEW_AUTHOR_FOLLOWERS)

# Статусы, которые вообще показываются публике (BR-10/11, DEC-23).
# «Жоба» и «Модерацияда» — этапы авторского пути, а не публикация: до явного
# решения модератора работа в каталоге не появляется.
PUBLIC_STATUSES = frozenset({"Published", "Completed", "OnProcess"})


def apply_catalog_filters(stories: list, sort: str = CATALOG_DEFAULT_SORT,
                          status: str = "", audience: str = "", length: str = "",
                          format: str = "", badge: str = "",
                          author_tier: str = "", kind: str = "") -> list:
    """Применяет сорт + фильтры к списку Story.

    Sort:
      - trending: по recent_views (desc) — просмотры за 14 дней, дефолт (DEC-36)
      - popularity: по накопленному views (desc)
      - recent: фейково — обратный порядок (нет created_at в stub)
      - alphabet: по title
    Status: пустой → все публичные; иначе точный match Story.status.
    Badge: ключ из STORY_BADGES; пустой → без фильтра.
    Author_tier: 'new' — авторы, которых ещё не читают (see is_new_author).
    """
    out = list(stories)
    if status:
        out = [s for s in out if s.status == status]
    if audience in AUDIENCE_ORDER:
        # Накопительно, а не точным совпадением (DEC-38): читателю четырнадцати
        # лет доступно и то, что помечено 10+. Точное совпадение прятало от него
        # три четверти каталога. Безопасное направление сохраняется — выбравший
        # младшую вилку не видит старших отметок.
        allowed = set(AUDIENCE_ORDER[:AUDIENCE_ORDER.index(audience) + 1])
        out = [s for s in out if s.audience in allowed]
    if length:
        out = [s for s in out if s.length_bucket == length]
    if format:
        out = [s for s in out if s.format == format]
    if kind in KIND_PREDICATES:
        out = [s for s in out if KIND_PREDICATES[kind](s)]
    if badge:
        label = BADGE_LABELS.get(badge)
        out = [s for s in out if label and label in s.badges] if label else []
    if author_tier == "new":
        out = [s for s in out if is_new_author(s.author_username)]

    if sort == "alphabet":
        out.sort(key=lambda s: s.title.lower())
    elif sort == "recent":
        out.reverse()
    elif sort == "popularity":
        out.sort(key=lambda s: s.views, reverse=True)
    else:  # trending (default)
        out.sort(key=lambda s: s.recent_views, reverse=True)
    return out


def filter_catalog(*, query: str = "", genre: str = "", tag: str = "",
                   status: str = "", sort: str = CATALOG_DEFAULT_SORT,
                   audience: str = "", length: str = "",
                   format: str = "", badge: str = "",
                   author_tier: str = "", kind: str = "") -> list:
    """Единый фильтр-пайплайн для унифицированного каталога (DEC-27).

    Применяет все источники AND-комбинацией. Для пустых параметров — no-op.
    Tag учитывает BR-TAG-07 (только accepted-теги показываются в публичной выборке).
    Черновики и работы на модерации не попадают в публичную выборку (DEC-23):
    раньше `aidana-erteg` со статусом «Модерацияда» открыто лежала в каталоге.
    """
    # Стартуем с полного источника (или с search-результата если есть query)
    out = search_stories(query) if query else list(STORIES)
    out = [s for s in out if s.status in PUBLIC_STATUSES]

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
                                 format=format, badge=badge,
                                 author_tier=author_tier, kind=kind)


# Пресеты «Не оқимын?» (docs/13 §13.6). Готовые ответы на вопрос состояния,
# а не набор атрибутов: комбинацию `single + short` §13.11 называет быстрым
# чтением дословно, но в панели она была двумя тапами в разных группах.
CATALOG_PRESETS = (
    {"slug": "bir-otyrysta", "label": "Бір отырыста",
     "filters": {"kind": "single", "length": "short"}},
    {"slug": "jalgasy-bar",  "label": "Жалғасы бар",
     "filters": {"kind": "ongoing"}},
    {"slug": "ayaqtalgan",   "label": "Аяқталған",
     "filters": {"kind": "done"}},
    {"slug": "redaksiya",    "label": "Редакция таңдауы",
     "filters": {"badge": "editorial"}},
    {"slug": "baiqau",       "label": "Байқау жұмыстары",
     "filters": {"badge": "contest"}},
    {"slug": "jana-esimder", "label": "Жаңа есімдер",
     "filters": {"author_tier": "new"}},
)


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
    """Все произведения данного автора (любого статуса), свежие сверху.

    Порядок был порядком объявления в STORIES, то есть случайным для автора:
    единственная опора для вопроса «что я трогал последним» отсутствовала,
    а с ростом числа работ список превращался в стену. Произведения без
    даты правки уходят в конец, сохраняя между собой исходный порядок.
    """
    mine = [s for s in STORIES if s.author_username == username]
    return sorted(
        mine,
        key=lambda s: (s.updated_days_ago is None, s.updated_days_ago or 0),
    )


def public_stories_of(username: str) -> list:
    """Работы автора, которые видит посторонний — свежие сверху.

    `my_stories_of` отдаёт любой статус: это выдача авторского кабинета.
    Публичный профиль был построен на ней же, и на `/u/<username>/` висели
    черновик и работа на модерации — обычными кликабельными карточками
    (нарушение BR-10 и DEC-23). У `aidana` так утекали `aidana-kus`
    (NotPublished) и `aidana-erteg` (OnModeration).

    Публичность берётся из `Story.is_public`, а не из литерала `'Published'`:
    после DEC-37 публичный сериал носит `Completed` или `OnProcess`, и
    сравнение со строкой молча выкинуло бы из профиля все сериалы.
    """
    return [s for s in my_stories_of(username) if s.is_public]


def top_stories_of(username: str, limit: int = 3) -> list:
    """Самые читаемые работы автора — для рейла чужого профиля (FR-PROF-09).

    Сортировка по накопленному `views`, а не по `recent_views`: рейл отвечает
    «с чего начать знакомство с автором», а не «что у него сейчас в моде».
    Ось «Қазір танымал» из DEC-36 живёт в каталоге и на профиле не к месту —
    автор с одной старой сильной работой оказался бы без ответа.

    Не `related_stories`: тот, наоборот, исключает того же автора.
    """
    return sorted(public_stories_of(username), key=lambda s: s.views, reverse=True)[:limit]


def writer_attention(username: str) -> list:
    """Что ждёт автора — короткая строка над списком (FR-WRITE-08).

    Кабинет перечислял имущество, но не отвечал на вопрос, с которым автор
    в него заходит. Все три сигнала уже лежали в данных и просто нигде не
    сходились: статус работы, непрочитанные пікір и начатый черновик,
    у которого нет ни одного бөлім.

    Отдаёт `kind`/`count`/`slug`; тексты и ссылки собирает шаблон — URL-ы
    в слой данных не спускаем. `slug` заполнен только когда элемент один:
    вести «3 шығарма модерацияда» в одну из трёх было бы враньём.
    """
    mine = my_stories_of(username)
    items = []

    def _one(kind, stories):
        if stories:
            items.append({
                "kind":  kind,
                "count": len(stories),
                "slug":  stories[0].slug if len(stories) == 1 else "",
            })

    _one("moderation", [s for s in mine if s.status == "OnModeration"])

    unread_comments = sum(
        1 for n in NOTIFICATIONS_BY_USER.get(username, [])
        if n.kind == "comment" and not n.read
    )
    if unread_comments:
        items.append({"kind": "comments", "count": unread_comments, "slug": ""})

    _one("draft", [s for s in mine
                   if s.status == "NotPublished" and not chapters_of(s.slug)])

    return items


def writer_stats(username: str) -> dict:
    """Агрегированная статистика автора — для правого рейла WRITE."""
    mine = my_stories_of(username)
    # После DEC-37 дописанный сериал носит статус Completed — он тоже
    # опубликован, и по литералу "Published" в счётчик бы не попал.
    # Ключ назывался `drafts`, хотя считал OnProcess и подписан был
    # «Жазылып жатыр»: черновик — это NotPublished, а не пишущийся сериал.
    published = [s for s in mine if s.status in ("Published", "Completed")]
    return {
        "total":      len(mine),
        "published":  len(published),
        "on_moderation": sum(1 for s in mine if s.status == "OnModeration"),
        "ongoing":    sum(1 for s in mine if s.status == "OnProcess"),
        # Черновик считался только в `total`, и разбивка по статусам не
        # сходилась с ним: у `aidana` 2+1+1 против «Барлығы 5». Разбивка,
        # не дающая в сумме целое, — то же враньё, что и хранимый счётчик.
        "draft":      sum(1 for s in mine if s.status == "NotPublished"),
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


# Сокращения месяцев для дат конкурса: «10 қаз — 5 жел».
KK_MONTHS_SHORT = ("қаң", "ақп", "нау", "сәу", "мам", "мау",
                   "шіл", "там", "қыр", "қаз", "қар", "жел")


def kk_date(d: date) -> str:
    """«5 желтоқсан» в короткой форме — «5 жел»."""
    return f"{d.day} {KK_MONTHS_SHORT[d.month - 1]}"


def kk_period(starts: date, ends: date) -> str:
    """Диапазон дат одной строкой; однодневный этап — просто дата."""
    return kk_date(starts) if starts == ends else f"{kk_date(starts)} — {kk_date(ends)}"


def kk_ago(days: int, hours: Optional[int] = None) -> str:
    """«Сколько времени назад» словами — одна формулировка на весь проект.

    Относительное время до этого лежало в данных строкой: у уведомления
    «5 күн бұрын», у заявки «6 ай бұрын». Это то же хранимое производное,
    что `days_left=12` (DEC-45, BR-40a), только заметить его труднее —
    страница выглядит правдоподобно ровно один день. Заявка `aidana` на
    «Жас алдым — 2023» говорила «6 ай бұрын» о конкурсе, закрывшемся в
    декабре 2023-го.

    Часы называются только сегодня: «26 сағат бұрын» человек в уме
    переводит в дни, и «кеше» короче.
    """
    if days <= 0:
        if hours:
            return f"{hours} сағат бұрын"
        return "бүгін"
    if days == 1:
        return "кеше"
    if days < 30:
        return f"{days} күн бұрын"
    if days < 365:
        return f"{days // 30} ай бұрын"
    return f"{days // 365} жыл бұрын"


@dataclass(frozen=True)
class TimelineStage:
    """Этап конкурса. Хранятся даты, состояние выводится.

    Раньше `state` ('done'/'active'/'upcoming') и подпись периода лежали
    в данных руками. Значит, они устаревали молча: у «Алтын қалам — 2024»
    этап «Өтінім қабылдау» стоял `active` в 2026 году, а конкурс носил год
    2024. Хранимое производное уже подводило проект в `Author.works`
    (DEC-40) и подвело здесь — DEC-45.
    """
    label: str
    starts: date
    ends: date

    @property
    def period(self) -> str:
        return kk_period(self.starts, self.ends)

    @property
    def state(self) -> str:
        today = date.today()
        if today > self.ends:
            return "done"
        if today >= self.starts:
            return "active"
        return "upcoming"


@dataclass(frozen=True)
class ContestAward:
    """Номинация конкурса и её награда (DEC-46).

    Набор произвольный: админ заводит столько номинаций, сколько нужно
    этому конкурсу, — «Бас жүлде» и «Оқырман таңдауы» у одного, четыре
    места у другого. Общего реестра номинаций нет и быть не может: он
    и есть то, чем один конкурс отличается от другого.

    `image` — файл эмблемы в MEDIA_ROOT (`awards/<contest>/<award>.png`),
    его загружает админ. Спрайт `components/awards/_sprite.html` тут ни при
    чём: он рукописный, и дописать в него `<symbol>` из админки нельзя.
    Пусто — рендерится типографическая заглушка, как у обложки без файла.

    Раму (медальон, кольцо, тень) рисует платформа, а не картинка. Иначе
    через десять конкурсов ряд наград стал бы коллекцией чужих JPEG.
    """
    slug: str
    title: str
    image: str = ""
    description: str = ""


@dataclass(frozen=True)
class Contest:
    """Конкурс. Заводит админ; всё, что можно вывести, выводится (DEC-45).

    Хранятся три даты — открытие приёма, дедлайн и объявление итогов. Из
    них считаются фаза, отсчёт дней и год; число заявок считается по самим
    заявкам. Прежние поля `status`, `days_left`, `year` и `submissions`
    были хранимыми производными: заведённые руками «87 өтінім» стояли при
    одной реальной заявке, а `days_left=12` протухал назавтра.
    """
    slug: str
    name: str
    subtitle: str                # категория/подзаголовок
    opens_on: date               # приём заявок открывается
    closes_on: date              # дедлайн подачи
    results_on: date             # объявление итогов
    prize_kzt: Optional[int]     # None — конкурс без денежного приза
    cover: str = "img/book1.jpg"
    description: str = ""
    conditions: tuple = ()       # bullet points
    timeline: tuple = ()         # TimelineStage[]
    jury: tuple = ()             # JuryMember[]
    # BR-22: пороги объёма для подачи (знаки)
    min_chars: int = 5_000
    max_chars: int = 15_000
    # Номинации этого конкурса (DEC-46). Показываются ДО итогов — «вот что
    # получит победитель» отвечает на «зачем участвовать» лучше, чем сумма
    # в тенге.
    awards: tuple = ()

    # ── Фаза и сроки ──────────────────────────────────────────────────────
    @property
    def phase(self) -> str:
        """Одна из CONTEST_PHASES. Единственный источник — три даты.

        Четвёртая фаза («қазылар қарауда») появилась потому, что двух
        статусов не хватало: между дедлайном и объявлением итогов конкурс
        либо врал «Белсенді, 0 күн қалды», либо резко становился
        «Аяқталды» без победителей (BR-40).
        """
        today = date.today()
        if today < self.opens_on:
            return "upcoming"
        if today <= self.closes_on:
            return "accepting"
        if today < self.results_on:
            return "judging"
        return "finished"

    @property
    def phase_label(self) -> str:
        return CONTEST_PHASE_LABELS[self.phase]

    @property
    def is_accepting(self) -> bool:
        """Можно ли подавать работу. Именно это, а не «конкурс активен»,
        решает судьбу кнопки «Қатысу»."""
        return self.phase == "accepting"

    @property
    def is_finished(self) -> bool:
        return self.phase == "finished"

    @property
    def days_left(self) -> Optional[int]:
        """Сколько дней до дедлайна. Только пока идёт приём."""
        return (self.closes_on - date.today()).days if self.is_accepting else None

    @property
    def days_until_open(self) -> Optional[int]:
        """Сколько дней до открытия приёма. Только у ещё не начавшегося."""
        if self.phase != "upcoming":
            return None
        return (self.opens_on - date.today()).days

    @property
    def opens_on_label(self) -> str:
        """«9 қыр» — дата открытия приёма для строки в хиро.

        Своё форматирование, а не Django-фильтр `date`: тот берёт названия
        месяцев из локали, а проект казахоязычный при `LANGUAGE_CODE`,
        который за это не отвечает. Та же функция форматирует таймлайн.
        """
        return kk_date(self.opens_on)

    @property
    def closes_on_label(self) -> str:
        return kk_date(self.closes_on)

    @property
    def results_on_label(self) -> str:
        return kk_date(self.results_on)

    @property
    def timing_line(self) -> str:
        """«Что дальше и когда» одной строкой. У завершённого — пусто.

        Живёт здесь, а не в шаблоне, потому что спрашивают об этом из
        трёх разных мест: строка заявки в «Менің өтінімдерім», конкурсное
        уведомление и рейл. Первая версия стояла inline в
        `my_submissions.html`; вторая копия разошлась бы с ней ровно так
        же, как разошлись две рукописные копии правил (см. предыдущий
        коммит ветки).
        """
        if self.phase == "upcoming":
            return f"Қабылдау {self.opens_on_label} басталады"
        if self.phase == "accepting":
            return (f"Қабылдау {self.closes_on_label} жабылады · "
                    f"жеңімпаздар {self.results_on_label} жарияланады")
        if self.phase == "judging":
            return f"Жеңімпаздар {self.results_on_label} жарияланады"
        return ""

    @property
    def year(self) -> int:
        """Год проведения — год объявления итогов.

        Нужен конкурсной биографии автора (FR-PROF-07): «1 жыл бұрын» из
        `Submission.submitted_relative` устаревает каждый день.
        """
        return self.results_on.year

    @property
    def submissions(self) -> int:
        """Число поданных работ — по самим заявкам, а не хранимым числом."""
        return sum(1 for subs in SUBMISSIONS_BY_USER.values()
                   for s in subs if s.contest_slug == self.slug)

    # ── Производное от состава ────────────────────────────────────────────
    @property
    def awards_by_slug(self) -> dict:
        return {a.slug: a for a in self.awards}

    @property
    def grants(self) -> list:
        """Присуждения этого конкурса, в порядке номинаций (DEC-46).

        Победа — акт жюри, а не вычислимая метрика, поэтому присуждение
        хранится. Хранится именно оно, а не список наград у автора:
        колонки `Author.badges` как не было, так и нет (BR-ACH-01).
        """
        order = {a.slug: i for i, a in enumerate(self.awards)}
        mine = [g for g in AWARD_GRANTS if g.contest_slug == self.slug]
        return sorted(mine, key=lambda g: order.get(g.award_slug, len(order)))

    @property
    def winners(self) -> tuple:
        """Слаги произведений-победителей — производное от присуждений.

        Автор выводится через `Story.author_username`: второй литерал
        с именем разошёлся бы с первым ровно так же, как хранимый
        `Author.works` разошёлся с числом произведений.
        """
        seen, out = set(), []
        for g in self.grants:
            if g.story_slug not in seen:
                seen.add(g.story_slug)
                out.append(g.story_slug)
        return tuple(out)

    @property
    def winner_stories(self) -> list:
        """Произведения-победители. Неизвестные слаги молча отбрасываются."""
        return [STORIES_BY_SLUG[s] for s in self.winners if s in STORIES_BY_SLUG]

    @property
    def current_stage(self) -> Optional["TimelineStage"]:
        """Этап, который идёт сейчас, или None.

        Нужен правому рейлу (FR-CONT-09): «что происходит прямо сейчас» —
        единственное, чего нет в хиро.
        """
        return next((t for t in self.timeline if t.state == "active"), None)

    @property
    def next_stage(self) -> Optional["TimelineStage"]:
        """Ближайший ещё не наступивший этап или None."""
        return next((t for t in self.timeline if t.state == "upcoming"), None)


# Фазы конкурса (BR-40, DEC-45). Порядок — хронологический.
CONTEST_PHASES = ("upcoming", "accepting", "judging", "finished")

CONTEST_PHASE_LABELS = {
    "upcoming":  "Жақында",
    "accepting": "Өтінім қабылдау",
    "judging":   "Қазылар қарауда",
    "finished":  "Аяқталды",
}

# Семантика бейджа фазы — та же шкала, что у статусов произведения.
CONTEST_PHASE_BADGE = {
    "upcoming":  "info",
    "accepting": "published",
    "judging":   "attention",
    "finished":  "neutral",
}


# Даты идущих конкурсов заданы относительно сегодняшнего дня. Абсолютные
# литералы в стаб-данных протухают молча: «Алтын қалам — 2024» стоял
# активным в 2026-м с этапом «Өтінім қабылдау» в статусе `active`.
# Завершённый конкурс, наоборот, держит настоящие прошлые даты — он и
# должен оставаться в своём году.
TODAY = date.today()


def _d(days: int) -> date:
    """Дата со сдвигом от сегодня — для конкурсов, которые идут сейчас."""
    return TODAY + timedelta(days=days)


CONTESTS = [
    Contest(
        "bolashak-mektebi", "«Болашақтың мектебі»", "Оқушыларға арналған әдеби байқау",
        opens_on=_d(-30), closes_on=_d(12), results_on=_d(40),
        prize_kzt=500_000,
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
            TimelineStage("Өтінім қабылдау", _d(-30), _d(12)),
            TimelineStage("Қазылар қарауы", _d(13), _d(39)),
            TimelineStage("Жеңімпаздар", _d(40), _d(40)),
        ),
        jury=(
            JuryMember("Алмат Рысқали", "Төраға"),
            JuryMember("Бекжан Тұрсынов",   "Мүше"),
            JuryMember("Дина Айдарбекова",  "Мүше"),
        ),
        awards=(
            ContestAward("bas-zhulde", "Бас жүлде",
                         image="awards/bolashak-mektebi/bas-zhulde.png",
                         description="Қазылар алқасы таңдаған үздік шығарма."),
            ContestAward("ekinshi-oryn", "Екінші орын"),
            ContestAward("ushinshi-oryn", "Үшінші орын"),
            # Эмблемы у этой номинации ещё нет: админ её не загрузил.
            # Так выглядит типографическая заглушка в живом наборе.
            ContestAward("uzdik-debut", "Үздік дебют",
                         description="Платформадағы алғашқы шығармасымен қатысқан авторға."),
        ),
    ),
    # Приём закрыт, победители ещё не названы — фаза `judging`. Ради неё
    # четвёртая фаза и заведена: раньше конкурс в этом промежутке показывал
    # «Белсенді, 0 күн қалды» либо «Аяқталды» без единого победителя.
    # Год ушёл из слага: он теперь выводится из даты итогов, а слаг с
    # зашитым годом у переезжающего конкурса разошёлся бы с ней снова.
    Contest(
        "altyn-qalam", "Алтын қалам", "Жас прозаиктер байқауы",
        opens_on=_d(-70), closes_on=_d(-4), results_on=_d(10),
        prize_kzt=300_000,
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
            TimelineStage("Жарияланды", _d(-70), _d(-70)),
            TimelineStage("Өтінім қабылдау", _d(-69), _d(-4)),
            TimelineStage("Шорт-лист", _d(-3), _d(3)),
            TimelineStage("Финал", _d(10), _d(10)),
        ),
        jury=(
            JuryMember("Айгерім Қасенова", "Төраға"),
            JuryMember("Сайын Нұрбекұлы",  "Мүше"),
        ),
        awards=(
            ContestAward("bas-zhulde", "Бас жүлде",
                         description="Қазылар алқасының бірінші орны."),
            ContestAward("oqyrman-tandauy", "Оқырман таңдауы",
                         description="Оқырман дауысы бойынша үздік шығарма."),
        ),
    ),
    # Приём ещё не открыт. До DEC-45 такого состояния не было вовсе:
    # конкурс появлялся сразу «активным», и анонсировать его заранее было
    # нечем.
    Contest(
        "qys-ertegisi", "«Қыс ертегісі»", "Қысқа әңгіме байқауы",
        opens_on=_d(9), closes_on=_d(45), results_on=_d(70),
        prize_kzt=200_000,
        cover="img/book4.jpg",
        description=(
            "Қысқы демалысқа арналған әңгіме байқауы. Тақырып еркін, "
            "бірақ оқиға қыс мезгілінде өтуі керек."
        ),
        conditions=(
            "Қатысушы жасы — 14-18 жас",
            "Көлемі 5 000-15 000 таңба",
            "Бір автор — бір өтінім (BR-23)",
        ),
        timeline=(
            TimelineStage("Өтінім қабылдау", _d(9), _d(45)),
            TimelineStage("Қазылар қарауы", _d(46), _d(69)),
            TimelineStage("Жеңімпаздар", _d(70), _d(70)),
        ),
        jury=(JuryMember("Айгерім Қасенова", "Төраға"),),
        awards=(
            ContestAward("bas-zhulde", "Бас жүлде"),
            ContestAward("uzdik-qys-angimesi", "Үздік қысқы әңгіме"),
        ),
    ),
    # Настоящие прошлые даты: завершённый конкурс остаётся в своём году,
    # и `year` (2023) сходится с годом в слаге.
    Contest(
        "zhas-aldym-2023", "Жас алдым — 2023", "Республикалық әдеби байқау",
        opens_on=date(2023, 9, 1), closes_on=date(2023, 12, 1),
        results_on=date(2023, 12, 15),
        prize_kzt=None,
        cover="img/book3.jpg",
        description="2023 жылғы байқау аяқталды. Жеңімпаздар: «Күңгірт мырза», «Қуыршақшының ойыны».",
        # Те же две работы, что названы в description. Расхождение между
        # текстом и полем ловит test_stub_data.ContestWinners.
        conditions=(),
        timeline=(
            TimelineStage("Өтінім қабылдау", date(2023, 9, 1), date(2023, 12, 1)),
            TimelineStage("Финал", date(2023, 12, 15), date(2023, 12, 15)),
        ),
        jury=(JuryMember("Алмат Рысқали", "Төраға"),),
        awards=(
            ContestAward("bas-zhulde", "Бас жүлде",
                         image="awards/zhas-aldym-2023/bas-zhulde.png",
                         description="Қазылар алқасы таңдаған үздік шығарма."),
            ContestAward("oqyrman-tandauy", "Оқырман таңдауы",
                         image="awards/zhas-aldym-2023/oqyrman-tandauy.png",
                         description="Оқырман дауысы бойынша үздік шығарма."),
        ),
    ),
]

CONTESTS_BY_SLUG = {c.slug: c for c in CONTESTS}

# Два разных вопроса, и раньше они смешивались в одном слове «активный»:
# «можно ли подать работу» и «конкурс ещё не закрыт». Бейдж работы
# «Байқауға қатысады» держится вторым, кнопка «Қатысу» — первым.
ACCEPTING_CONTESTS = [c for c in CONTESTS if c.is_accepting]

# Порядок в списке — по тому, что читатель может сделать: сначала куда
# можно подать работу прямо сейчас, потом что откроется, потом что уже
# судят. Алфавит и порядок объявления такой вопрос не решают.
_OPEN_ORDER = ("accepting", "upcoming", "judging")
OPEN_CONTESTS = sorted((c for c in CONTESTS if not c.is_finished),
                       key=lambda c: _OPEN_ORDER.index(c.phase))
FINISHED_CONTESTS = [c for c in CONTESTS if c.is_finished]

HERO_CONTEST = ACCEPTING_CONTESTS[0] if ACCEPTING_CONTESTS else None


@dataclass(frozen=True)
class AwardGrant:
    """Присуждение: кому и за что вручена награда конкурса (DEC-46).

    Хранится сам акт, а не список наград у автора. Разница принципиальная:
    «1-орын в Алтын қалам» из данных не вычисляется — это решение жюри, и
    в этом конкурсные награды отличаются от системных знаков (BR-ACH-01).
    Но производной остаётся выдача: ряд наград в профиле — запрос по
    присуждениям, а не колонка `Author.badges`.

    Автор не хранится: он выводится из произведения, как и у победителей.
    """
    contest_slug: str
    award_slug: str
    story_slug: str
    note: str = ""

    @property
    def contest(self):
        return CONTESTS_BY_SLUG.get(self.contest_slug)

    @property
    def award(self) -> Optional[ContestAward]:
        contest = self.contest
        return contest.awards_by_slug.get(self.award_slug) if contest else None

    @property
    def story(self):
        return STORIES_BY_SLUG.get(self.story_slug)

    @property
    def author(self):
        story = self.story
        return story.author if story else None


AWARD_GRANTS = [
    AwardGrant("zhas-aldym-2023", "bas-zhulde", "temniy-lord",
               note="Қазылар алқасының бірауыздан шешімі."),
    AwardGrant("zhas-aldym-2023", "oqyrman-tandauy", "igra-kuklovoda"),
]


# ───────────────────────── CONT — заявки автора ───────────────────────────

@dataclass(frozen=True)
class Submission:
    """Заявка автора. Хранится дата подачи, подпись выводится (BR-41a).

    Прежнее `submitted_relative` было строкой: «6 ай бұрын» стояло у
    заявки на конкурс, закрывшийся в декабре 2023-го, — то есть подача
    приходилась на полгода позже дедлайна. Дата, наоборот, проверяема:
    подача обязана лежать внутри окна приёма своего конкурса.
    """
    contest_slug: str
    story_slug: str
    submitted_on: date         # когда подана; внутри opens_on…closes_on конкурса
    status: str                # 'reviewing' | 'accepted' | 'rejected'
    note: str = ""             # жюри-комментарий (для rejected/accepted)

    @property
    def contest(self):
        return CONTESTS_BY_SLUG.get(self.contest_slug)

    @property
    def story(self):
        return STORIES_BY_SLUG.get(self.story_slug)

    @property
    def submitted_label(self) -> str:
        """«5 күн бұрын» — производное от даты, а не хранимая строка."""
        return kk_ago((date.today() - self.submitted_on).days)


SUBMISSIONS_BY_USER: dict = {
    "aidana": [
        Submission(
            contest_slug="altyn-qalam", story_slug="aidana-tan",
            submitted_on=_d(-5), status="reviewing",
        ),
        Submission(
            contest_slug="zhas-aldym-2023", story_slug="aidana-kysh",
            submitted_on=date(2023, 11, 20), status="rejected",
            # Работа на 2 524 знака при пороге 5 000 — отказ по недобору.
            # Прежняя формулировка говорила «асып кеткен» (превысил) и
            # противоречила собственным данным.
            note="Көлемі шарттан аз — кемінде 5 000 таңба керек.",
        ),
    ],
    # Заявки победителей «Жас алдым — 2023». Без них конкурсная история и
    # знаки «Байқауға қабылданды» / «Байқау жеңімпазы» не на чем показать:
    # заявка была ровно у одного автора, и та не принята.
    "dina_books": [
        Submission(
            contest_slug="bolashak-mektebi", story_slug="igra-kuklovoda",
            submitted_on=_d(-8), status="reviewing",
        ),
        Submission(
            contest_slug="zhas-aldym-2023", story_slug="igra-kuklovoda",
            submitted_on=date(2023, 10, 12), status="accepted",
            note="Қазылар алқасының таңдауы.",
        ),
    ],
    "bekzhan_t": [
        Submission(
            contest_slug="zhas-aldym-2023", story_slug="temniy-lord",
            submitted_on=date(2023, 10, 5), status="accepted",
            note="Қазылар алқасының таңдауы.",
        ),
    ],
}


def submissions_of(username: str) -> list:
    return SUBMISSIONS_BY_USER.get(username, [])


def has_submission(username: str, contest_slug: str) -> bool:
    """BR-23: один автор — одна работа на конкретный конкурс."""
    return any(s.contest_slug == contest_slug for s in submissions_of(username))


# Подписи результата — те же слова, что в «Менің өтінімдерім» (BR-41),
# плюс «Жеңімпаз» для победы: победа выводится из `Contest.winners`,
# отдельного статуса заявки под неё нет.
CONTEST_RESULT_LABELS = {
    "winner":    "Жеңімпаз",
    "accepted":  "Қабылданды",
    "reviewing":  "Қаралуда",
    "rejected":  "Қабылданбады",
}

# Что из результата видит посторонний (BR-74a). Всё остальное публично
# выглядит просто участием.
PUBLIC_CONTEST_RESULTS = ("winner", "accepted")


def contest_history(username: str, *, is_self: bool = False) -> list:
    """Конкурсная биография автора (FR-PROF-07), свежие сверху.

    Правило приватности (BR-74a): публично видно **участие без статуса**.
    Наверх поднимаются только победа и принятие; «қаралуда» и
    «қабылданбады» публично неотличимы друг от друга, и отказ поэтому
    нельзя ни увидеть, ни вычислить сравнением с числом заявок — строк
    столько же, сколько подач.

    Комментарий жюри не покидает личный кабинет никогда: у `aidana` это
    «Көлемі шарттан асып кеткен», и на чужом экране ему делать нечего.

    Публично работа показывается только пока она публична (BR-73): подача
    на конкурс не должна раскрывать снятое с публикации произведение.
    """
    out = []
    for sub in submissions_of(username):
        contest, story = sub.contest, sub.story
        if not contest or not story:
            continue
        # Награды конкретного конкурса (DEC-46). Если работа их взяла,
        # строка называет номинацию — «Бас жүлде» точнее общего
        # «Жеңімпаз», который одинаково звучал у первого места и у приза
        # зрительских симпатий.
        titles = [g.award.title for g in contest.grants
                  if g.story_slug == story.slug and g.award]
        result = "winner" if titles else sub.status
        if not is_self and result not in PUBLIC_CONTEST_RESULTS:
            result = ""
        label = ", ".join(titles) if result == "winner" and titles \
            else CONTEST_RESULT_LABELS.get(result, "")
        out.append({
            "contest":      contest,
            "story":        story if (is_self or story.is_public) else None,
            "year":         contest.year,
            "result":       result,
            "result_label": label,
            "note":         sub.note if is_self else "",
        })
    return sorted(out, key=lambda i: (-i["year"], i["contest"].name))


def spaced_number(value) -> str:
    """Разряды через неразрывный пробел: 500000 -> «500 000».

    Канонический вид числа для автора. Живёт здесь, а не в фильтре
    `balaproza.spaced`, потому что те же числа собираются на стороне
    данных — в подсказках `submission_checklist`. Фильтр вызывает эту
    функцию; двух реализаций одной формы записи в проекте быть не должно.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return value
    return f"{n:,}".replace(",", " ")


def submission_checklist(story: "Story", contest: "Contest") -> list:
    """BR-22: чек-лист соответствия конкретного произведения требованиям конкурса.

    Возвращает список dict'ов: [{key, label, passed, hint}, ...].
    Сейчас «объём» — единственная авто-проверка; остальное — статичные подсказки
    либо требуют декларации автора (AI/возраст/оригинальность).
    """
    # Считаем объём по сумме char_count глав (если есть) или по фикс-аппрокс
    total_chars = sum(c.char_count for c in chapters_of(story.slug)) or 0
    have = spaced_number(total_chars)
    lo, hi = spaced_number(contest.min_chars), spaced_number(contest.max_chars)
    if total_chars < contest.min_chars:
        vol_passed, vol_hint = False, f"Көлемі тым аз — {have} таңба (мин. {lo})"
    elif total_chars > contest.max_chars:
        vol_passed, vol_hint = False, f"Көлемі тым үлкен — {have} таңба (макс. {hi})"
    else:
        vol_passed, vol_hint = True, f"{have} таңба — нормада"

    return [
        # Пороги берутся у конкурса, а не вписаны в подпись: «5 000-15 000»
        # литералом врало бы любому конкурсу с другими границами, а границы
        # у каждого свои — их задаёт админ.
        {"key": "volume",    "label": f"Көлемі ({lo}-{hi} таңба)", "passed": vol_passed,
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


# Почему работу нельзя подать. Пустая строка — можно (BR-24, BR-23a).
INELIGIBLE_REASONS = {
    "too_short": "Көлемі тым аз",
    "too_long":  "Көлемі тым үлкен",
    "busy":      "Бұл шығарма басқа байқауда тұр",
}


def busy_contest_of(username: str, story_slug: str, *, besides: str = "") -> Optional["Contest"]:
    """Незавершённый конкурс, в котором эта работа уже участвует (BR-23a).

    Одна работа не может идти в двух конкурсах одновременно: жюри читают
    параллельно, и одним текстом нельзя выиграть дважды. Завершённый
    конкурс не мешает — работа своё отучаствовала.
    """
    for sub in submissions_of(username):
        if sub.story_slug != story_slug or sub.contest_slug == besides:
            continue
        contest = sub.contest
        if contest and not contest.is_finished:
            return contest
    return None


def eligible_for_contest(username: str, contest_slug: str) -> list:
    """Работы автора как кандидаты на подачу (BR-24, BR-23a).

    В список идут **только публичные** работы: черновик и работа на
    модерации кандидатами не являются вовсе, а показывать их
    заблокированными значит предлагать выбрать то, что нельзя выбрать
    в принципе. Раньше они попадали в выбор, и от подачи черновика
    спасал только нулевой объём — работа на 6 000 знаков со статусом
    `NotPublished` подавалась бы (DEC-23).

    Порог объёма, наоборот, показывается заблокированным с причиной:
    это про эту работу и этот конкурс, и автор может её дописать.

    Возвращает [{story, chars, eligible, reason, hint}, ...] — UI решает рендер.
    """
    contest = CONTESTS_BY_SLUG.get(contest_slug)
    if not contest:
        return []
    result = []
    for s in public_stories_of(username):
        total = sum(c.char_count for c in chapters_of(s.slug))
        busy = busy_contest_of(username, s.slug, besides=contest_slug)
        if total < contest.min_chars:
            reason, hint = "too_short", f"{INELIGIBLE_REASONS['too_short']} — мин. {spaced_number(contest.min_chars)}"
        elif total > contest.max_chars:
            reason, hint = "too_long", f"{INELIGIBLE_REASONS['too_long']} — макс. {spaced_number(contest.max_chars)}"
        elif busy:
            reason, hint = "busy", f"{INELIGIBLE_REASONS['busy']}: «{busy.name}»"
        else:
            reason, hint = "", ""
        result.append({"story": s, "chars": total,
                       "eligible": not reason, "reason": reason, "hint": hint})
    return result


def can_withdraw(username: str, contest_slug: str) -> bool:
    """Можно ли отозвать заявку (BR-23b).

    Пока идёт приём и жюри ещё не вынесло решения. BR-23 разрешает одну
    работу на конкурс — без отзыва это значило, что ошибся работой и всё:
    ни заменить, ни отказаться от участия.
    """
    contest = CONTESTS_BY_SLUG.get(contest_slug)
    if not contest or not contest.is_accepting:
        return False
    return any(s.contest_slug == contest_slug and s.status == "reviewing"
               for s in submissions_of(username))


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


def in_library(username: str, story_slug: str) -> bool:
    """Лежит ли произведение в библиотеке — для кнопки «Сақтау» на STORY."""
    return any(e.story_slug == story_slug for e in library_of(username))


def public_stats(username: str) -> dict:
    """Четыре числа публичного профиля (FR-PROF-01).

    Отдельно от `reader_stats`, потому что зритель разный. `reader_stats`
    считал по `my_stories_of` и по личной библиотеке — то есть чужой профиль
    показывал число работ вместе с черновиками (у `aidana` «5» против «3» в
    карточке автора на странице произведения) и счётчик дочитанных книг из
    приватной библиотеки постороннего человека.

    `works` совпадает с `Author.works` по построению: одно правило
    публичности, посчитанное один раз, — иначе два числа под одним словом
    снова разъедутся.
    """
    pub = public_stories_of(username)
    author = AUTHORS_BY_USERNAME.get(username)
    return {
        # «Шығарма» — работы, видимые читателю
        "works":     len(pub),
        # «Оқылым» — сколько раз прочитали автора (сумма просмотров)
        "reads":     sum(s.views for s in pub),
        # «Ұнату» — лайки на публичных работах
        "likes":     sum(s.likes for s in pub),
        # «Жазылушы» — подписчики автора
        "followers": author.followers if author else 0,
    }


def reader_stats(username: str) -> dict:
    """Сводка для своего профиля: то же самое плюс приватное.

    Числа, которые видит посторонний, берутся из `public_stats` — свой
    профиль не должен показывать владельцу другую арифметику, чем читателю.
    Сверх них: `works_total` (с черновиками — владелец их видит) и
    `finished` (сколько дочитал; только своё).
    """
    stats = dict(public_stats(username))
    lib = library_of(username)
    stats.update({
        # Все свои работы, включая черновики и модерацию
        "works_total": len(my_stories_of(username)),
        # Сколько дочитал — записи библиотеки с kind='done'. Приватно.
        "finished":    sum(1 for e in lib if e.kind == "done"),
    })
    return stats


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


# ───────────────────────── PROF — достижения автора ───────────────────────
#
# Знаки автора (FR-PROF-06). Все семь **выводятся из данных**, ни один не
# хранится: `Author.works` уже был хранимым литералом и врал у всех шести
# авторов сразу в шести местах рендера. Достижений семь, и разъезжаться они
# начали бы в семь раз быстрее.
#
# Рейтинга — числа, по которому авторов можно выстроить в ряд, — здесь нет и
# не будет (DEC-41, docs/13 §13.10). Знак говорит «ты сделал», рейтинг —
# «ты хуже вон того»; аудитории 14-18 второе не нужно.

# Ступени прочтений. Считаются **накопительно по всем публичным работам**:
# это знак автора, а у произведения свои бейджи уже есть (STORY_BADGES).
READ_TIERS = (
    (1_000,   "Мың оқылым"),
    (10_000,  "Он мың оқылым"),
    (50_000,  "Елу мың оқылым"),
    (100_000, "Жүз мың оқылым"),
)


def reads_total(username: str) -> int:
    """Сколько раз прочитали автора — по публичным работам (BR-73)."""
    return sum(s.views for s in public_stories_of(username))


def tier_for(total: int) -> Optional[tuple]:
    """Высшая ступень, взятая при таком числе прочтений, или None.

    Отдельно от `read_tier`, чтобы границы (999/1 000/9 999/10 000)
    проверялись напрямую, а не через подгонку фикстур.
    """
    taken = [t for t in READ_TIERS if total >= t[0]]
    return taken[-1] if taken else None


def next_tier_for(total: int) -> Optional[tuple]:
    """Следующая невзятая ступень или None, если взяты все."""
    ahead = [t for t in READ_TIERS if total < t[0]]
    return ahead[0] if ahead else None


def read_tier(username: str) -> Optional[tuple]:
    """Высшая взятая ступень автора.

    В публичный ряд идёт только она. «Мың» + «Он мың» + «Елу мың» рядом —
    три пилюли, говорящие одно и то же; пройденные ступени видно в своей
    статистике (FR-PROF-08).
    """
    return tier_for(reads_total(username))


def next_read_tier(username: str) -> Optional[tuple]:
    """Следующая ступень — для своей статистики, не для публичного ряда."""
    return next_tier_for(reads_total(username))


def winning_stories_of(username: str) -> list:
    """Работы автора, отмеченные наградой конкурса (DEC-46)."""
    seen, out = set(), []
    for grant in AWARD_GRANTS:
        story = grant.story
        if story and story.author_username == username and story.slug not in seen:
            seen.add(story.slug)
            out.append(story)
    return out


def contest_awards_of(username: str) -> list:
    """Награды конкурсов, полученные автором (DEC-46), свежие сверху.

    Второй класс знаков рядом с системными `AWARDS`. Разница — в источнике
    факта: системный знак вычисляется из данных, конкурсная награда
    присуждается жюри и потому хранится присуждением. Ряд в профиле
    по-прежнему собирается запросом, а не полем автора (BR-ACH-01).

    Работа называется только пока она публична (BR-73): снятая с
    публикации не должна проступать через награду. Сама награда при этом
    остаётся — она принадлежит автору, а не видимости текста.
    """
    out = []
    for grant in AWARD_GRANTS:
        story, award, contest = grant.story, grant.award, grant.contest
        if not (story and award and contest) or story.author_username != username:
            continue
        out.append({
            "key":     f"{contest.slug}:{award.slug}",
            "title":   award.title,
            "image":   award.image,
            "contest": contest,
            "story":   story if story.is_public else None,
            "year":    contest.year,
            "note":    grant.note,
        })
    return sorted(out, key=lambda i: (-i["year"], i["contest"].name, i["title"]))


# Слаг иллюстрации и металл ступени для каждой награды (DEC-43).
# Металл — не украшение, а сигнал ценности: бронза — первые шаги, серебро —
# середина пути, золото — редкое. Он заменил прежнюю подсветку `kind`,
# потому что читается без легенды и не требует подписи рядом.
AWARD_TIERS = ("bronze", "silver", "gold")

# Ступени оқылым: слаг иллюстрации + металл. Один рисунок-стела, у которого
# меняются число на табличке и металл, — как «5 ЛЕТ» у аналогов. Четыре
# отдельные картинки рисовать незачем.
READ_TIER_ART = {
    1_000:   ("reads-1k",   "bronze"),
    10_000:  ("reads-10k",  "silver"),
    50_000:  ("reads-50k",  "silver"),
    100_000: ("reads-100k", "gold"),
}


@dataclass(frozen=True)
class Award:
    """Одна награда: чем она выглядит, за что даётся и как проверяется.

    Условие лежит рядом с наградой, а не в отдельном списке «как получить»:
    иначе получилось бы два места, описывающих одно правило, и однажды они
    разошлись бы — как расходились две копии вкладки «Туралы».
    """
    key: str
    label: str
    art: str        # слаг иллюстрации в components/awards/_sprite.html
    tier: str       # металл ступени, см. AWARD_TIERS
    hint: str       # что нужно сделать — для своей статистики (FR-PROF-08)
    earned: Callable  # username -> bool

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label,
                "art": self.art, "tier": self.tier}


# Порядок стабильный — от первого шага к редкому (BR-ACH-02). Ступени
# оқылым сюда не входят: у них четыре варианта и динамическая подпись,
# они живут в READ_TIERS / READ_TIER_ART и добавляются отдельно.
AWARDS = (
    Award("first_publication", "Алғашқы жарияланым", "first-publication", "bronze",
          "Бірінші шығармаңды жарияла",
          lambda u: any(s.is_public for s in my_stories_of(u))),
    Award("contest_participant", "Байқауға қатысты", "contest-participant", "bronze",
          "Кез келген байқауға өтінім жібер",
          lambda u: bool(submissions_of(u))),
    # Дописанный сериал — самая ценная награда набора: дописать начатое
    # подростку тяжелее всего, и это ровно то поведение, которое платформе
    # нужно поощрять. Одиночный рассказ сюда не считается — он «дописан»
    # в момент публикации (BR-10a, BR-ACH-04).
    Award("finished_serial", "Сериалды аяқтады", "finished-serial", "silver",
          "Көп бөлімді шығармаңды аяқта",
          lambda u: any(s.status == "Completed" and not s.is_single
                        for s in my_stories_of(u))),
    Award("contest_accepted", "Байқауға қабылданды", "contest-accepted", "silver",
          "Өтінімің қазылар алқасынан өтсін",
          lambda u: any(s.status == "accepted" for s in submissions_of(u))),
    # Системного «Байқау жеңімпазы» здесь больше нет — DEC-46. Один общий
    # знак на все конкурсы всех лет вытесняется наградой конкретного
    # конкурса: она называет номинацию, год и работу, а общий — только
    # факт. Держать оба значило бы дважды сказать одно и то же, причём
    # менее точным способом.
    Award("editorial_choice", BADGE_LABELS["editorial"], "editorial-choice", "gold",
          "Редакция шығармаңды таңдасын",
          lambda u: any(BADGE_LABELS["editorial"] in s.badges
                        for s in public_stories_of(u))),
)


def achievements_of(username: str) -> list:
    """Полученные награды автора — публичный ряд (FR-PROF-06).

    Отдаёт `key` / `label` / `art` / `tier`; рендерит `components/award.html`.
    Ссылок здесь нет: URL-ы в слой данных не спускаем — как в каталоге
    (`_catalog_href`) и в полосе внимания кабинета (`_attention_links`).

    `art` — слаг иллюстрации в `components/awards/_sprite.html`, `tier` —
    металл постамента. Прежние `icon` / `kind` описывали пилюлю с
    монохромной иконкой; награда — предметная иллюстрация, и ступень
    ценности несёт металл, а не цвет фона (DEC-43, BR-ACH-02).

    В ряд идёт только **высшая** взятая ступень оқылым: «Мың» и «Он мың»
    рядом говорят одно и то же. Пройденные видно в своей статистике.
    """
    if username not in AUTHORS_BY_USERNAME:
        return []

    out = [a.as_dict() for a in AWARDS if a.earned(username)]

    tier = read_tier(username)
    if tier:
        art, metal = READ_TIER_ART[tier[0]]
        out.append({"key": "reads", "label": tier[1], "art": art, "tier": metal})

    return out


def award_catalog(username: str) -> list:
    """Все награды с отметкой «взята» — для своей статистики (FR-PROF-08).

    Тот же реестр `AWARDS`, что и у публичного ряда: список «что можно
    получить» не может разойтись со списком «что получено», потому что это
    один список.
    """
    return [{**a.as_dict(), "hint": a.hint,
             "earned": bool(a.earned(username)),
             # Готовый флаг «обесцветить»: `{% include %}` не умеет `not`,
             # а обход через `earned|yesno:",True"` читается как ребус.
             "dim": not a.earned(username)}
            for a in AWARDS]


def read_ladder(username: str) -> list:
    """Ступени оқылым с отметкой пройденного и указанием следующей.

    Публичный ряд показывает одну ступень; здесь видно весь путь — это и
    есть ответ на «что дальше», ради которого своя статистика заводилась.
    """
    total = reads_total(username)
    ahead = next_tier_for(total)
    return [
        {
            "threshold": threshold,
            "label":     label,
            "art":       READ_TIER_ART[threshold][0],
            "tier":      READ_TIER_ART[threshold][1],
            "earned":    total >= threshold,
            "dim":       total < threshold,
            "is_next":   bool(ahead and ahead[0] == threshold),
            "left":      max(0, threshold - total),
        }
        for threshold, label in READ_TIERS
    ]


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
    """Событие в ленте автора. Хранится «когда», выводится «как давно».

    Два правила, которых у уведомления не было (BR-70a, BR-72a):

    **Время не хранится строкой.** Было `when="5 күн бұрын"` и
    `bucket="past_week"` — оба поля устаревали на следующий день, ровно
    как `days_left` до DEC-45. Теперь хранится `days_ago`, а подпись и
    группа выводятся из него.

    **Уведомление ведёт к своему предмету.** Конкурсное событие знало о
    конкурсе только по имени внутри `text` и потому не вело никуда:
    прочитав «шорт-лист басталды», автор шёл искать конкурс через меню.
    Имя предмета берётся у самого предмета — второй литерал разошёлся бы
    с первым, как разошёлся хранимый `Author.works` (DEC-40).
    """
    kind: str               # см. NOTIF_KINDS
    days_ago: int = 0       # сколько дней назад; 0 — сегодня
    hours_ago: Optional[int] = None   # уточнение для сегодняшних событий
    actor_username: str = ""    # кто инициатор (для comment/like/follower); '' если системное
    story_slug: str = ""        # к чему относится (comment/like/new_chapter/moderation)
    contest_slug: str = ""      # к какому конкурсу относится (kind='contest')
    text: str = ""              # только событие: имя предмета приходит из объекта
    read: bool = False          # прочитано ли

    @property
    def actor(self):
        return AUTHORS_BY_USERNAME.get(self.actor_username) if self.actor_username else None

    @property
    def story(self):
        return STORIES_BY_SLUG.get(self.story_slug) if self.story_slug else None

    @property
    def contest(self):
        return CONTESTS_BY_SLUG.get(self.contest_slug) if self.contest_slug else None

    @property
    def when(self) -> str:
        return kk_ago(self.days_ago, self.hours_ago)

    @property
    def bucket(self) -> str:
        """Группа FR-NOTIF-01 или '' — если событие старше недели.

        Групп ровно три, и четвёртой («раньше») в требовании нет. Значит,
        неделя и есть глубина ленты; событие старше в неё не попадает —
        см. `notifications_for_user`.
        """
        if self.days_ago <= 0:
            return "today"
        if self.days_ago == 1:
            return "yesterday"
        return "past_week" if self.days_ago <= 7 else ""


NOTIFICATIONS_BY_USER: dict = {
    "aidana": [
        # ── Бүгін ──
        Notification(
            kind="comment", hours_ago=2,
            actor_username="aygerim_k", story_slug="aidana-tan",
            text="Соңғы бөлім жанға тиді. Сегізіншіде Айданың Таразға қайтуы — нағыз қазақша драма!",
        ),
        Notification(
            kind="like", hours_ago=4,
            actor_username="bekzhan_t", story_slug="aidana-tan",
        ),
        Notification(
            kind="moderation", hours_ago=9,
            story_slug="aidana-erteg",
            # Название работы в тексте не повторяется: его несёт ссылка на
            # саму работу. Раньше строка начиналась с «Ертегі ертеректегі»,
            # и переименование произведения оставило бы уведомление
            # говорить о старом имени.
            # «Модерация: … модерациядан өтуде» повторяло корень дважды:
            # тип события уже назван подписью и иконкой, тексту остаётся срок.
            text="1-2 күн қажет.",
        ),
        # Срок, а не тишина: приём в «Болашақтың мектебі» ещё идёт, и это
        # то единственное уведомление, по которому автор может что-то
        # сделать прямо сейчас. Сколько именно осталось, знает конкурс —
        # в тексте этого числа нет (BR-40a).
        Notification(
            kind="contest", hours_ago=6,
            contest_slug="bolashak-mektebi",
            # Про дедлайн говорит строка срока под текстом; здесь — то,
            # что автор может сделать. «Жабылады» в обеих строках подряд
            # было одним фактом, сказанным дважды.
            text="өтінім беруге әлі үлгересің.",
        ),
        # ── Кеше ──
        Notification(
            kind="follower", days_ago=1,
            actor_username="dina_books", read=True,
        ),
        Notification(
            kind="new_chapter", days_ago=1,
            actor_username="rudazov", story_slug="arhimag",
            text="жаңа бөлім қосылды.",
            read=True,
        ),
        # ── Өткен аптада ──
        Notification(
            kind="like", days_ago=3,
            actor_username="sayyn", story_slug="aidana-kysh", read=True,
        ),
        # У aidana в этом конкурсе лежит заявка, и уведомление обязано
        # вести к нему: дата объявления итогов — первый вопрос после
        # закрытия приёма, и она приходит из `Contest.timing_line`.
        Notification(
            kind="contest", days_ago=4,
            contest_slug="altyn-qalam",
            text="өтінім қабылдау жабылды, жұмыстар қазылар алқасында.",
            read=True,
        ),
        Notification(
            kind="comment", days_ago=6,
            actor_username="rudazov", story_slug="aidana-tan",
            text="Жас автордың тілі жаңа да жанды. Әрі қарай жалғастыр.",
            read=True,
        ),
    ],
}


def notifications_for_user(username: str) -> dict:
    """Уведомления, сгруппированные по бакетам времени (FR-NOTIF-01).

    Возвращает {'today': [...], 'yesterday': [...], 'past_week': [...]}.

    Групп три, и старше недели событие не показывается: `Notification.bucket`
    отдаёт у такого пустую строку, и в выдачу оно не попадает. Глубина ленты
    объявлена самим требованием — четвёртой группы «раньше» в нём нет.

    Внутри группы — свежие сверху. Порядок объявления в данных таким не
    является: сегодняшние события шли «2 сағат · 4 сағат · 9 сағат ·
    6 сағат», и лента читалась как перемешанная.
    """
    items = NOTIFICATIONS_BY_USER.get(username, [])
    grouped = {b: [] for b in NOTIF_BUCKETS}
    for n in items:
        if n.bucket in grouped:
            grouped[n.bucket].append(n)
    for bucket in grouped.values():
        bucket.sort(key=lambda n: (n.days_ago, n.hours_ago or 0))
    return grouped


def unread_count_for_user(username: str) -> int:
    """Сколько непрочитанных уведомлений у пользователя (для бейджа в шапке).

    Считается то же, что показывается: событие старше недели в ленту не
    попадает (BR-70a), и учитывать его в бейдже значит послать автора
    искать уведомление, которого на странице нет.
    """
    return sum(1 for n in NOTIFICATIONS_BY_USER.get(username, [])
               if not n.read and n.bucket)


# ───────────────────────── Глобальные «цифры платформы» ────────────────────

PLATFORM_STATS = {
    "stories":  12_384,
    "authors":   4_821,
    "contests":      3,
}

