"""
Стаб-данные для дизайн-фазы. Здесь живут все «как будто из БД» сущности,
которые рисует UI. После Ф14 этот файл заменится на Django-модели.

Не импортировать в продакшен-логику — это сугубо для рендера шаблонов.
"""

from dataclasses import dataclass, field
from typing import Optional


# ───────────────────────── Жанры (docs/03 — 12 шт) ─────────────────────────

@dataclass(frozen=True)
class Genre:
    slug: str
    name: str       # казахское название
    hue: int        # OKLCH hue 0-360
    count: int      # сколько произведений


GENRES = [
    Genre("fantastika", "Фантастика", 250, 124),
    Genre("fantezi",    "Фэнтези",    295,  87),
    Genre("triller",    "Триллер",    210,  56),
    Genre("romantika",  "Романтика",    8, 142),
    Genre("drama",      "Драма",      195,  91),
    Genre("horror",     "Хоррор",      25,  34),
    Genre("erteg",      "Ертегі",      75,  48),
    Genre("tarih",      "Тарихи",      40,  29),
    Genre("komediya",   "Комедия",     55,  61),
    Genre("fanfik",     "Фанфик",     330,  38),
    Genre("balalar",    "Балалар",    180,  77),
    Genre("shyttyrman", "Шытырман",   145,  53),
]

GENRES_BY_SLUG = {g.slug: g for g in GENRES}


# ───────────────────────── Пользователи / Авторы ─────────────────────────

@dataclass(frozen=True)
class Author:
    username: str   # без @
    name: str
    bio: str
    works: int
    followers: int


AUTHORS = [
    Author("rudazov",   "Алмат Рысқали",     "Фэнтези, шытырман",      12, 8420),
    Author("aygerim_k", "Айгерім Қасенова",  "Жас прозаик · Алматы",    3,  184),
    Author("bekzhan_t", "Бекжан Тұрсынов",   "Қалалық әңгімелер",       5,  312),
    Author("dina_books","Дина Айдарбекова",  "Балалар әдебиеті",        8,  542),
    Author("sayyn",     "Сайын Нұрбекұлы",   "Фантастика, шытырман",    2,   96),
    # Демо-пользователь, под которым логинимся через фейк-сессию (см. core.views.login_view).
    Author("aidana",    "Айдана Серікқызы",  "Жас прозаик · Тараз",     4,   23),
]

AUTHORS_BY_USERNAME = {a.username: a for a in AUTHORS}


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


