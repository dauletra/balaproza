# Balaproza

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
uv run python manage.py seed_demo
```

```bash
uv run python manage.py runserver
```

Повтор `seed_demo` не удваивает корпус и возвращает изменённые записи к эталону.
Поэтому команда, а не фикстура: даты идущих конкурсов заданы относительно
сегодняшнего дня, и застывший JSON через месяц перевёл бы конкурс в другую фазу
(DEC-45).

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

Сессию держит `django.contrib.auth`. ⛔ **Провайдера личности пока нет:** Telegram
Login Widget с проверкой подписи (NFR-25) заводится при деплое, а до тех пор
`login_view` подписывает в демо-аккаунт `aidana` — автора четырёх работ с разными
статусами, на которых удобно смотреть кабинет, профиль и библиотеку.

---

# Деплой

> Проект в production не разворачивался. Ниже — порядок первого деплоя.

## Окружение

Прод включается **одной переменной** — `DJANGO_ENV=production`. Она выключает
`DEBUG`, включает https-редирект, HSTS, secure-куки и `CSRF_TRUSTED_ORIGINS`,
подключает whitenoise (если установлен) и делает `SECRET_KEY` с
`DJANGO_ALLOWED_HOSTS` обязательными: без любой из них запуск падает с
объяснением. Раньше прод отличался тремя независимыми переменными, и любая
забытая давала «почти прод» — трейсбэки на странице или ключ подписи сессий из
репозитория.

`DEBUG_TOOLBAR=0` выключает панель, не трогая `DEBUG`. Значения, различающиеся
между машинами, читаются из окружения — `.env` или менеджер процессов, код читает
и то и другое одинаково.

Ключ из git считается скомпрометированным: в проде генерируется свой. Логирование
пока не настроено — при `DEBUG=False` ошибки уйдут в никуда, минимум это
`LOGGING` с выводом в stdout.

## Зависимости

Группы объявлены в `pyproject.toml`: основная (`django`, `psycopg[binary]`,
`dj-database-url`, `python-dotenv`), `dev` (django-debug-toolbar), `prod`
(gunicorn, whitenoise). На сервере — `uv sync --no-dev --group prod`. Node нужен
только на сборке CSS: в рантайме `output.css` — статический файл.

## Безопасность (NFR-65)

Платформа для детей — эти настройки не опциональны:

```python
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
```

За обратным прокси обязателен
`SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')` — иначе
`SECURE_SSL_REDIRECT` уйдёт в бесконечный редирект.

Проект self-hosted целиком, внешних CDN нет — жёсткий CSP стоит выставить на
уровне веб-сервера при первом деплое. Единственный источник инлайн-стилей —
OKLCH-цвета жанров, поэтому `style-src` потребует `'unsafe-inline'` либо nonce.

## Статика и media

**Статика** — код: CSS, шрифты, вендорный JS. Сначала Tailwind, потом
`collectstatic`, иначе соберётся старый `output.css`. **Media** — загруженные
файлы; через git не переезжает, требует бэкапа, в проде раздаётся веб-сервером
(отдавать её через Django нельзя — это блокирующий воркер на каждой картинке).

## Процедура

```bash
git pull && uv sync --no-dev --group prod && npm ci && npm run build
```

```bash
uv run python manage.py migrate && uv run python manage.py collectstatic --noinput
```

```bash
uv run python manage.py check --deploy
```

Команда проверяет ровно список выше и должна отдавать **ноль предупреждений**.
Затем перезапуск gunicorn на `config.wsgi:application` под менеджером процессов,
за прокси, который терминирует TLS и раздаёт `/static/` и `/media/`.

## По расписанию

Одна задача, раз в сутки:

```bash
uv run python manage.py recount_views
```

Пересчитывает окно «Қазір танымал» по журналу прочтений и вычищает строки,
вышедшие из него (DEC-55). Без неё колонка только растёт: дефолтная сортировка
каталога со временем сойдётся с «Ең көп оқылған», а таблица журнала — с трафиком
за всё время. Команда идемпотентна, пропуск дня ничего не портит.

## Чек-лист перед публичным запуском

| # | Что | Статус |
|---|---|---|
| 1 | `DJANGO_ENV=production` | ждёт окружения |
| 2 | `check --deploy` без предупреждений | ждёт окружения |
| 3 | HTTPS, HSTS, secure-куки | ждёт окружения |
| 4 | `/_design/*` недоступны | следует из `DEBUG=False`, закрыто тестом |
| 5 | Placeholder-обложки в `media/` заменены на легальные | ⛔ |
| 6 | Правовые стабы наполнены реальным текстом (иначе ломается FR-AUTH-05) | ⛔ |
| 7 | Favicon-set вместо `logo.png`: 16/32/192/512 + maskable | ⛔ |
| 8 | OG-метаданные и `meta description` | ⛔ |
| 9 | `sitemap.xml` и `robots.txt` | ⛔ |
| 10 | Логирование ошибок настроено | ⛔ |
| 11 | Бэкап `media/` и базы | ⛔ |
| 12 | Решён вопрос OKLCH-fallback (DEC-12) | ⛔ |
| 13 | **Демо-вход заменён на Telegram Login Widget с проверкой подписи** | ⛔ |

Пункт 13 — единственный, который делает публичный запуск не «неполным», а
небезопасным: до него любой посетитель становится автором чужих произведений.
