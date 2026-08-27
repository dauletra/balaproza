# Balaproza

Казахоязычный детский литературный портал. Django 6 + Tailwind CSS v4 + Alpine.js + htmx.

Дизайн-система (вёрстка, токены, компоненты, шаблоны) готова и работает на стаб-данных.
Ф14 (замена стаба на модели БД) завершена — план по этапам в [`docs/19`](docs/19-f14-migration-plan.md).
Идёт Ф15 — запись (формы создания/редактирования, комментарии, реакции, подача на конкурс, профиль), план в [`docs/20`](docs/20-f15-write-plan.md).
Подробное ТЗ — в [`docs/`](docs/) (модули 00-20), заметки для разработки — в [`CLAUDE.md`](CLAUDE.md).

## Откуда берутся данные

**Из базы.** Страницы читают Postgres через фасад [`core/data.py`](core/data.py):
правила предметной области (оси каталога, реакции, подписи статусов, формулировки
времени) — из [`core/domain/`](core/domain/), записи — из [`core/queries/`](core/queries/).
Фасад заведён ради этой замены и пережил её: вызовы во views не изменились.

Демо-содержимое кладёт в базу идемпотентная команда `seed_demo`; её литералы
лежат рядом с ней ([`core/management/commands/_corpus.py`](core/management/commands/_corpus.py))
и читаются только ею. Тексты глав — файлами в
[`core/story_texts/`](core/story_texts/) (`.txt`, по одному файлу на главу).

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

1159 тестов в 25 файлах (`core/tests/`). Отдельный файл:

```bash
uv run python manage.py test core.tests.test_catalog
```

Прогон идёт в четыре процесса, корпус кладётся в базу один раз и приезжает
в каждый клон готовым. Последовательно — `--parallel 1` (нужен для `--pdb`),
быстрый круг без пересоздания баз — `--keepdb`.

## Стаб-авторизация

Логина по паролю нет. `core.views.login_view` просто ставит в сессию
`signed_in`, `user_name`, `user_username` (по умолчанию `aidana`).
У этого пользователя есть 4 произведения с разными статусами — на них
удобно смотреть авторский кабинет, профиль и библиотеку.

## Наполнить базу

```
uv run python manage.py migrate
uv run python manage.py seed_demo
```

Команда идемпотентна: её запускают на пустой базе, поверх засеянной и после
смены схемы. Повтор не удваивает корпус и возвращает изменённые записи к
эталону. Даты идущих конкурсов заданы относительно сегодняшнего дня — поэтому
команда, а не фикстура: застывший JSON через месяц перевёл бы конкурс в другую
фазу (DEC-45).
