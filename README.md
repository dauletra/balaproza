# Balaproza

Казахоязычный детский литературный портал. Django 6 + Tailwind CSS v4 + Alpine.js + htmx.

Текущий этап — дизайн-система (вёрстка, токены, компоненты, шаблоны) на стаб-данных.
Реальные модели БД появятся на Ф14. Подробное ТЗ — в [`docs/`](docs/) (модули 00-18),
заметки для разработки — в [`CLAUDE.md`](CLAUDE.md).

## Откуда берутся данные

**Контента в базе нет.** Всё, что рендерится на страницах, — Python-литералы:

- [`core/stub_data.py`](core/stub_data.py) — Genre, Tag, Author, Story, Chapter, Collection,
  Contest, Submission, LibraryEntry, Notification и хелперы к ним;
- [`core/story_texts/`](core/story_texts/) — тексты глав (`.txt`, по одному файлу на главу).

Оба лежат в git, поэтому данные переезжают между машинами как обычный код —
дампы, фикстуры и seed-команды не нужны.

`db.sqlite3` держит только служебные таблицы Django (`django_session`, `auth_user`,
`django_content_type`, `django_admin_log`). Она в `.gitignore` и не пушится:
терять там нечего, `migrate` создаёт её заново за секунду.

## Установка на новой машине

Нужны [uv](https://docs.astral.sh/uv/) и Node.js 20+.

```bash
git clone https://github.com/dauletra/balaproza.git
```

```bash
uv sync
```

```bash
npm install && npm run build
```

```bash
uv run python manage.py migrate
```

```bash
uv run python manage.py runserver
```

`migrate` обязателен, хотя контент от базы не зависит: стаб-логин пишет в сессию,
и без таблицы `django_session` вход упадёт.

## Что не переезжает через git

| Что | Почему | Как восстановить |
|---|---|---|
| `media/` — фото-обложки произведений | `/media/` в `.gitignore` | Скопировать папку вручную. Без неё `components/cover_placeholder.html` рисует типографическую плашку OKLCH — страницы не ломаются, но фото-обложек не будет |
| `static/css/output.css` | gitignored, пересобираемый артефакт | `npm run build` |
| Суперюзер Django admin | жил в локальной sqlite | `uv run python manage.py createsuperuser` |
| `.venv/`, `node_modules/` | gitignored | `uv sync`, `npm install` |

## Ежедневная работа

```bash
npm run dev
```

Watch-режим Tailwind: пересобирает `static/css/output.css` при правках шаблонов
и `static_src/input.css`. Держать в отдельном терминале рядом с `runserver`.

## Тесты

```bash
uv run python manage.py test core
```

876 тестов в 16 файлах (`core/tests/`). Отдельный файл:

```bash
uv run python manage.py test core.tests.test_catalog
```

## Стаб-авторизация

Логина по паролю нет. `core.views.login_view` просто ставит в сессию
`signed_in`, `user_name`, `user_username` (по умолчанию `aidana`).
У этого пользователя есть 4 произведения с разными статусами — на них
удобно смотреть авторский кабинет, профиль и библиотеку.

## После Ф14

Когда `stub_data.py` заменится реальными моделями, наполнение перестанет ехать
вместе с кодом и понадобится сид. План — management-команда `seed_demo`,
которая читает те же структуры и раскладывает их по моделям идемпотентно:
версионируется как код и переживает изменения схемы, в отличие от фикстур.
