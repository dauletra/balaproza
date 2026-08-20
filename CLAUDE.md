# CLAUDE.md

Заметки для Claude Code по проекту `balaproza_v1`. Платформа — Balaproza, казахоязычный детский литературный портал. Подробное ТЗ — в [`docs/`](docs/) (модули 01-11).

## Текущий фокус

Делаем **только дизайн-систему** (вёрстка, токены, компоненты, шаблоны) и стаб-данные для рендера.
**НЕ трогаем**: модели БД, миграции, формы, бизнес-логика, реальная авторизация. Всё это заменится после Ф14.

Готовы Ф1-Ф13 (см. список тасок). Остаётся Ф14 — заменить `core/stub_data.py` на реальные Django-модели.

## Технический стек

### Backend
- **Python** 3.13 (см. `.python-version`)
- **uv** — менеджер зависимостей (`pyproject.toml`, `uv.lock`, `.venv/`)
- **Django** 6.0.5
- **SQLite** (`db.sqlite3`) — заглушка, миграций по своим моделям пока нет
- Группы зависимостей: `dev` (django-debug-toolbar), `prod` (gunicorn)
- Команды: `uv run python manage.py runserver`, `uv run python manage.py test core`

### Frontend
- **Tailwind CSS v4** через npm-пакет `@tailwindcss/cli` (`package.json`)
- **Alpine.js 3.14.9** + **htmx 2.0.4** — self-hosted (`static/vendor/*.min.js`)
- **Self-hosted variable WOFF2 fonts** (`static/fonts/`): Montserrat (display), Open Sans (sans), Inter (ui), Georgia (serif — системный)
- Исходный CSS: `static_src/input.css` (содержит `@theme` с токенами, см. ниже)
- Скомпилированный CSS: `static/css/output.css`
- **Команды Tailwind запускает пользователь сам**:
  ```
  npm install      # один раз
  npm run dev      # watch
  npm run build    # production --minify
  ```

## Структура проекта

