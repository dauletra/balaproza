# Qazaqnovel

Казахоязычный детский литературный портал. Django 6 + PostgreSQL + Tailwind CSS v4
+ Alpine.js + htmx.

Портал читает и пишет базу на всех путях. Требования и решения — в
[`docs/`](docs/), заметки для разработки — в [`CLAUDE.md`](CLAUDE.md).

## Откуда берутся данные

**Из базы.** Страницы ходят в Postgres через фасад [`core/data.py`](core/data.py):
правила предметной области — из [`core/domain/`](core/domain/), записи — из
[`core/queries/`](core/queries/).

Демо-содержимое кладёт идемпотентная команда `seed_demo`; её литералы лежат рядом
с ней ([`_corpus.py`](core/management/commands/_corpus.py)) и читаются только ею.
Тексты глав — файлами в [`core/story_texts/`](core/story_texts/). 12 жанров и
блок-лист тегов заливает миграция `0002`: они часть системы, а не контент.

## Установка на новой машине

Нужны [uv](https://docs.astral.sh/uv/), Node.js 20+ и PostgreSQL 14+.

```bash
git clone https://github.com/dauletra/qazaqnovel.git
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
uv run python manage.py seed_demo
```

```bash
uv run python manage.py runserver
```

Повтор `seed_demo` не удваивает корпус и возвращает изменённые записи к эталону.
Поэтому команда, а не фикстура: даты идущих конкурсов заданы относительно
сегодняшнего дня, и застывший JSON через месяц перевёл бы конкурс в другую фазу.

## Что не переезжает через git

| Что | Почему | Как восстановить |
|---|---|---|
| `media/` — обложки, афиши, эмблемы наград | в `.gitignore` | Скопировать вручную. Без неё рисуется типографическая плашка OKLCH — страницы не ломаются |
| `static/css/output.css` | пересобираемый артефакт | `npm run build` |
| `.env` | там пароль к БД | `cp .env.example .env` |
| Суперюзер Django admin | живёт в локальной БД | `manage.py createsuperuser` |
| `.venv/`, `node_modules/` | gitignored | `uv sync`, `npm install` |

## Ежедневная работа

```bash
npm run dev
```

Watch-режим Tailwind: пересобирает `static/css/output.css` при правках шаблонов и
`static_src/input.css`. Держать в отдельном терминале рядом с `runserver`.

## Тесты

```bash
uv run python manage.py test core
```

Прогон идёт в четыре процесса, корпус кладётся в базу один раз и приезжает в
каждый клон готовым. Отдельный файл — `test core.tests.test_catalog`,
последовательно — `--parallel 1` (нужен для `--pdb`), быстрый круг без
пересоздания баз — `--keepdb`.

## Вход

Сессию держит `django.contrib.auth`. Провайдер личности — Telegram Login
Widget с проверкой подписи: кнопка ведёт на Telegram, тот
подписывает данные и редиректит браузер на наш callback.

Виджет не рисуется без домена, зарегистрированного за ботом через
`@BotFather` — **на localhost напрямую он не работает даже в разработке**,
нужен туннель (ngrok/cloudflared) с доменом, прописанным боту через
`/setdomain`. Порядок: `@BotFather` → `/newbot` → имя и `@username` бота →
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_BOT_USERNAME` в `.env` → `/setdomain` на
адрес туннеля (для прода — на прод-домен, и тогда переустанавливать при
каждом запуске не надо).

## Деплой и эксплуатация

Окружение, безопасность, потолок запросов на прокси, статика и media,
процедура деплоя, расписание, бэкап и восстановление, чек-лист перед
публичным запуском — в [`docs/deploy.md`](docs/deploy.md). Настройка
самого сервера (Ubuntu, systemd, nginx) и готовые скрипты —
[`docs/vps-setup.md`](docs/vps-setup.md) и [`ops/`](ops/). Здесь их нет
намеренно: три четверти README читал тот, кто ставит проект себе на
машину и до nginx с gpg не доберётся никогда.

Что осталось до открытия адреса и делается не кодом — в
[`LAUNCH.md`](LAUNCH.md).