STORIES = [
    Story("dalney-berega",  "Алыс жағалауларда",     "sayyn",      "img/book1.jpg", ("fantastika",  None),         12, 12482, 4821, 312, status="Published"),
    Story("temniy-lord",    "Күңгірт мырза",         "bekzhan_t",  "img/book3.jpg", ("fantezi",     "horror"),      8,  8920, 2440, 156, status="Published"),
    Story("igra-kuklovoda", "Қуыршақшының ойыны",    "dina_books", "img/book4.jpg", ("triller",     "drama"),      15, 18102, 6230, 421, status="Published"),
    Story("kronchessii",    "Тас уәделер",           "rudazov",    "img/book2.jpg", ("shyttyrman",  "fantezi"),    24, 32540, 11200, 890, status="Published"),
    Story("arhimag",        "Сиқыршы: бөтен әлемдер","rudazov",    "img/book1.jpg", ("fantezi",     "shyttyrman"), 12, 12482, 4821, 312, status="Published"),
    Story("sila-imperii",   "Империя құдіреті",      "aygerim_k",  "img/book3.jpg", ("tarih",       "drama"),      18, 14200, 3890, 245, status="Published"),

    # ─ Произведения демо-пользователя «Айдана» (для WRITE-страниц) ─
    Story(
        slug="aidana-tan",    title="Таң алдында",            author_username="aidana",
        cover="img/book2.jpg", genres=("drama", None),
        chapters=8, views=1042, likes=87, comments=12,
        status="Published", annotation="Жас қыздың Алматыдан Таразға қайту туралы әңгімесі. Сегіз бөлімде, әр бөлім — жаңа қала.",
    ),
    Story(
        slug="aidana-koshe",  title="Көше әндері",            author_username="aidana",
        cover="img/book4.jpg", genres=("drama", "komediya"),
        chapters=5, views=203, likes=18, comments=4,
        status="OnProcess", annotation="Қаладағы бес адамның бір күні. Әрқайсысының өз әні.",
        secondary_genre="komediya",
    ),
    Story(
        slug="aidana-erteg",  title="Ертегі ертеректегі",      author_username="aidana",
        cover="img/book3.jpg", genres=("erteg", None),
        chapters=3, views=0, likes=0, comments=0,
        status="OnModeration", annotation="Дәстүрлі ертегі формасында жазылған заманауи тарих.",
    ),
    Story(
        slug="aidana-kysh",   title="Қыстың үнсіздігі",        author_username="aidana",
        cover="img/book1.jpg", genres=("drama", None),
        chapters=12, views=872, likes=64, comments=9,
        status="Completed", annotation="Қыстағы ауылда қалған әжемен өткізген бір ай. Аяқталған кітап.",
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


# Длинный lorem-текст для проверки скролла/тёмной темы (≈5 000 знаков)
_SAMPLE_BODY = (
    "Бірде ерте таңда, мен тауларға қарап тұрдым. Күн жаңа ғана шығып келе жатқан, "
    "аспан алтын түсті болатын. Сандр менің жанымда үнсіз отырды — оның көздері "
    "алыс белдеудегі бір нүктеге қадалған. Біз бұл саяхатты үш жыл бойы күткен едік, "
    "енді міне, оның соңғы күні басталып қалды.\n\n"
    "— Қалай ойлайсың, — деді ол ақырында, — біз барар жерімізге жеткен боламыз ба?\n\n"
    "Мен жауап бере алмадым. Тауларды қарап тұрып, өзім де нақты білмейтінімді сездім. "
    "Біздің картамыз әлдеқашан бұрмаланған, жетекшіміз бізді тастап кеткен, "
    "ал алда не күтіп тұрғаны — белгісіз. Бірақ ішкі бір сезім «жалғастыр» деп "
    "сыбырлап тұрды. Біз тұрып, жолға шықтық.\n\n"
    "Жол қиын болды. Тастар сырғанап, жел әл-қуатымызды алып бара жатты. "
    "Бірақ Сандр алға қарай батыл басып отырды, ал мен оның артынан ілесіп, "
    "өзімді осы саяхатқа лайық деп сезінуге тырыстым. Ой үстінде өзіме «сен қажет «"
    "емессің, сен мұнда бекерге», — деген дауыстар жиі келетін. Бірақ Сандр "
    "оларды естіді ме білмеймін — сұрап көрген жоқпын.\n\n"
    "Біз биік шыңға жетіп, шаршап отырған кезде, төмендегі алқаптан түтін көтерілгенін "
    "байқадық. Ауыл! Демек, әлі де адам тұратын жерлер бар. Сандр маған қарап күлді — "
    "оның көзінде үміт жанып тұрды. Біз бір-бірімізге қол беріп, тыныстап алдық та, "
    "жолды жалғастырдық.\n\n"
    "Ауылға жеткенде, біздің таңқалғанымыздай, бұл — ескі замандағы шағын тұрақ "
    "болатын. Үйлер ағаштан, шатырлар сабаннан жасалған. Балалар көшеде ойнап жүр, "
    "ересектер бір-бірімен қазақша сөйлеседі. Мен бұл диалектіні бұрын естіген емес "
    "едім — Сандр да солай. Бірақ түсіну қиын болмады.\n\n"
    "Аққалпақты бір қарт біздің қасымызға келді. Көзі жарқырап, бізді танығандай "
    "қарады.\n\n"
    "— Сіздерді күтіп жүрдім, — деді ол. — Кітапты алып келдіңіздер ме?\n\n"
    "Мен Сандрға қарадым. Сандр маған қарады. Қандай кітап? Біз жай саяхатшылар "
    "едік, ешқандай кітап туралы білмейтінбіз. Қарт қарсы жауапты күтпестен әрі "
    "жалғастырды:\n\n"
    "— Жоқ па? Онда сіздер жалғыз келдіңіздер. Бірақ келдіңіздер ғой — бұл да жақсы. "
    "Жүріңіздер, шай ішеміз.\n\n"
    "Біз оның артынан ердік. Менің басымда мың сұрақ ойнап жатты, бірақ оларды қою "
    "уақыты әлі келмеген сияқты. Сандр да үнсіз. Ауыл арқылы өткен сайын мен "
    "өзімізді бір ертегінің ішіне түсіп қалдық деген ойдан арыла алмадым.\n\n"
    "Қарттың үйі шеттеу тұрды. Іші тар, бірақ жылы. Қабырғаларында ескі суреттер, "
    "сөрелерде сары парақты кітаптар. Ол шай қайнатты, бізге нан мен балды жайып "
    "берді. Біз ауыздан-ауыз қалай оның үйіне түскенімізді айта бастадық — карта, "
    "жетекшінің кетуі, көп күн жүруіміз туралы. Қарт басын изеп, ара-арасында «иә, "
    "иә» деп қойды.\n\n"
    "Содан кейін ол маған қарап:\n\n"
    "— Сенің жүрегің не дейді? — деп сұрады.\n\n"
    "Бұл сұрақ мені есімнен айырғандай болды. Мен жүректі тыңдауды ұмытқан "
    "адам сияқтымын. Күн сайын — жоспар, мақсат, нәтиже. Жүрек? Ол қашан "
    "сөйледі еді? Мен жауап бере алмадым. Сандр да үнсіз отырды.\n\n"
    "— Біз жалғастыруымыз керек пе? — деп сұрадым ақырында.\n\n"
    "— Әрине, — деді қарт. — Бірақ басқа бағытта.\n\n"
    "Сол түні мен ұйықтай алмадым. Сыртта жұлдыздар жанып тұрды, иттер алыста "
    "үретін. Мен өзімнің не үшін осы жолға шыққанымды есіме түсіруге тырыстым — "
    "ескерту ме, әлде үрей ме? Бір кезде Сандр оянып, маған қарап:\n\n"
    "— Біз кейін қайтамыз ба? — деп сұрады.\n\n"
    "— Білмеймін. Бірақ сенің ішкі дауысыңа сен. Бұл — менің қателігім, сені "
    "соңыма еріткенім. Енді өз шешіміңді өзің жаса.\n\n"
    "Ол маған ұзақ қарап тұрды. Содан кейін кірпігін жұмды. Мен сол түні бірінші "
    "рет «бұл саяхаттың соңы — менің соңым емес» дегенді түсіндім. Ол өз жолын "
    "табатын болады — менсіз де."
)


CHAPTERS_BY_STORY: dict = {
    # Айдана / aidana — главы для manage_story и chapter_editor
    "aidana-tan": [
        # Сумма = 12 800 знаков → попадает в окно 5000-15000 для CONT-чек-листа.
        Chapter(1, "Алматыдан шығу",      1500, _SAMPLE_BODY),
        Chapter(2, "Шу станциясы",         2100, ""),
        Chapter(3, "Поезд жолдастары",     1900, ""),
        Chapter(4, "Кешкі ас",             1700, ""),
        Chapter(5, "Қап-қараңғы",          1800, ""),
        Chapter(6, "Таң алдында",          1900, ""),
        Chapter(7, "Тараз",                1100, ""),
        Chapter(8, "Үй",                    800, ""),
    ],
    "aidana-koshe": [
        Chapter(1, "Бірінші көше",         800, ""),
        Chapter(2, "Темір жол қасында",    1200, ""),
        Chapter(3, "Базар алдында",        950, ""),
        Chapter(4, "Парк ішінде",          1100, ""),
        Chapter(5, "Кеш батқанда",         700, ""),
    ],
    "dalney-berega": [
        # FR-STORY-12: лайки — на главу, не на произведение целиком.
        # Прогрессия лайков иллюстрирует «крючок»: первые главы заходят, к середине пик,
        # глава 4 — текущая для возвращающегося читателя (liked=True), последние ещё впереди.
        Chapter(1, "Жолға шығу",           1800, _SAMPLE_BODY, likes=842),
        Chapter(2, "Тауға көтерілу",       2400, _SAMPLE_BODY, likes=719),
        Chapter(3, "Алғашқы кездесу",      3100, _SAMPLE_BODY, likes=1024),
        Chapter(4, "Депрессия",            2800, _SAMPLE_BODY, likes=687, liked=True),
        Chapter(5, "Жаңа карта",           2200, "",           likes=512),
        Chapter(6, "Жаңбыр түн",           1900, "",           likes=438),
        Chapter(7, "Тас үй",               2700, "",           likes=391),
        Chapter(8, "Кездесу",              2100, "",           likes=287),
        Chapter(9, "Жасырын есік",         3300, "",           likes=176),
        Chapter(10, "Қайту",               2500, "",           likes=94),
        Chapter(11, "Соңғы кеш",           1700, "",           likes=42),
        Chapter(12, "Шеп",                 2900, "",           likes=18),
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

    @property
    def author(self):
        return AUTHORS_BY_USERNAME.get(self.author_username)


COMMENTS_BY_STORY: dict = {
    # Богатый набор — иллюстрирует все кейсы дизайна:
    # короткий/длинный, лайкнутый текущим юзером, бейдж «Автор»,
    # нить с одним и двумя ответами (BR-30: только 1 уровень).
    "dalney-berega": [
        # 1) Длинный читательский с нитью из 2 ответов (включая ответ автора)
        StoryComment(
            "aygerim_k", "2 сағат бұрын",
            "Тамаша шығарма! Әсіресе үшінші бөлімдегі қарттың сұрағы — «жүректің не дейтіні?» — әлі есімде. "
            "Авторға айтарым: тіл өте таза, метафоралары жанды. Сирек кездесетін сапа. "
            "Жалғасын асыға күтемін, тағы 4 бөлім жетеді деп үміттенемін.",
            likes=24,
            replies=(
                StoryComment(
                    "sayyn", "1 сағат бұрын",
                    "Рахмет, Айгерім! Үшінші бөлім — менің ең қиналған сәтім болды. "
                    "Сезіміңіз мен үшін маңызды.",
                    likes=18, is_author_badge=True,
                ),
                StoryComment(
                    "bekzhan_t", "45 мин бұрын",
                    "Айгерімнің пікіріне қосыламын.",
                    likes=3,
                ),
            ),
        ),
        # 2) Ответ автора верхнеуровневый (с бейджем) — без нити
        StoryComment(
            "sayyn", "1 күн бұрын",
            "Пікірлерге рахмет. Келесі бөлім жұма күні шығады, дайындап жатырмын.",
            likes=87, is_author_badge=True,
        ),
        # 3) Короткий, лайкнут текущим пользователем
        StoryComment(
            "bekzhan_t", "3 күн бұрын",
            "Тіл өте таза, метафоралары жанды.",
            likes=12, liked=True,
        ),
        # 4) Очень короткий, без лайков — иллюстрирует нулевое состояние
        StoryComment(
            "dina_books", "5 күн бұрын",
            "👍",
        ),
        # 5) С одним ответом от автора (типичный кейс «спасибо за фидбек»)
        StoryComment(
            "rudazov", "1 апта бұрын",
            "Стилистика Брэдбериге ұқсайды — бұл мен үшін үлкен мадақ. Жалғастыр!",
            likes=9,
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
            replies=(
                StoryComment(
                    "rudazov", "3 сағат бұрын",
                    "Иә, бұл әдейі. Кейіпкерлер 4-бөлімде ашылады. Шыдамдылықпен оқыңыз 🙂",
                    likes=11, is_author_badge=True,
                ),
            ),
        ),
        StoryComment(
            "sayyn", "2 күн бұрын",
            "Кронцессиялардың тілі — нағыз олжа. Әрбір сөз орнында.",
            likes=22, liked=True,
        ),
    ],
}


def comments_of(story_slug: str) -> list:
    return COMMENTS_BY_STORY.get(story_slug, [])


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
        if q in s.title.lower() or q in s.author.name.lower()
    ]


def search_authors(query: str, limit: int = 5) -> list:
    """Substring-поиск по name и username автора (для search popup)."""
    q = (query or "").strip().lower()
    if not q:
        return []
    return [
        a for a in AUTHORS
        if q in a.name.lower() or q in a.username.lower()
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


def apply_catalog_filters(stories: list, sort: str = "popularity", status: str = "") -> list:
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

    if sort == "alphabet":
        out.sort(key=lambda s: s.title.lower())
    elif sort == "recent":
        out.reverse()
    else:  # popularity (default)
        out.sort(key=lambda s: s.views, reverse=True)
    return out


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
    slug: str
    name: str
    count: int
    tint_hue: int                # OKLCH hue для тонировки карточки и иконки
    icon: str                    # slug SVG-иконки из спрайта (без префикса icon-)
    cover_slugs: tuple           # 3 story slug — для fallback и детальной (стопка обложек)
    curator: str = "редакция"    # «Құрастырған: …»
    description: str = ""        # описание подборки на детальной
    story_slugs: tuple = ()      # все произведения внутри; пусто → fallback на cover_slugs

    @property
    def covers(self) -> list:
        """Story-объекты для стопки обложек на карточке коллекции."""
        return [STORIES_BY_SLUG[s] for s in self.cover_slugs if s in STORIES_BY_SLUG]

    @property
    def stories(self) -> list:
        """Все произведения подборки (для детальной)."""
        slugs = self.story_slugs or self.cover_slugs
        return [STORIES_BY_SLUG[s] for s in slugs if s in STORIES_BY_SLUG]


COLLECTIONS = [
    Collection(
        slug="zhaz-okyrman", name="Жаз оқырмандарына",
        count=6, tint_hue=75, icon="planet",
        cover_slugs=("dalney-berega", "temniy-lord", "igra-kuklovoda"),
        curator="редакция",
        description="Жазғы демалысқа арналған жеңіл әрі қызық оқу. Ұзақ түнгі поезд сапары немесе теңіз жағасында бір күн — осы тізіммен.",
        story_slugs=("dalney-berega", "temniy-lord", "igra-kuklovoda", "sila-imperii", "arhimag", "kronchessii"),
    ),
    Collection(
        slug="bir-otyru", name="Бір отыруда оқу",
        count=3, tint_hue=210, icon="book",
        cover_slugs=("kronchessii", "dalney-berega", "temniy-lord"),
        curator="редакция",
        description="Қысқа форматтар — бір кешке. Әр шығарма 3 сағаттан аспайды.",
        story_slugs=("temniy-lord", "dalney-berega", "sila-imperii"),
    ),
    Collection(
        slug="kazak-avt", name="Қазақ авторлары",
        count=4, tint_hue=195, icon="feather",
        cover_slugs=("temniy-lord", "igra-kuklovoda", "kronchessii"),
        curator="Бекжан Тұрсынов",
        description="Қазақстандық авторлардың үздік шығармалары. Жас прозаиктерден танымал классиктерге дейін.",
        story_slugs=("kronchessii", "arhimag", "sila-imperii", "dalney-berega"),
    ),
    Collection(
        slug="korkynyshty", name="Қорқынышты түн",
        count=3, tint_hue=25, icon="skull",
        cover_slugs=("igra-kuklovoda", "kronchessii", "dalney-berega"),
        curator="редакция",
        description="Күн батқанда оқуға арналған. Тек ересектерге ұсынылады.",
        story_slugs=("igra-kuklovoda", "temniy-lord", "kronchessii"),
    ),
    # ── Настроенческие подборки ────────────────────────────────────────
    Collection(
        slug="kozzhasty-tun", name="Көзжасты түн",
        count=5, tint_hue=250, icon="drop",
        cover_slugs=("dalney-berega", "kronchessii", "temniy-lord"),
        curator="редакция",
        description="Ішкі үнсіздікке арналған шығармалар — қайғы, қимас сезім, өткен күндер туралы.",
        story_slugs=("dalney-berega", "kronchessii", "temniy-lord", "sila-imperii", "arhimag"),
    ),
    Collection(
        slug="mektep-kundeligi", name="Мектеп күнделігі",
        count=4, tint_hue=130, icon="backpack",
        cover_slugs=("temniy-lord", "arhimag", "sila-imperii"),
        curator="редакция",
        description="Мектеп жасындағы кейіпкерлер: сабақ, достық, алғашқы сезімдер.",
        story_slugs=("temniy-lord", "arhimag", "sila-imperii", "kronchessii"),
    ),
    Collection(
        slug="zhuldyzdan-kelgender", name="Жұлдыздан келгендер",
        count=4, tint_hue=280, icon="planet",
        cover_slugs=("sila-imperii", "arhimag", "kronchessii"),
        curator="редакция",
        description="Бөгде планеталық қонақтар, ғарыштық кездесулер және белгісіз әлемдер.",
        story_slugs=("sila-imperii", "arhimag", "kronchessii", "igra-kuklovoda"),
    ),
    Collection(
        slug="kala-anyzdary", name="Қала аңыздары",
        count=5, tint_hue=15, icon="cityscape",
        cover_slugs=("igra-kuklovoda", "temniy-lord", "kronchessii"),
        curator="редакция",
        description="Қалалық мифтер, түнгі көше әңгімелері, шынайылық пен сиқыр шегіндегі оқиғалар.",
        story_slugs=("igra-kuklovoda", "temniy-lord", "kronchessii", "dalney-berega", "arhimag"),
    ),
    Collection(
        slug="kalam-ustagan-kyzdar", name="Қалам ұстаған қыздар",
        count=4, tint_hue=340, icon="feather",
        cover_slugs=("dalney-berega", "arhimag", "kronchessii"),
        curator="редакция",
        description="Қыз авторлардың шығармалары — нәзік, ашық және ерекше дауыстар.",
        story_slugs=("dalney-berega", "arhimag", "kronchessii", "sila-imperii"),
    ),
    Collection(
        slug="zhana-zhyl-tuninde", name="Жаңа жыл түнінде",
        count=3, tint_hue=0, icon="fir",
        cover_slugs=("arhimag", "temniy-lord", "dalney-berega"),
        curator="редакция",
        description="Мерекелік көңіл-күй, ғажайыпқа сенім және қыс кешінің жылуы.",
        story_slugs=("arhimag", "temniy-lord", "dalney-berega"),
    ),
    Collection(
        slug="tiri-olikter", name="Тірі өліктер",
        count=3, tint_hue=100, icon="skull",
        cover_slugs=("igra-kuklovoda", "sila-imperii", "kronchessii"),
        curator="редакция",
        description="Зомби-апокалипсис, тірі қалу күресі және адамзаттан кейінгі әлем.",
        story_slugs=("igra-kuklovoda", "sila-imperii", "kronchessii"),
    ),
    Collection(
        slug="kulki-men-kuanysh", name="Күлкі мен қуаныш",
        count=4, tint_hue=60, icon="smile",
        cover_slugs=("temniy-lord", "arhimag", "dalney-berega"),
        curator="редакция",
        description="Жеңіл, жылы, көңіл көтеретін шығармалар — кейде күлкі ең жақсы дәрі.",
        story_slugs=("temniy-lord", "arhimag", "dalney-berega", "sila-imperii"),
    ),
]

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
        LibraryEntry("kronchessii",    "reading", "1 апта бұрын", progress_chapter=11),
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
            text="Жас автордың тілі жаңа да жанды. Әрі қарай жалғастырыңыз.",
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