```
balaproza_v1/
├── config/                       # Django project (settings, urls)
├── core/
│   ├── stub_data.py              # ВСЕ «данные» проекта (Genre, Tag, Author, Story, Chapter,
│   │                             # Collection, Contest, Submission, LibraryEntry,
│   │                             # Notification, ReadingProgress, FOLLOWING, etc.)
│   │                             # Story.status дефолт = "NotPublished" (Draft) — см. BR-10
│   │                             # Story.tags: tuple = () — UGC-теги, до 10 (docs/11, BR-TAG-*)
│   │                             # Genre.icon — slug SVG-иконки для тайла жанра на главной
│   │                             # + helpers: my_stories_of, chapters_of, comments_of,
│   │                             # stories_by_genre, search_stories, search_authors,
│   │                             # related_stories, apply_catalog_filters, filter_catalog,
│   │                             # library_of, reader_stats, writer_stats, is_following,
│   │                             # following_of, followers_of, notifications_for_user,
│   │                             # unread_count_for_user, submissions_of, has_submission,
│   │                             # submission_checklist (BR-22), eligible_for_contest,
│   │                             # tag_by_slug, tags_of, is_blocked, popular_tags,
│   │                             # accepted_tags_json, blocked_tag_patterns_list
│   │                             # + константы: CATALOG_SORTS, CATALOG_STATUS_FILTERS,
│   │                             # TAGS, TAGS_BY_SLUG, BLOCKED_TAG_PATTERNS
│   ├── views.py                  # все view (тонкие, читают из stub_data)
│   │                             # + legal_* (5 stub-страниц), profile_me_edit (stub-форма),
│   │                             # search_index_json (lazy-fetch для popup, включает теги),
│   │                             # _render_catalog (общий движок DEC-27) + тонкие обёртки
│   │                             # search_results / catalog / genre_detail / tag_detail
│   ├── urls.py                   # все маршруты, app_name='core'
│   │                             # + /catalog/, /tag/<slug>/, /api/search-index.json,
│   │                             # /me/edit/, 5 legal routes
│   ├── context_processors.py     # auth_state, nav_state, site_links
│   ├── templatetags/balaproza.py # filter page_range (для pagination)
│   └── tests/                    # 315 тестов в 12 файлах (см. ниже)
├── templates/
│   ├── base.html                 # sprite + alpine/htmx defer + toast_host + search_popup +
│   │                             # favicon + theme-color + right_rail (опт., см. has_right_rail)
│   ├── 404.html / 500.html       # branded error pages (500 — standalone, без base.html)
│   ├── components/               # ~55 атомов и composites (см. docs/04)
│   │                             # включая cover_placeholder (двухрежимный: <img> если
│   │                             # story.cover задан, иначе типографическая плашка OKLCH +
│   │                             # буква по primary genre.hue),
│   │                             # avatar (буквенные инициалы + OKLCH-фон),
│   │                             # tag_chip / tag_list / tag_input (docs/11 — UGC-теги),
│   │                             # extras §4.10: skeleton_*, error_state, empty_state,
│   │                             # segmented_control, delete_confirm_modal, toast_host,
│   │                             # share_button, search_popup (Cmd+K — теги тоже в group),
│   │                             # chapter_like (FR-STORY-12), school_links.
│   │                             # NB: catalog_controls.html устарел — заменён
│   │                             # _filter_panel в каталоге (DEC-27)
│   ├── partials/                 # header, footer (карта сайта), mobile_nav, page_header,
│   │                             # right_rail/{home,story,writer,profile,contest,catalog}.html
│   │                             # home/*.html (hero_guest, hero_returning, book_of_week,
│   │                             # book_row, collections, new_authors, become_author,
│   │                             # contest_banner, genres_section),
│   │                             # catalog/_*.html (DEC-27): _book_list, _filter_panel,
│   │                             # _filter_sheet (mobile bottom-sheet), _hero_search,
│   │                             # _hero_genre, _hero_tag, _hero_catalog.
│   │                             # NB: sidebar.html удалён — DEC-25; genre_grid удалён —
│   │                             # жанры теперь отдельная секция (genres_section).
│   └── pages/                    # все страницы по модулям (home, auth, catalog, story,
│                                 # write, profile, library, notifications, contests, _design)
│                                 # + legal.html (универсальный шаблон для 5 правовых стабов)
│                                 # + profile/profile_me_edit.html
│                                 # NB: catalog/search_results.html и catalog/genre_detail.html
│                                 # удалены — один общий catalog.html обслуживает все режимы
│                                 # (search/genre/tag/catalog) — DEC-27
├── media/                       # фото-обложки произведений (placeholder из стороннего
│                                # источника, заменить перед публичным деплоем).
│                                # MEDIA_URL='/media/', MEDIA_ROOT=BASE_DIR/'media'
├── static/
│   ├── css/output.css            # Tailwind output (gitignored ИЛИ нет — спросить юзера)
│   ├── fonts/                    # 4 variable woff2
│   └── vendor/{alpine,htmx}.min.js
├── static_src/input.css          # Tailwind v4 @import + @theme c токенами
├── docs/                         # ТЗ модулями 00-11 (приоритет над прототипом)
├── package.json                  # @tailwindcss/cli + npm-скрипты dev/build
├── pyproject.toml + uv.lock
└── manage.py
```

## Дизайн-токены (в `static_src/input.css`, секция `@theme`)

- **Цвета**: `--color-brand` (бирюзовый), `--color-brand-dark`, slate-50…900, status-пары (`--color-status-published-bg`/`-fg`, и т.д. для `info`/`warning`/`attention`/`error`), `--color-notif`, `--color-promo-bg`/`-cta`, `--color-tg-1`/`-tg-2` (Telegram-градиент)
- **Шрифты**: `--font-display` (Montserrat), `--font-sans` (Open Sans), `--font-ui` (Inter), `--font-serif` (Georgia)
- **Радиусы**: `--radius-{xs(2),sm(4),chip(6),md(8),lg(12),hero(16),search(24),pill(9999)}`
- **Тени**: `--shadow-{card-hover,bottom-nav,tg-btn,modal}`
- **Цвета жанров** — OKLCH через inline-style `oklch(0.96 0.04 {{ hue }})` (см. `components/genre_chip.html`)

