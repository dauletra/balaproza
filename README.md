# Balaproza

Казахоязычный детский литературный портал. Django 6 + Tailwind CSS v4 + Alpine.js + htmx.

Дизайн-система (вёрстка, токены, компоненты, шаблоны) готова и работает на стаб-данных.
Идёт Ф14 — замена стаба на модели БД, план по этапам в [`docs/19`](docs/19-f14-migration-plan.md).
Подробное ТЗ — в [`docs/`](docs/) (модули 00-19), заметки для разработки — в [`CLAUDE.md`](CLAUDE.md).

## Откуда берутся данные

**Контента в базе нет.** Всё, что рендерится на страницах, — Python-литералы:

- [`core/stub_data.py`](core/stub_data.py) — Genre, Tag, Author, Story, Chapter, Collection,
  Contest, Submission, LibraryEntry, Notification и хелперы к ним;
- [`core/story_texts/`](core/story_texts/) — тексты глав (`.txt`, по одному файлу на главу).

Страницы обращаются не туда напрямую, а к фасаду [`core/data.py`](core/data.py):
на Ф14 источник меняется, а вызовы во views — нет. Правила предметной области
(оси каталога, реакции, подписи статусов, формулировки времени) лежат отдельно
в [`core/domain/`](core/domain/) — они переживут замену хранилища.

Оба лежат в git, поэтому данные переезжают между машинами как обычный код —
дампы, фикстуры и seed-команды не нужны.

В базе — служебные таблицы Django, `core_user` и справочники: 12 жанров
и блок-лист тегов заливает миграция (они часть системы, а не контент).
Остальное `migrate` создаёт заново за секунду — терять там пока нечего.

## Установка на новой машине

Нужны [uv](https://docs.astral.sh/uv/), Node.js 20+ и PostgreSQL 14+.

```bash
git clone https://github.com/dauletra/balaproza.git
```

```bash
uv sync
```

```bash
npm install && npm run build
```

Роль и база создаются один раз. `CREATEDB` нужен не для сайта, а для тестов:
Django поднимает отдельную `test_<имя>` и сносит её после прогона.

```bash
psql -U postgres -c "CREATE ROLE qnovel_user LOGIN PASSWORD 'сюда-пароль' CREATEDB;"
```

```bash
psql -U postgres -c "CREATE DATABASE qnovel_db OWNER qnovel_user;"
```

Дальше — окружение. `.env` в `.gitignore`, в git лежит только образец:

```bash
cp .env.example .env
```

В нём обязателен один ключ — `DATABASE_URL`. Без него настройки падают
с `ImproperlyConfigured`, а не молча поднимаются на пустой базе.

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
| `.env` | gitignored, там пароль к БД | `cp .env.example .env` и подставить свои значения |
| Суперюзер Django admin | живёт в локальной БД | `uv run python manage.py createsuperuser` |
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

1037 тестов в 19 файлах (`core/tests/`). Отдельный файл:

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
