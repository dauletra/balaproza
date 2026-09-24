# VPS: первичная настройка и деплой

Практический рантайм-слой к тому, что уже решено в [`deploy.md`](deploy.md)
(окружение, безопасность, статика, расписание, бэкап — политика и «почему»)
и [`../LAUNCH.md`](../LAUNCH.md) (что до сих пор делает человек). Здесь —
конкретные команды и файлы: пустой Ubuntu-сервер → работающий сайт, и как
потом выкатывать новый код. Читать один раз при первом сервере; дальше
нужен только раздел «Деплой обновлений».

Все скрипты и шаблоны лежат в [`../ops/`](../ops/) и написаны на реальный
стек проекта — Django 6 за gunicorn, nginx как прокси и раздатчик `media/`,
PostgreSQL, cron вместо очереди задач. Ничего из перечисленного не
абстрактный пример — это то, что нужно ЭТОМУ проекту, при его нынешнем
масштабе (см. `LAUNCH.md`, «Чего в этом списке нет»: общий кэш и очередь
задач намеренно не заведены).

## Что нужно до начала

- Сервер с Ubuntu 22.04 или 24.04, root-доступ по SSH (свежая VPS почти
  всегда даёт это сразу).
- Домен, у которого уже можно поставить A/AAAA-запись на IP сервера —
  без неё не будет TLS и не заработает Telegram Login Widget
  (`/setdomain` у `@BotFather` требует настоящий домен).
- SSH-ключ, добавленный в репозиторий как deploy key, если репозиторий
  приватный (`REPO_URL` тогда — `git@github.com:...`, а не `https://`).

## Первичная настройка

`provision.sh` ссылается на соседние файлы (`nginx.conf`, `qazaqnovel.service`
и другие в этой же папке), поэтому запускается не сам по себе, а из
временного клона — сам `provision.sh` потом клонирует репозиторий заново,
уже в `/srv/qazaqnovel`:

```bash
git clone https://github.com/dauletra/qazaqnovel.git /tmp/qazaqnovel-setup
cd /tmp/qazaqnovel-setup

DOMAIN=qazaqnovel.kz \
REPO_URL=git@github.com:dauletra/qazaqnovel.git \
ADMIN_EMAIL=you@example.com \
ops/provision.sh
```

`REPO_URL` — адрес, по которому клонирует уже сам `/srv/qazaqnovel`: для
приватного репозитория это `git@github.com:...` через deploy key, а не
`https://`, которым можно было клонировать только что публично.

Что делает [`ops/provision.sh`](../ops/provision.sh), по порядку:

1. Ставит пакеты: `git`, `postgresql`, `nginx`, `certbot`, Node.js 20 (для
   сборки CSS), инструменты для `ops/backup.sh` (`gnupg`, `rsync`).
2. Открывает firewall (`ufw`) только для SSH и nginx — всё остальное
   снаружи закрыто, включая прямой доступ к порту Postgres и к unix-
   сокету gunicorn (тот и не слушает TCP).
3. Заводит системного пользователя `qazaqnovel` — сайт не должен работать
   от root, и не должен делить пользователя с чем-то ещё на той же
   машине.