## Архитектурные решения (DEC из `docs/10`)

- **DEC-01**: Отдельной роли «Читатель» нет. Любой авторизованный пользователь автоматически Автор — доступ к чтению/лайкам/комментам/библиотеке и авторскому кабинету включён сразу после регистрации
- **DEC-15** (anti-tabs): псевдо-табы запрещены. Используем `components/segmented_control.html` (реальный `?tab=`) или scrollspy через IntersectionObserver
- **DEC-17** (loading/error): обязательны на всех data-зависимых страницах. См. компоненты `skeleton_*`, `error_state.html`, опт-ин `?state=loading|error` (work on home/library/notifications/my_stories). Showcase: `/_design/states/`
- **DEC-21**: AI-декларация в конкурсной подаче — обязательна (радио + расшифровка в `<details>`)
- **DEC-22**: «Авторлар мектебі» как страница исключена. Только блок ссылок (`components/school_links.html` в 3 layout: list/grid/inline). Финальное решение — в footer заголовок не кликабельный, ссылки inline
- **DEC-23**: Инструмент модерации = стандартный **Django admin** (кастомный UI отложен на V2). Story.status дефолт = `NotPublished` (Draft) — в публичный каталог попадает только после явной модерации
- **DEC-24**: Верификация возраста 14-18 = **самодекларация** (поле в регистрации + чекбокс в contest_submit). Никаких документов в MVP
- **DEC-25**: Левый sidebar на десктопе исключён. В хедере одна контент-ссылка («Байқаулар» — единственный раздел без альтернативного входа с главной), остальные разделы — секции главной и колонка «Контент» в footer. Личные разделы авторизованного — через avatar-dropdown. Правый рейл рендерится только если view передал `has_right_rail=True`. Контейнер `max-w-[1280px]`, правый рейл 300px (расширен с 234px ради осмысленных виджетов)
- **DEC-26**: Введена **UGC-таксономия тегов** параллельно жанрам. До 10 на произведение, free-form input. Новые попадают в `pending`, модератор переводит в `accepted` (через Django admin, BR-TAG-*). Часть паттернов в блок-листе — `is_blocked()`. Pending-теги скрыты от публики (BR-TAG-07). См. `docs/11`
- **DEC-27**: Каталог унифицирован — **один движок** `_render_catalog` обслуживает search/genre/tag/catalog. Canonical URLs сохранены (`/search/?q=`, `/genres/<slug>/`, `/tag/<slug>/`, `/catalog/`), комбинации через query (`/genres/triller/?tag=mektep`). Общий filter_panel в правом рейле / mobile bottom-sheet. **Коллекции (Жинақтар) НЕ объединены** — это editorial curation, отдельный content type

## Стаб-авторизация

- `core.views.login_view` ставит `session['signed_in']`, `user_name`, `user_username` (по умолчанию `aidana`)
- Контекст-процессор `auth_state` отдаёт в шаблоны: `signed_in`, `current_user_name`, `current_user_username`, `unread_notifications` (читает из `stub_data.unread_count_for_user`)
- Контекст-процессор `site_links` отдаёт `school_links_global` глобально (для footer)
- Защита от open-redirect: `_safe_next(request)` принимает только относительные пути (отвергает `//evil.com/`)
- Логин по 4-ой пользователю `aidana` — он же автор 4 стори с разными статусами для теста WRITE/PROF/LIB

## Тестирование

```
uv run python manage.py test core       # все 315 тестов
uv run python manage.py test core.tests.test_<file>
```

Тесты в `core/tests/`:
- `test_urls_smoke.py` — все маршруты в guest/auth + DEBUG-only design URLs
- `test_auth.py`, `test_context.py`, `test_filters.py`, `test_stub_data.py`
- `test_home.py`, `test_story.py`, `test_catalog.py`, `test_write.py`
- `test_prof_lib_notif.py`, `test_contests.py`, `test_auth_links.py`, `test_states.py`

