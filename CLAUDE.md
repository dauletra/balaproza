# CLAUDE.md

Заметки для Claude Code по проекту `balaproza_v1`. Платформа — Balaproza, казахоязычный детский литературный портал. Подробное ТЗ — в [`docs/`](docs/) (модули 01-10).

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
│   ├── stub_data.py              # ВСЕ «данные» проекта (Genre, Author, Story, Chapter,
│   │                             # Collection, Contest, Submission, LibraryEntry,
│   │                             # Notification, ReadingProgress, FOLLOWING, etc.)
│   │                             # Story.status дефолт = "NotPublished" (Draft) — см. BR-10
│   │                             # + helpers: my_stories_of, chapters_of, comments_of,
│   │                             # stories_by_genre, search_stories, search_authors,
│   │                             # related_stories, apply_catalog_filters, library_of,
│   │                             # reader_stats, writer_stats, is_following,
│   │                             # following_of, followers_of, notifications_for_user,
│   │                             # unread_count_for_user, submissions_of, has_submission,
│   │                             # submission_checklist (BR-22), eligible_for_contest
│   │                             # + константы: CATALOG_SORTS, CATALOG_STATUS_FILTERS
│   ├── views.py                  # все view (тонкие, читают из stub_data)
│   │                             # + legal_* (5 stub-страниц), profile_me_edit (stub-форма),
│   │                             # search_index_json (lazy-fetch для popup)
│   ├── urls.py                   # все маршруты, app_name='core'
│   │                             # + /api/search-index.json, /me/edit/, 5 legal routes
│   ├── context_processors.py     # auth_state, nav_state, site_links
│   ├── templatetags/balaproza.py # filter page_range (для pagination)
│   └── tests/                    # 280 тестов в 12 файлах (см. ниже)
├── templates/
│   ├── base.html                 # sprite + alpine/htmx defer + toast_host + search_popup +
│   │                             # favicon + theme-color + right_rail block
│   ├── 404.html / 500.html       # branded error pages (500 — standalone, без base.html)
│   ├── components/               # ~50 атомов и composites (см. docs/04)
│   │                             # включая extras §4.10: skeleton_*, error_state, empty_state,
│   │                             # segmented_control, delete_confirm_modal, toast_host,
│   │                             # share_button, search_popup (Cmd+K), catalog_controls,
│   │                             # chapter_like (лайк на главу — FR-STORY-12), school_links
│   ├── partials/                 # header, sidebar, footer, mobile_nav, page_header,
│   │                             # right_rail/{home,story,writer,profile,contest}.html,
│   │                             # home/*.html (hero_guest, hero_returning, genre_grid,
│   │                             # book_of_week, book_row, collections, new_authors,
│   │                             # become_author)
│   └── pages/                    # все страницы по модулям (home, auth, catalog, story,
│                                 # write, profile, library, notifications, contests, _design)
│                                 # + legal.html (универсальный шаблон для 5 правовых стабов)
│                                 # + profile/profile_me_edit.html
├── static/
│   ├── css/output.css            # Tailwind output (gitignored ИЛИ нет — спросить юзера)
│   ├── fonts/                    # 4 variable woff2
│   └── vendor/{alpine,htmx}.min.js
├── static_src/input.css          # Tailwind v4 @import + @theme c токенами
├── docs/                         # ТЗ модулями 00-10 (приоритет над прототипом)
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

- **DEC-15** (anti-tabs): псевдо-табы запрещены. Используем `components/segmented_control.html` (реальный `?tab=`) или scrollspy через IntersectionObserver
- **DEC-17** (loading/error): обязательны на всех data-зависимых страницах. См. компоненты `skeleton_*`, `error_state.html`, опт-ин `?state=loading|error` (work on home/library/notifications/my_stories). Showcase: `/_design/states/`
- **DEC-21**: AI-декларация в конкурсной подаче — обязательна (радио + расшифровка в `<details>`)
- **DEC-22**: «Авторлар мектебі» как страница исключена. Только блок ссылок (`components/school_links.html` в 3 layout: list/grid/inline). Финальное решение — в footer заголовок не кликабельный, ссылки inline
- **DEC-23**: Инструмент модерации = стандартный **Django admin** (кастомный UI отложен на V2). Story.status дефолт = `NotPublished` (Draft) — в публичный каталог попадает только после явной модерации
- **DEC-24**: Верификация возраста 14-18 = **самодекларация** (поле в регистрации + чекбокс в contest_submit). Никаких документов в MVP

## Стаб-авторизация

- `core.views.login_view` ставит `session['signed_in']`, `user_name`, `user_username` (по умолчанию `aidana`)
- Контекст-процессор `auth_state` отдаёт в шаблоны: `signed_in`, `current_user_name`, `current_user_username`, `unread_notifications` (читает из `stub_data.unread_count_for_user`)
- Контекст-процессор `site_links` отдаёт `school_links_global` глобально (для footer)
- Защита от open-redirect: `_safe_next(request)` принимает только относительные пути (отвергает `//evil.com/`)
- Логин по 4-ой пользователю `aidana` — он же автор 4 стори с разными статусами для теста WRITE/PROF/LIB

## Тестирование

```
uv run python manage.py test core       # все 280 тестов
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
- В компонентах используем `{% comment %}…{% endcomment %}` для документации параметров (НЕ многострочный `{# … #}` — Django парсит его как single-line)
- В именах template-переменных нельзя начинать с `_` (Django блокирует) — использовать `rid`, `id` и т.п.

### Глобальные Alpine-события (window dispatch)
- `toast` — `{kind: 'success'|'info'|'warning'|'error', text: '...'}` → показывает тост
- `open-search` — открывает search_popup (Cmd+K). Используется в кнопках поиска header
- `open-report` — открывает report_modal с целью `{target: 'story:slug'}`

### Mobile bottom nav (5 слотов)
- **Гость:** home / genres / login (FAB) / contests / search
- **Авторизованный:** home / **contests** / new_story (FAB) / notifications / profile
- Library и my_submissions у авторизованных доступны через dropdown header и desktop sidebar (не в bottom nav)

## Стилистические правила для шаблонов

- **Радиусы — только токены**: `rounded-{xs,sm,chip,md,lg,hero,search,pill}`. НЕ `rounded-2xl`/`3xl`/etc.
- **Произвольные значения** — через arbitrary syntax: `h-[26px]` (не `h-6.5`), `px-[52px]` (не `px-13`), `bg-white/10` (не `bg-white/8`)
- **Иконки** — только через `components/icon.html` + спрайт (`templates/components/icons/_sprite.html`)
- **Статусы произведения** — только через `components/status_badge.html` с key из 5: `Published|NotPublished|OnProcess|Completed|OnModeration` (BR-10/11)
- **Жанры** — только через `components/genre_chip.html` (DEC-14: `GenrePill` запрещён)
- **Внешние ссылки** — `target="_blank" rel="noopener noreferrer"` (FR-LINKS-03)
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
