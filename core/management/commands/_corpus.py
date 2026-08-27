"""Демо-корпус: содержимое портала, которым он показывает себя.

Это **данные, а не контракт**. Раньше здесь же лежал стаб `core/stub_data.py`,
и страницы читали его напрямую — вместе с записями он держал девяносто
хелперов и полсотни вычисляемых свойств, то есть вторую реализацию портала
рядом с настоящей. Чтение переехало на модели (Ф14), и от файла остались
ровно литералы: кто написал, что написал, кто это прочитал.

Читать отсюда имеет право **только `seed_demo`** — команда, которая
раскладывает корпус по таблицам. Приложение отвечает из базы; модуль лежит
рядом с командой, а не в `core/`, чтобы это было видно по пути. Держит
`core/tests/test_data_facade.py`.

Правил здесь нет — ни одной строки из `core.domain`: корпус не знает ни
осей каталога, ни ступеней наград, ни того, как называется статус. Он знает
только то, что нельзя вывести, — сами тексты и числа.

Времена заданы **относительно сегодня** (`_d(±N)`, дни назад): фаза конкурса
выводится из дат (DEC-45), и абсолютные литералы протухают молча — через
месяц идущий конкурс оказался бы завершённым, а тесты падали бы по
календарю. Завершённый конкурс, наоборот, держит настоящие прошлые даты.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

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

# ───────────────────────── Пользователи / Авторы ─────────────────────────

@dataclass(frozen=True)
class Author:
    username: str   # без @
    name: str       # реальное имя для кабинета/модерации/конкурсов
    pen_name: str   # публичное авторское имя / псевдоним
    bio: str
    # Год прихода на платформу — «2024 жылдан бері» в шапке профиля.
    # Единственный факт профиля, который нельзя вывести из данных: следов
    # регистрации в стабе нет. Год, а не полная дата: подростку важно «давно
    # или недавно», а не день; точная дата — лишние персональные данные.
    joined_year: int



AUTHORS = [
    Author("rudazov",   "Алмат Рысқали",     "Rudazov",       "Фэнтези, шытырман",       2023),
    Author("aygerim_k", "Айгерім Қасенова",  "aiqalam",       "Жас прозаик · Алматы",     2024),
    Author("bekzhan_t", "Бекжан Тұрсынов",   "BekTor",        "Қалалық әңгімелер",        2024),
    Author("dina_books","Дина Айдарбекова",  "dina.books",    "Балалар әдебиеті",         2023),
    Author("sayyn",     "Сайын Нұрбекұлы",   "sayyn",         "Фантастика, шытырман",      2025),
    # Демо-пользователь, под которым логинимся через фейк-сессию (см. core.views.login_view).
    Author("aidana",    "Айдана Серікқызы",  "aidana",        "Жас прозаик · Тараз",       2025),
]

# ───────────────────────── Произведения ─────────────────────────

@dataclass(frozen=True)
class Story:
    slug: str
    title: str
    author_username: str
    cover: str       # путь относительно static/
    genres: tuple    # (primary_slug, secondary_slug or None)
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
    # Возрастная отметка работы (BR-10b). Пустая строка — «автор ещё не
    # выбрал», и это отдельное состояние, а не синоним «10+». Дефолт «10+»
    # проставлял отметку молча за автора: чеклист кабинета рисовал за неё
    # зелёную галку, хотя автор её не ставил, а каталожная ось «Жасың»
    # (DEC-38) раскладывала работу по чужому решению. На детской платформе
    # это самое дорогое поле карточки — оно выбирается, а не достаётся.
    # Работа выходит из черновика только с заполненной отметкой.
    audience: str = ""
    # Знак редакции — акт человека, поэтому лежит здесь. Второго знака
    # («Байқауға қатысады») в корпусе нет: он выводится из заявки на
    # незавершённый конкурс, и записанный рядом с нею он с нею же и
    # расходился — знак стоял у одной работы, а заявок было две.
    is_editorial_pick: bool = False
    format: str = "serial"  # single | serial
    # Сколько дней назад автор трогал работу в последний раз. None — не задано:
    # в кабинете показывается только своё, и заполнены только те произведения,
    # которые там бывают. В Ф14 это `updated_at` с auto_now, а не число дней —
    # хранить дельту нельзя, она устаревает каждые сутки. Ось «что я трогал
    # последним» держится на этом поле: до него порядок списка был порядком
    # объявления в STORIES.
    updated_days_ago: int | None = None
















STORIES = [
    Story("dalney-berega",  "Алыс жағалауларда",     "sayyn",      "ipad_19b0bc4bcd9c1a1dc4c3cc12cf20dce5.webp", ("fantastika",  None),          12482, 5230, 312, status="Completed", recent_views=2980, annotation="Үш дос жоғалған жолды іздеп шығады. Таудағы сапар оларды өз қорқынышымен, достықпен және белгісіз ауылдың құпиясымен беттестіреді.", tags=("arman", "sayahat", "jasospirim"), audience="10+", is_editorial_pick=True),
    Story("temniy-lord",    "Күңгірт мырза",         "bekzhan_t",  "ipad_42f033cf1b9a2bcad744d05b9d429609.webp", ("fantezi",     "horror"),        8920, 2440, 156, status="OnProcess", recent_views=1810, annotation="Қараңғы патшалыққа түскен жас кейіпкер биліктің бағасын түсіне бастайды. Сиқыр, қорқыныш және таңдау туралы фэнтези.", tags=("mistika", "arman", "basqa-alem"), audience="14+"),
    Story("igra-kuklovoda", "Қуыршақшының ойыны",    "dina_books", "ipad_499539963221e0fe36b0888bf8601067.webp", ("triller",     "drama"),        18102, 6230, 421, status="OnProcess", recent_views=4120, annotation="Мектептегі тыныш күндер бір жұмбақ ойыннан кейін өзгереді. Әр белгі жаңа күдікке апарады, ал шындық жақын жерде жасырынып тұр.", tags=("mistika", "jasospirim", "detektiv-jas"), audience="14+"),
    Story("kronchessii",    "Тас уәделер",           "rudazov",    "ipad_5916b4e19c616e74d008125ba9a1be8e.webp", ("shyttyrman",  "fantezi"),      32540, 11200, 890, status="Completed", recent_views=890, annotation="Ескі қала қабырғаларындағы тасқа қашалған уәделер оянады. Кейіпкерлер өткеннің шартын бұзбай, болашақты сақтауға тырысады.", tags=("sayahat", "arman", "syikyr-akademiya"), audience="10+"),
    Story("arhimag",        "Сиқыршы: бөтен әлемдер","rudazov",    "ipad_940e074d12d6c3657199601ca568f1b3.jpg",  ("fantezi",     "shyttyrman"),   12482, 4821, 312, status="OnProcess", recent_views=740, annotation="Жас сиқыршы бөтен әлемдердің есігін ашқанда, әр әлем өз ережесін ұсынады. Үйге қайту үшін ол күштен бұрын жауапкершілікті үйренеді.", tags=("syikyr-akademiya", "arman", "dostyk", "jasospirim", "mektep"), audience="10+"),
    Story("sila-imperii",   "Империя құдіреті",      "aygerim_k",  "ipad_992f1631a421d74ed5e1aa72717df374.webp", ("tarih",       "drama"),        14200, 3890, 245, status="Published", recent_views=610, annotation="Көне империяның шетінде өскен жас батыр тарихтың үлкен толқынына түседі. Бұл шығарма билік, адалдық және ел алдындағы таңдау туралы.", tags=("arman", "jasospirim"), audience="10+", format="single"),

    # ─ Витринный слой: заполняет ряды главной и покрывает пустые жанры ─
    # Без него «Қысқа оқылатын әңгімелер» рендерился одной карточкой, а половина
    # жанровых чипов вела в пустое состояние — раскладку было не на чем смотреть.
    # cover="" оставлен намеренно у части историй: проверяем типографическую
    # плашку cover_placeholder наравне с фото-обложками.
    Story(
        slug="kunnin-songy-sagaty", title="Күннің соңғы сағаты", author_username="sayyn",
        cover="ipad_f8f1ea3b7e8133f930825b2da92a135e.webp", genres=("fantastika", None),
        views=6410, likes=980, comments=64,
        status="Published", format="single",
        recent_views=2210, annotation="Күн батпай тұрып бір нәрсені үлгеру керек. Он жеті жасар бала уақыттың қалай тоқтайтынын біледі.",
        tags=("arman", "jasospirim"), audience="10+",
    ),
    Story(
        slug="mektep-koridory", title="Мектеп дәлізіндегі хат", author_username="aygerim_k",
        cover="", genres=("romantika", "drama"),
        views=9240, likes=2110, comments=188,
        status="Published", format="single", secondary_genre="drama",
        recent_views=3450, annotation="Партаның астынан табылған хат кімге жазылғаны белгісіз. Бірақ оны оқыған қыз енді бұрынғыдай жүре алмайды.",
        tags=("mektep", "gashyqtyq", "jasospirim"), audience="10+",
    ),
    Story(
        slug="atam-aityp-berdi", title="Атам айтып берген ертегі", author_username="dina_books",
        cover="", genres=("erteg", None),
        views=3120, likes=540, comments=41,
        status="Published", format="single",
        recent_views=1620, annotation="Ауылдағы жаз, кешкі шай және атаның бір ертегісі. Ол ертегіде жоғалған қой да, жоғалған бала да бар.",
        tags=("dostyk", "mektep"), audience="10+",
    ),
    Story(
        slug="konshi-bala", title="Көрші бала", author_username="bekzhan_t",
        cover="", genres=("komediya", None),
        views=7830, likes=1420, comments=133,
        status="Published", format="single",
        recent_views=980, annotation="Көршінің баласы күнде бір нәрсе бүлдіреді. Бүгін ол менің велосипедімді ұрлады — бірақ себебі күлкілі.",
        tags=("dostyk", "mektep", "jasospirim"), audience="10+",
    ),
    Story(
        slug="tunge-deiin", title="Түнге дейін үш сағат", author_username="bekzhan_t",
        cover="ipad_fe6ce3337de7c1c1bf18ef8bb0f3f9a3.webp", genres=("triller", None),
        views=11470, likes=2890, comments=241,
        status="Published", format="single",
        recent_views=1150, annotation="Лифт екі қабат арасында тоқтады. Ішінде екеу, ал біреуі шындықты айтпай тұр.",
        tags=("mistika", "detektiv-jas"), audience="14+",
    ),
    Story(
        slug="almaty-ayazy", title="Алматы аязы", author_username="aygerim_k",
        cover="", genres=("drama", None),
        views=4980, likes=760, comments=58,
        status="Published", format="single",
        recent_views=2740, annotation="Қаңтардағы қала, жылымаған автобус және әкесімен алғаш рет ашық сөйлескен күн.",
        tags=("jasospirim", "arman"), audience="14+",
    ),
    Story(
        slug="balkonnan-korinetin", title="Балконнан көрінетін әлем", author_username="dina_books",
        cover="", genres=("balalar", None),
        views=2640, likes=430, comments=27,
        status="Published", format="single",
        recent_views=1490, annotation="Тоғызыншы қабаттан бүкіл ауланы көруге болады. Ал кейде — өзіңді де.",
        tags=("dostyk", "arman"), audience="10+",
    ),
    Story(
        slug="korkynyshty-koilek", title="Қорқынышты көйлек", author_username="bekzhan_t",
        cover="", genres=("horror", None),
        views=8150, likes=1630, comments=204,
        status="Published", format="single",
        recent_views=620, annotation="Ескі шкафтан табылған көйлекті киген адам түнде өз атын ұмытады.",
        tags=("mistika",), audience="14+",
    ),
    Story(
        slug="zhuldyz-kartasy", title="Жұлдыз картасы", author_username="rudazov",
        cover="", genres=("fantastika", "shyttyrman"),
        views=15320, likes=3940, comments=387,
        status="Completed", secondary_genre="shyttyrman",
        recent_views=1240, annotation="Ғарыш кемесінің картасында болмауға тиіс бір нүкте бар. Экипаж соған қарай бет алады.",
        tags=("aua-ralighi", "sayahat", "arman"), audience="10+",
        is_editorial_pick=True,
    ),
    Story(
        slug="kokjal-anyzy", title="Көкжал аңызы", author_username="dina_books",
        cover="", genres=("tarih", "erteg"),
        views=6720, likes=1180, comments=94,
        status="Completed", secondary_genre="erteg",
        recent_views=430, annotation="Далада бір қасқыр туралы аңыз жүреді. Оны естіген әр ұрпақ басқаша айтады.",
        tags=("sayahat", "dostyk"), audience="10+",
    ),
    Story(
        slug="keiipkerge-hat", title="Кейіпкерге жазылған хат", author_username="aygerim_k",
        cover="", genres=("fanfik", "romantika"),
        views=10940, likes=3210, comments=452,
        status="OnProcess", secondary_genre="romantika",
        recent_views=3120, annotation="Сүйікті кітабының кейіпкеріне хат жазған қыз кенет жауап алады.",
        tags=("gashyqtyq", "syikyr-akademiya", "jasospirim"), audience="14+",
    ),
    Story(
        slug="arqadagy-jaz", title="Арқадағы жаз", author_username="sayyn",
        cover="", genres=("balalar", "drama"),
        views=3890, likes=610, comments=45,
        status="OnProcess", secondary_genre="drama",
        recent_views=260, annotation="Жазғы каникул, ескі велосипед және ауылдағы жеті апта. Әр бөлім — бір апта.",
        tags=("dostyk", "sayahat", "mektep"), audience="10+",
    ),

    # ─ Произведения демо-пользователя «Айдана» (для WRITE-страниц) ─
    Story(
        slug="aidana-tan",    title="Таң алдында",            author_username="aidana",
        cover="ipad_c9217632f98051fd88ca5763f218a9e3.webp", genres=("drama", None),
        views=1042, likes=87, comments=12,
        status="OnProcess", recent_views=310, annotation="Жас қыздың Алматыдан Таразға қайту туралы әңгімесі. Сегіз бөлімде, әр бөлім — жаңа қала.",
        tags=("sayahat", "jasospirim", "arman", "experimental"), audience="14+",
        updated_days_ago=2,
    ),
    Story(
        slug="aidana-koshe",  title="Көше әндері",            author_username="aidana",
        cover="ipad_e655bb59097d8f25698466168d385969.webp", genres=("drama", "komediya"),
        views=203, likes=18, comments=4,
        status="Published", recent_views=203, annotation="Қаладағы бес адамның бір күні. Әрқайсысының өз әні.",
        secondary_genre="komediya",
        tags=("aua-ralighi", "dostyk", "mektep"), audience="10+",
        format="single",
        updated_days_ago=12,
    ),
    Story(
        slug="aidana-erteg",  title="Ертегі ертеректегі",      author_username="aidana",
        cover="ipad_eec6a1375d9124c7348c7579b8d2db33.jpg", genres=("erteg", None),
        # Фикстура «произведение без глав» для manage_story
        # (test_write.ManageStoryEmptyChapters): записи в CHAPTERS_BY_STORY
        # нет, и «N бөлім» теперь считается по ней, а не объявляется.
        views=0, likes=0, comments=0,
        status="OnModeration", recent_views=0, annotation="Дәстүрлі ертегі формасында жазылған заманауи тарих.",
        audience="10+",
        updated_days_ago=4,
    ),
    Story(
        slug="aidana-kysh",   title="Қыстың үнсіздігі",        author_username="aidana",
        cover="ipad_f0e918b204613b38cc0e04ba74e3e3ab.webp", genres=("drama", None),
        views=872, likes=64, comments=9,
        status="Published", recent_views=190, annotation="Қыстағы ауылда қалған әжемен өткізген бір ай. Аяқталған кітап.",
        audience="10+",
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
        views=0, likes=0, comments=0,
        status="NotPublished", recent_views=0,
        annotation="Ауыл баласы мен түнгі аспан туралы. Әзірге бас-аяғы ойда.",
        updated_days_ago=9,
    ),
]

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





# Тексты глав лежат в приложении, а не здесь: 48 файлов прозы,
# заведённые литералом python, нечитаемы и неправимы.
STORY_TEXTS_DIR = Path(__file__).resolve().parents[2] / "story_texts"

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
                 reactions=(("tangaldym", 1580), ("shabyt", 1110), ("kuldim", 640), ("juregim", 320), ("jyladym", 240))),
    ],
}

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

# ───────────────────────── Комментарии (для STORY) ────────────────────────

@dataclass(frozen=True)
class StoryComment:
    author_username: str
    # Насколько давно написан — длительностью, а не строкой. Строку («2 сағат
    # бұрын») пришлось бы разбирать обратно в момент времени, и разбор жил в
    # сиде: подпись выводится из `created_at` (BR-70a), а не хранится.
    ago: timedelta
    text: str
    likes: int = 0
    is_author_badge: bool = False
    liked: bool = False             # текущий пользователь поставил лайк
    replies: tuple = ()             # один уровень вложенности (BR-30); tuple[StoryComment]
    chapter_number: int | None = None   # к какой главе пришвартован; None = общий, на всё произведение




COMMENTS_BY_STORY: dict = {
    # Богатый набор — иллюстрирует все кейсы дизайна:
    # короткий/длинный, лайкнутый текущим юзером, бейдж «Автор»,
    # нить с одним и двумя ответами (BR-30: только 1 уровень).
    "dalney-berega": [
        # 1) Длинный читательский с нитью из 2 ответов — про 3-й бөлім
        StoryComment(
            "aygerim_k", timedelta(hours=2),
            "Тамаша шығарма! Әсіресе үшінші бөлімдегі қарттың сұрағы — «жүректің не дейтіні?» — әлі есімде. "
            "Авторға айтарым: тіл өте таза, метафоралары жанды. Сирек кездесетін сапа. "
            "Жалғасын асыға күтемін, тағы 4 бөлім жетеді деп үміттенемін.",
            likes=24,
            chapter_number=3,
            replies=(
                StoryComment(
                    "sayyn", timedelta(hours=1),
                    "Рахмет, Айгерім! Үшінші бөлім — менің ең қиналған сәтім болды. "
                    "Сезімің мен үшін маңызды.",
                    likes=18, is_author_badge=True,
                ),
                StoryComment(
                    "bekzhan_t", timedelta(minutes=45),
                    "Айгерімнің пікіріне қосыламын.",
                    likes=3,
                ),
            ),
        ),
        # 2) Ответ автора верхнеуровневый — общее объявление, не привязано к главе
        StoryComment(
            "sayyn", timedelta(days=1),
            "Пікірлерге рахмет. Келесі бөлім жұма күні шығады, дайындап жатырмын.",
            likes=87, is_author_badge=True,
        ),
        # 3) Короткий, лайкнут текущим пользователем — про 1-ю главу
        StoryComment(
            "bekzhan_t", timedelta(days=3),
            "Тіл өте таза, метафоралары жанды.",
            likes=12, liked=True,
            chapter_number=1,
        ),
        # 4) Очень короткий — на 4-ю главу, где стоит закладка Айданы
        StoryComment(
            "dina_books", timedelta(days=5),
            "Бұл бөлім — шедевр.",
            chapter_number=4,
        ),
        # 5) Свой комментарий демо-пользователя — на 3-ю главу.
        # Нужен, чтобы ветка «свой» в меню (Жою вместо Шағым, BR-33) вообще
        # была видна: без него дизайн-фаза показывала только чужие.
        StoryComment(
            "aidana", timedelta(hours=4),
            "Қарттың «жүректерің не дейді?» деген сұрағынан кейін кітапты жауып, біраз ойланып отырдым.",
            likes=6,
            chapter_number=3,
        ),
        # 6) С одним ответом от автора — на 2-ю главу
        StoryComment(
            "rudazov", timedelta(days=7),
            "Стилистика Брэдбериге ұқсайды — бұл мен үшін үлкен мадақ. Жалғастыр!",
            likes=9,
            chapter_number=2,
            replies=(
                StoryComment(
                    "sayyn", timedelta(days=6),
                    "Рудазов, рахмет! Брэдбериді жасөспірім кезімде оқыған едім — әсері қалған шығар.",
                    likes=4, is_author_badge=True,
                ),
            ),
        ),
    ],
    # Вторая история — менее активная, для проверки разных story_detail
    "kronchessii": [
        StoryComment(
            "aygerim_k", timedelta(hours=5),
            "Бірінші тарау қызықтыра түсті, бірақ кейіпкерлердің мотивациясы әлі түсініксіз. "
            "Авторға сұрақ: бұл қасақана ма?",
            likes=6,
            chapter_number=1,
            replies=(
                StoryComment(
                    "rudazov", timedelta(hours=3),
                    "Иә, бұл әдейі. Кейіпкерлер 4-бөлімде ашылады. Шыдамдылықпен оқы.",
                    likes=11, is_author_badge=True,
                ),
            ),
        ),
        # Общий — без главы
        StoryComment(
            "sayyn", timedelta(days=2),
            "Кронцессиялардың тілі — нағыз олжа. Әрбір сөз орнында.",
            likes=22, liked=True,
        ),
    ],
}

# ───────────────────────── Прогресс чтения (для returning hero) ────────────

# ───────────────────────── Книга недели (FR-HOME-03) ──────────────────────

@dataclass(frozen=True)
class BookOfWeek:
    story_slug: str
    editorial_note: str          # цитата от редакции
    quote: str                   # цитата из книги


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

# ───────────────────────── Конкурсы (CONT) ─────────────────────────────────

@dataclass(frozen=True)
class JuryMember:
    name: str
    role: str   # «Төраға», «Мүше», ...

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
    # Афиша конкурса — файл в MEDIA_ROOT (`contests/<slug>.png`), его
    # загружает админ, как и эмблему награды (BR-46). Пусто — платформа
    # рисует типографическую афишу по названию.
    #
    # Раньше здесь лежал путь в `static/img/bookN.jpg`: фотография книжной
    # обложки в роли афиши. Она не имела к конкурсу отношения ни одним
    # пикселем, и четыре конкурса различались тем, чья книга досталась
    # каждому. Свои афиши платформе взять неоткуда, поэтому в стабе поле
    # пустое у всех — виден ровно тот вид, который получает конкурс без
    # загруженного файла.
    poster: str = ""
    # Слаг «семейства» — повторяющегося конкурса, у которого бывают
    # выпуски разных лет (BR-47). Пусто — разовый конкурс.
    series: str = ""
    description: str = ""
    conditions: tuple = ()       # bullet points
    timeline: tuple = ()         # TimelineStage[]
    jury: tuple = ()             # JuryMember[]
    # BR-22: пороги объёма для подачи (знаки)
    min_chars: int = 5_000
    max_chars: int = 15_000
    # Возрастное требование конкурса (BR-48). Любая граница может быть
    # None — конкурс её не ставит; обе None — возраст не ограничен вовсе.
    #
    # Возраст живёт здесь, а не в правилах платформы: у платформы своего
    # ценза нет. Прежнее BR-20 объявляло «14-18 лет» глобально, и потому
    # конкурс со своей вилкой выразить было нечем — все четыре повторяли
    # одну и ту же строку руками.
    min_age: Optional[int] = None
    max_age: Optional[int] = None
    # Номинации этого конкурса (DEC-46). Показываются ДО итогов — «вот что
    # получит победитель» отвечает на «зачем участвовать» лучше, чем сумма
    # в тенге.
    awards: tuple = ()





















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
        min_age=14, max_age=18,
        description=(
            "Республикалық мектеп оқушыларына арналған әдеби байқау. Мақсаты — "
            "жас прозаиктерді табу әрі қолдау. Қазақ және орыс тілдеріндегі шығармалар қабылданады."
        ),
        # Только то, чем этот конкурс отличается. Возраст приходит из
        # `min_age`/`max_age`, остальное — из `common_rules`: там оно
        # написано один раз для всех.
        conditions=(
            "Жанры еркін",
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
        min_age=16, max_age=25,
        description=(
            "Қазақ тіліндегі жас прозаиктердің ұлттық байқауы. "
            "Үздік үш шығарма платформаның басты бетінде жарияланып, "
            "сыйақы алады."
        ),
        # «Тек қазақ тілінде» — настоящее условие: платформа принимает два
        # языка (BR-21), этот конкурс сужает до одного.
        conditions=(
            "Тек қазақ тілінде",
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
        # Возраст не ограничен: так выглядит конкурс, который ценза не
        # ставит. До BR-48 такого состояния не было — «14-18» стояло у всех.
        description=(
            "Қысқы демалысқа арналған әңгіме байқауы. Тақырып еркін, "
            "бірақ оқиға қыс мезгілінде өтуі керек."
        ),
        conditions=(
            "Оқиға қыс мезгілінде өтуі керек",
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
        series="zhas-aldym",
        max_age=22,
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
    # Второй выпуск того же конкурса (BR-47). Он объявлен последним
    # намеренно: `ACCEPTING_CONTESTS[0]` — конкурс баннера главной, и
    # порядок объявления решает, какой туда попадёт.
    #
    # Без него связь выпусков нечем показать, а показать её нужно: пока
    # выпуска этого года не было, страница «Жас алдым — 2023» кончалась
    # составом жюри, и пришедшему из поиска идти было некуда.
    Contest(
        "zhas-aldym-2026", "Жас алдым — 2026", "Республикалық әдеби байқау",
        opens_on=_d(-20), closes_on=_d(25), results_on=_d(60),
        prize_kzt=400_000,
        series="zhas-aldym",
        min_age=16,
        description=(
            "«Жас алдым» — жыл сайын өтетін республикалық байқау. "
            "Былтырғыдай, биыл да екі номинация бар."
        ),
        conditions=(),
        timeline=(
            TimelineStage("Өтінім қабылдау", _d(-20), _d(25)),
            TimelineStage("Қазылар қарауы", _d(26), _d(59)),
            TimelineStage("Жеңімпаздар", _d(60), _d(60)),
        ),
        jury=(
            JuryMember("Алмат Рысқали", "Төраға"),
            JuryMember("Дина Айдарбекова", "Мүше"),
        ),
        awards=(
            ContestAward("bas-zhulde", "Бас жүлде",
                         description="Қазылар алқасы таңдаған үздік шығарма."),
            ContestAward("oqyrman-tandauy", "Оқырман таңдауы",
                         description="Оқырман дауысы бойынша үздік шығарма."),
        ),
    ),
]

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
        # Идущий конкурс «Жас алдым — 2026»: приём открыт, жюри ещё не
        # судит, но заявка уже прошла первичный отбор — участник виден в
        # списке страницы конкурса до объявления итогов (FR-CONT-16).
        Submission(
            contest_slug="zhas-aldym-2026", story_slug="atam-aityp-berdi",
            submitted_on=_d(-6), status="accepted",
            note="Талаптарға сай, қабылданды.",
        ),
    ],
    "bekzhan_t": [
        Submission(
            contest_slug="zhas-aldym-2023", story_slug="temniy-lord",
            submitted_on=date(2023, 10, 5), status="accepted",
            note="Қазылар алқасының таңдауы.",
        ),
    ],
    # «Жас алдым — 2026» — единственный текущий конкурс с реальными
    # участниками в корпусе (остальные идущие держат только `reviewing`).
    "sayyn": [
        Submission(
            contest_slug="zhas-aldym-2026", story_slug="kunnin-songy-sagaty",
            submitted_on=_d(-10), status="accepted",
            note="Талаптарға сай, қабылданды.",
        ),
    ],
}

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
    - 'reading' — Оқу үстіндегі (читает сейчас)
    - 'done'    — Оқылғаны (прочитал)

    У 'reading' сид заводит ещё и закладку (`ReadingProgress`): глава и
    цитата отсюда, оставшееся время считается по главам. Отдельного
    литерала прогресса больше нет: два источника одного факта в корпусе
    уже разошлись (DEC-52).
    """
    story_slug: str
    kind: str                       # 'saved' | 'reading' | 'done'
    added_ago: timedelta            # когда положил на полку; подпись выводится
    progress_chapter: int = 1       # глава закладки; имеет смысл только для 'reading'
    quote: str = ''                 # последний абзац, на котором остановился