Логин в тестах:
```python
def _login_as_aidana(client):
    s = client.session
    s['signed_in'] = True
    s['user_name'] = 'Айдана'
    s['user_username'] = 'aidana'
    s.save()
```

## Шаблоны

- **Все шаблоны в корневой `templates/`** (не в `core/templates/`)
- `base.html` определяет блоки `title`, `content`, `right_rail` — каждая страница может переопределить рейл
- `base.html` глобально подключает: sprite, alpine/htmx, toast_host, **search_popup** (Cmd+K), favicon, theme-color
- **`has_right_rail` флаг** (DEC-25): `<aside>` правого рейла рендерится только если view передал `'has_right_rail': True` в контекст. Иначе контент тянется на всю ширину контейнера. См. `home`, `story_detail`, `profile_me/other`, `contest_detail/submit`, `manage_story`, `chapter_editor`, `my_stories`, `new_story`, `story_settings`
- **Container**: `max-w-[1280px]` (после удаления sidebar) с padding `lg:px-12`
- В компонентах используем `{% comment %}…{% endcomment %}` для документации параметров (НЕ многострочный `{# … #}` — Django парсит его как single-line)
- В именах template-переменных нельзя начинать с `_` (Django блокирует) — использовать `rid`, `id` и т.п.

### Глобальные Alpine-события (window dispatch)
- `toast` — `{kind: 'success'|'info'|'warning'|'error', text: '...'}` → показывает тост
- `open-search` — открывает search_popup (Cmd+K). Используется в кнопках поиска header
- `open-report` — открывает report_modal с целью `{target: 'story:slug'}`
- `open-catalog-filters` — открывает mobile bottom-sheet с фильтр-панелью каталога (DEC-27)
- `open-delete-confirm` — открывает delete_confirm_modal с целью `{name, confirm_url}`

### Mobile bottom nav (5 слотов)
- **Гость:** Басты / Оқу (catalog) / **Іздеу (FAB)** / Байқау / Кіру
- **Авторизованный:** Басты / Кітапхана / **Жазу (FAB)** / Байқау / Профиль
- У всех пунктов, кроме FAB, есть видимая подпись 10px — иконки без подписей опираются на неочевидные метафоры. У FAB подписи нет, только `aria-label`.
- Гостевой FAB — поиск (открывает quick-search popup, href на `/search/` как no-JS fallback). Логин в FAB не ставить: самый заметный слот не должен требовать регистрации до получения ценности.
- Конкурсы — иконка `trophy` (как в хедере), не `adjustments`.
- Notifications у авторизованных — в хедере (колокольчик с бейджем), в нижнее меню не выносим. Library и my_submissions доступны через avatar-dropdown в хедере (на десктопе) и через profile (на mobile). Sidebar исключён — DEC-25.

## Стилистические правила для шаблонов

