# CLAUDE.md

Заметки по проекту `balaproza_v1` — казахоязычный литературный портал Balaproza.
Требования и решения — в [`docs/`](docs/): [архитектура](docs/architecture.md),
[требования](docs/spec.md), [интерфейс](docs/ui.md),
[реестр решений DEC](docs/10-resolved-decisions.md).

## Текущий фокус

**Идёт оптимизация кодовой базы — план и статус шагов в
[`PLAN-OPTIMIZATION.md`](PLAN-OPTIMIZATION.md).** При расхождении с правилами ниже
план сильнее: он меняет слой данных (QuerySet вместо list), вводит Django-формы
и декораторы, разгружает модели.

Ф1–Ф15 закрыты: портал отвечает из PostgreSQL, вход настоящий
(`django.contrib.auth`), запись работает на всех путях — произведения и главы,
теги, модерация, комментарии и их лайки, реакции, опрос, подача на конкурс и её
отзыв, профиль, библиотека, подписки, уведомления, счётчик оқылым.

Впереди: Telegram Login Widget с проверкой подписи (NFR-25 ⛔ — до него публичный
запуск небезопасен), автосохранение черновика по debounce, убыль `recent_views`.

## Стек и команды

Python 3.13 · uv · Django 6.0.5 · PostgreSQL (`DATABASE_URL` в `.env`, образец —
`.env.example`; роли нужен `CREATEDB` для тестов) · Tailwind CSS v4 через
`@tailwindcss/cli` · Alpine.js 3 и htmx 2 self-hosted.

```
uv run python manage.py runserver
uv run python manage.py test core          # вся суита, в четыре процесса
uv run python manage.py test core --keepdb # быстрый круг
uv run python manage.py seed_demo          # демо-корпус, идемпотентно
```

**Команды Tailwind (`npm run dev` / `npm run build`) и `runserver` запускает
пользователь сам** — не запускать их для смоук-проверок.

## Структура

```
core/
├── domain/        правила: константы и чистые функции (каталог, story, contests,
│                  awards, notifications, formatting). Хранилища не знает
├── managers.py    выдача: StoryQuerySet и ContestQuerySet — публичность, состав
│                  карточки, объём чтения, оси каталога, фазы конкурса
├── queries/       записи: catalog, story, author, profile, contests, tags,
│                  library, site, write
├── data.py        ФАСАД — единственная дверь к данным для views, контекст-
│                  процессоров и фильтров
├── links.py       «данные + URL»: CatalogState, CATALOG_AXES (один список осей
│                  на проект), сборка ссылок каталога, кабинета, уведомлений
├── models.py      поля, Meta, инварианты, мутации. Story.apply_moderation —
│                  статус и уведомление одним движением (BR-11)
├── views/         модуль на раздел, имена собраны в __init__
├── admin.py       инструмент модерации (DEC-23): решение принимается ДЕЙСТВИЕМ
│                  (approve / send_back / reject), а не правкой поля статуса
├── management/commands/  seed_demo + _corpus.py (демо-содержимое литералами)
└── tests/         12 файлов; base.py (login_as), factories.py, runner.py
templates/         base.html, components/, partials/, pages/ — всё в корневой
static_src/input.css   @theme с токенами
media/             обложки, афиши, эмблемы наград (в .gitignore целиком)
```

## Инварианты

- **`core/domain` не импортирует модели, `core.data` и корпус** — иначе цикл и
  константы не взять в миграцию.
- **Читать и писать — только через `core.data`.** Views в модели не пишут.
- **Слой данных принимает пользователя, а не ник**, и отдаёт QuerySet, а не
  список: `None` значит «гость», а материализованный список платит запросом даже
  за то, чего страница не покажет. Снимок работ автора живёт на самом объекте
  (`User.authored` и соседние `cached_property`).
- **`_corpus.py` читает только `seed_demo`.**
- **URL не спускаются в слой данных и не собираются в шаблоне** — их строит
  `links.py`.
- **Публичность — `data.PUBLIC_STATUSES`, а не литерал `'Published'`** (DEC-37):
  по литералу из выдачи молча пропадают все сериалы.
- **Производное не хранится** (число частей, счётчики тега, фаза конкурса, знаки
  автора). Исключения — акты с датой и автором (`AwardGrant`,
  `Notification.outcome`) и колонки под `ORDER BY`/`WHERE` (`Story.likes`,
  `User.followers`), которые пересчитываются по строкам, а не сдвигаются.
- **Новой странице заводится бюджет в `test_query_budget`** — он один ловит N+1
  при полностью зелёной суите.
- **`{% include … with … %}` — всегда в одну строку**, иначе Django выведет тег
  текстом. То же для `{% url %}` и `{% if %}`; многострочный `{# … #}` — тоже.
- **`@click`/`@submit` требуют `x-data` в предках**, иначе директива мёртвая без
  ошибки в консоли. Лечение — пустой `x-data` на самом элементе.
- **`{% include "components/icon.html" … only %}`** — без `only` подпись кнопки
  утекает в иконку и читается скринридером дважды.
- **`aria-label` на `<span>`/`<div>` без `role` не озвучивается** — подпись идёт
  `<span class="sr-only">`, элемент под `aria-hidden`.
- **Абсолютное позиционирование внутри горизонтального скроллера — только с
  `relative`-предком**, иначе всё фиксированное улетает за экран.
- **Эмодзи запрещены** в шаблонах, корпусе и текстах — кроме UGC.
- Обложка — `cover_placeholder.html`, статус — `status_badge.html`, жанр —
  `genre_chip.html`, награда — `award.html`, реакции — `reaction_bar.html`.
  Числа: `compact_count` читателю, `spaced` автору; `stringformat` в позиции
  метрики запрещён.

Полные правила интерфейса и тона — [`docs/ui.md`](docs/ui.md).

## Документация

**Изменение, затрагивающее FR / BR / DEC, правит `docs/` тем же коммитом.**
Решение не правится — оно отменяется новым DEC со ссылкой «отменяет DEC-NN».
Невыполненное помечается ⛔ с объяснением. Номера не переиспользуются.

## Что НЕ делать

- НЕ коммитить `node_modules/`, `.venv/`, `__pycache__/`, `static/css/*.css` без
  просьбы.
- НЕ заводить `tailwind.config.js` — это v4, всё в `@theme`.
- НЕ обходить хуки (`--no-verify`) и верификацию подписи в git.