4. Ставит [uv](https://docs.astral.sh/uv/) этому пользователю.
5. Создаёт роль и базу Postgres (`qnovel_user`/`qnovel_db`, как в
   README, но без `CREATEDB` — это право нужно только тестам, а тесты в
   проде не гоняют) со сгенерированным паролем.
6. Клонирует репозиторий в `/srv/qazaqnovel`, если его там ещё нет.
7. Пишет `/srv/qazaqnovel/.env`, если файла ещё нет: `DATABASE_URL`,
   `DJANGO_ENV=production`, `SECRET_KEY` — из того, что скрипт уже знает
   или сгенерировал сам. `TELEGRAM_BOT_TOKEN`/`TELEGRAM_BOT_USERNAME`
   оставляет пустыми — это внешняя система (`@BotFather`), её заводит
   человек, см. `LAUNCH.md`, пункт 6.
8. Устанавливает и включает systemd-юнит, nginx-конфиг, crontab,
   logrotate — из шаблонов рядом (см. таблицу ниже).
9. Печатает, что осталось сделать руками.

**Дальше руками, в этом порядке** (скрипт печатает то же самое в конце):

```bash
# 1. Дописать в /srv/qazaqnovel/.env:
#    TELEGRAM_BOT_TOKEN=...
#    TELEGRAM_BOT_USERNAME=...
# (после @BotFather -> /newbot -> /setdomain на ваш домен)

# 2. Первый релиз — собрать статику, прогнать миграции, поднять сервис
sudo -u qazaqnovel bash -c 'cd /srv/qazaqnovel && ops/deploy.sh'

# 3. TLS — когда DNS уже указывает на сервер
certbot --nginx -d qazaqnovel.kz -d www.qazaqnovel.kz -m you@example.com --agree-tos
```

После этого сайт открывается по `https://ваш-домен`. Дальше — LAUNCH.md:
контент каталога, люди на модерации, правовые тексты у юриста и
проверка восстановления бэкапа (обязательна до публичного адреса, см.
чек-лист в `deploy.md`).

## Деплой обновлений

Код на сервере обновляет одна команда, от пользователя `qazaqnovel`:

```bash
ssh qazaqnovel@сервер
cd /srv/qazaqnovel && ops/deploy.sh
```

[`ops/deploy.sh`](../ops/deploy.sh) делает ровно то, что описано в
`deploy.md`, раздел «Процедура», одной командой: `git pull` (только
fast-forward — если история разошлась, скрипт остановится, а не смешает
чужой коммит с локальным), `uv sync`, сборка CSS, миграции,
`collectstatic`, `check --deploy` и перезапуск `systemd`-юнита. Любая
ошибка на любом шаге останавливает скрипт до перезапуска — старый процесс
продолжает отвечать читателям, пока не разберутся, что сломалось.

Если что-то пошло не так:

```bash
journalctl -u qazaqnovel -n 100 --no-pager   # что gunicorn написал при падении
git log -3 --oneline                          # на каком коммите остановились
git reset --hard HEAD~1 && ops/deploy.sh       # откат на предыдущий коммит
```

`git reset --hard` откатывает **код**; миграции откатывать так не
получится (Django не хранит откат автоматически) — если проблема в
миграции, откат делает `manage.py migrate core <номер_предыдущей>`
вручную, само по себе редкое и обдуманное действие, не для one-liner'а.

## Что каждый файл делает

| Файл | Что делает | Когда трогать руками |
|---|---|---|
| [`ops/provision.sh`](../ops/provision.sh) | Настраивает чистый сервер целиком: пакеты, firewall, пользователь, база, `.env`, systemd, nginx, cron, logrotate | Один раз на новом сервере; повторный запуск безопасен, но обычно не нужен |
| [`ops/deploy.sh`](../ops/deploy.sh) | Обновляет код: `git pull`, зависимости, миграции, статика, `check --deploy`, перезапуск | При каждом релизе |
| [`ops/qazaqnovel.service`](../ops/qazaqnovel.service) | systemd-юнит: как запускать gunicorn, от какого пользователя, что делать при падении (`Restart=on-failure`) | При смене числа воркеров или пути к venv |
| [`ops/nginx.conf`](../ops/nginx.conf) | Конфиг сайта в nginx: прокси на gunicorn через unix-сокет, раздача `/media/` напрямую, лимиты запросов, CSP | При смене домена, лимитов или CSP — синхронно с `deploy.md` |
| [`ops/crontab`](../ops/crontab) | Расписание: рассылка уведомлений раз в минуту, шесть суточных команд, бэкап | При добавлении новой суточной команды в `core/management/commands/` |
| [`ops/logrotate.conf`](../ops/logrotate.conf) | Не даёт логам cron-команд расти бесконечно (systemd-юнит логи сам не пишет в файл — их видно через `journalctl`) | Почти никогда |
| [`ops/backup.sh`](../ops/backup.sh) | Снимает дамп базы и архив `media/`, шифрует (если задан GPG-получатель), ротирует копии, шлёт отчёт в Telegram | Не трогать без причины — разбор решений в комментариях самого файла |
| [`ops/restore.sh`](../ops/restore.sh) | Восстанавливает базу и `media/` из снимка `backup.sh`, спрашивает подтверждение | При реальном восстановлении или при проверке (обязательна до запуска) |
| [`.env`](../.env.example) | Секреты и адрес БД — не в git; `provision.sh` создаёт на сервере автоматически | Дописать `TELEGRAM_BOT_TOKEN`, позже — `SENTRY_DSN`, `BACKUP_*` |

## Полезные команды

**Статус и логи**

```bash
sudo systemctl status qazaqnovel          # жив ли процесс, последние строки лога
sudo systemctl restart qazaqnovel         # ручной перезапуск (deploy.sh делает то же)
journalctl -u qazaqnovel -f               # лог gunicorn вживую
journalctl -u qazaqnovel --since "1 hour ago"
sudo nginx -t && sudo systemctl reload nginx   # проверить конфиг nginx и применить без разрыва соединений
tail -f /var/log/qazaqnovel/daily.log     # что написали ночные команды
```

**База**

```bash
sudo -u postgres psql qnovel_db
sudo -u qazaqnovel bash -c 'cd /srv/qazaqnovel && .venv/bin/python manage.py dbshell'
sudo -u qazaqnovel bash -c 'cd /srv/qazaqnovel && .venv/bin/python manage.py shell'
```

**Управление сайтом** (везде один и тот же шаблон: от `qazaqnovel`, из
`/srv/qazaqnovel`, через `.venv/bin/python` — `uv run` тут не обязателен,
venv уже собран `deploy.sh`)

```bash
sudo -u qazaqnovel bash -c 'cd /srv/qazaqnovel && .venv/bin/python manage.py createsuperuser'
sudo -u qazaqnovel bash -c 'cd /srv/qazaqnovel && .venv/bin/python manage.py make_moderator <ник>'   # роль модератора, LAUNCH.md п.2
sudo -u qazaqnovel bash -c 'cd /srv/qazaqnovel && .venv/bin/python manage.py prune_media'             # посчитать мусор в media/, без удаления
sudo -u qazaqnovel bash -c 'cd /srv/qazaqnovel && .venv/bin/python manage.py prune_media --apply'     # удалить
```

**Бэкап и восстановление**

```bash
cd /srv/qazaqnovel
set -a; source .env; set +a       # даёт backup.sh DATABASE_URL и TELEGRAM_BOT_TOKEN
BACKUP_DIR=/backups ops/backup.sh
ls -la /backups/daily/
BACKUP_DIR=/backups ops/restore.sh /backups/daily/2026-09-19
```

**Диагностика сервера**

```bash
df -h                     # место на диске — media/ и бэкапы растут
free -h                   # память
ss -tlnp                  # кто слушает какие порты (443/80 — nginx; gunicorn — только unix-сокет)
ss -lx | grep gunicorn     # сокет gunicorn существует и слушает
sudo ufw status verbose   # что открыто во внешний мир
```

**TLS**

```bash
sudo certbot renew --dry-run   # проверить, что автопродление сработает (сертификат живёт 90 дней)
sudo certbot certificates      # когда истекает текущий
```

certbot ставит свой systemd-таймер на автопродление сам — отдельная
запись в cron не нужна.

## Быстрая диагностика

| Симптом | Где смотреть |
|---|---|
| 502 Bad Gateway | `systemctl status qazaqnovel` — скорее всего gunicorn не поднялся; `journalctl -u qazaqnovel -n 50` |
| Страница без стилей | `collectstatic` не прогнали или упал — `deploy.sh` делает это сам, вручную: `uv run python manage.py collectstatic --noinput` |
| 400 Bad Request на всех страницах | `DJANGO_ALLOWED_HOSTS` в `.env` не совпадает с доменом в запросе |
| CSRF-ошибка на форме входа | Домен не в `DJANGO_ALLOWED_HOSTS`, либо nginx не шлёт `X-Forwarded-Proto` (см. `ops/nginx.conf`) |
| Обложки не грузятся, но текст открывается | nginx не раздаёт `/media/` — проверить `location /media/` в конфиге и права на `media/` |
| Telegram-вход не рисует кнопку | Бот не знает домен: `@BotFather` → `/setdomain` не выставлен на прод-домен |
| Уведомления не приходят | `push_notifications` не в cron или упала — `tail /var/log/qazaqnovel/push_notifications.log`; либо `TELEGRAM_BOT_TOKEN` пуст |