- **Радиусы — только токены**: `rounded-{xs,sm,chip,md,lg,hero,search,pill}`. НЕ `rounded-2xl`/`3xl`/etc.
- **Произвольные значения** — через arbitrary syntax: `h-[26px]` (не `h-6.5`), `px-[52px]` (не `px-13`), `bg-white/10` (не `bg-white/8`)
- **Иконки** — только через `components/icon.html` + спрайт (`templates/components/icons/_sprite.html`). Если нужной иконки нет — добавить новый `<symbol>` в спрайт
- **Эмодзи запрещены** в шаблонах, stub_data и любом контенте проекта. Стандартные emoji-символы (☀️ 📖 😢 🎒 👽 🌆 🇰🇿 🕯️ ✍️ 🎄 🧟 😄 и т.п.) выглядят дёшево и роняют уровень дизайна. Альтернативы: SVG-иконка через `components/icon.html`, типографический акцент (крупная буква), абстрактный геометрический паттерн OKLCH, либо ничего. Это правило касается и текстового контента — приветствий, заголовков, описаний
- **Обложки произведений** — `components/cover_placeholder.html` (двухрежимный): если `story.cover` непустой → рендерит `<img src="/media/{cover}">` с object-cover; иначе — типографическая плашка OKLCH + буква + «корешок» по hue primary жанра. Не использовать `{% static story.cover %}` напрямую — путь к файлу инкапсулирован в компоненте
- **Аватары** — `components/avatar.html` (буквенные инициалы на OKLCH-фоне по длине seed=username+name). Передавать `username` для стабильного цвета
- **Статусы произведения** — только через `components/status_badge.html` с key из 5: `Published|NotPublished|OnProcess|Completed|OnModeration` (BR-10/11)
- **Жанры** — только через `components/genre_chip.html` (DEC-14: `GenrePill` запрещён). У жанра есть `icon` (slug из спрайта) — используется в `genres_section` на главной для тайла «книжной полки»
- **Теги (UGC)** — `components/tag_chip.html` (slate-style + `#`-префикс, отличается от цветного `genre_chip`). Pending-теги автоматически с пунктирной рамкой + бейдж «проверкада». Группа тегов на стори — через `components/tag_list.html` (фильтрует pending для не-автора, BR-TAG-07). Ввод тегов в формах — `components/tag_input.html` (Alpine, автокомплит, лимит 10, blocklist-валидация)
- **Внешние ссылки** — `target="_blank" rel="noopener noreferrer"` (FR-LINKS-03)
- **Абсолютное позиционирование внутри горизонтальных скроллеров — только с `relative`-предком.** В рядах вида `overflow-x-auto` + `flex w-max` (book_row, new_authors, любые карусели) каждая карточка обязана иметь `relative`. Иначе у любого потомка с `position:absolute` — включая **`sr-only`** (это `position:absolute` + `clip-path`), `absolute inset-y-0`, бейджи, оверлеи — containing block становится initial containing block. Такой элемент **не клипается скроллером** и уезжает в координаты документа на всю ширину ряда (в реальном баге — до x≈653 при вьюпорте 376).

  Симптом на мобильном: `html.scrollWidth` сильно больше `clientWidth`, при этом `body.scrollWidth` в норме — верный признак именно этой ошибки. Chrome пересчитывает page-scale, ICB для `position:fixed` раздувается (653×1413 вместо 376×812), и **всё фиксированное улетает за экран**: mobile bottom nav, `toast_host`, `search_popup`, `delete_confirm_modal`, mobile-фильтры каталога. Страница при этом выглядит «почти нормально» — просто без нижнего меню, поэтому баг легко пропустить.

  Проверка в консоли на 375px:
  ```js
  document.documentElement.scrollWidth === document.documentElement.clientWidth
  ```
  Если `false`, а `body.scrollWidth` совпадает с `clientWidth` — ищи абсолютный элемент без позиционированного предка.
- **`{% include … with … %}` — ВСЕГДА в одну строку.** Django не парсит перенос строк внутри тега и выводит конструкцию как plain-текст. Если параметров много — пиши длинную строку, не разбивай:
  ```django
  {# ❌ ЛОМАЕТСЯ — рендерится как текст #}
  {% include "components/comment.html" with
      author_name=cm.author.name
      text=cm.text %}
  {# ✅ Правильно — в одну строку #}
  {% include "components/comment.html" with author_name=cm.author.name text=cm.text %}
  ```
  То же правило для других тегов: `{% url %}`, `{% if %}` — без переносов внутри.

## Что НЕ делать

- **НЕ создавать** модели/миграции/реальные формы/сервисы/view с бизнес-логикой
- **НЕ запускать** `npm run dev`/`npm run build` — пользователь сам
- **НЕ запускать** `python manage.py runserver` для smoke-проверок — пользователь поднимает дев-сервер сам в своём терминале
- **НЕ коммитить** `node_modules/`, `.venv/`, `__pycache__/`, скомпилированный `static/css/*.css` без явной просьбы
- **НЕ использовать** `tailwind.config.js` — это Tailwind v4, всё в `@theme` внутри `input.css`
- **НЕ обходить** хуки (`--no-verify`) или верификацию подписи в git