# Библиотека Айданы. Используется PROF/LIB.
LIBRARY_BY_USER: dict = {
    "aidana": [
        # ── Оқу үстіндегі ──
        LibraryEntry("dalney-berega",  "reading", timedelta(days=2), progress_chapter=4,
                      quote="«…қалай ойлайсыз, бұл саяхатымыздың соңына жеттік пе?» — деді Сандр, біраз үнсіз отырып."),
        LibraryEntry("kronchessii",    "reading", timedelta(days=7), progress_chapter=2),
        # ── Сақталған ──
        LibraryEntry("temniy-lord",    "saved",   timedelta(0)),
        LibraryEntry("igra-kuklovoda", "saved",   timedelta(days=3)),
        LibraryEntry("arhimag",        "saved",   timedelta(days=14)),
        # ── Оқылғаны ──
        LibraryEntry("sila-imperii",   "done",    timedelta(days=30)),
    ],
}

# ───────────────────────── PROF — граф подписок ───────────────────────────

# username → set[username]; «X подписан на Y» означает Y ∈ FOLLOWING[X].
FOLLOWING: dict = {
    "aidana":    {"rudazov", "sayyn", "dina_books"},
    "bekzhan_t": {"rudazov"},
    "aygerim_k": {"rudazov", "aidana"},
}

# ───────────────────────── NOTIF — уведомления ────────────────────────────

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
    outcome: str = ""           # kind='moderation': см. MODERATION_OUTCOMES; '' — решения нет
    text: str = ""              # только событие: имя предмета приходит из объекта
    read: bool = False          # прочитано ли







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
            story_slug="aidana-erteg", outcome="",
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
        # Возврат на доработку с замечанием — BR-11 требует именно его,
        # иначе автор не знает, что исправлять. Замечание лежит в `text`:
        # это собственные слова модератора, а не пересказ данных, — то же
        # исключение из BR-72a, по которому у `comment` в `text` стоит
        # цитата читателя.
        #
        # Это `needs_work`, а не `rejected`: работу просят продолжить, и
        # docs/13 §13.5 требует называть такое приглашением, а не отказом.
        # Работа при этом вернулась в черновики (`aidana-kus` —
        # `NotPublished`): данные не должны противоречить статусу.
        Notification(
            kind="moderation", days_ago=5,
            story_slug="aidana-kus", outcome="needs_work",
            text="Бірінші бөлімде диалогтар үзіліп қалған. Толықтырып, қайта жіберші.",
            read=True,
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


# Хиро гостя считает цифры платформы через `portal_stats()` — по самим
# данным. Хранимый `PLATFORM_STATS` с литералами («3 байқау» при пяти
# заведённых) не читал никто: он остался от первой редакции главной и
# пережил её на три месяца, ни разу не попав на экран.

