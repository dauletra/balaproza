#!/usr/bin/env bash
#
# Первичная настройка чистого сервера Ubuntu под Qazaqnovel. Запускать один
# раз, от root, на новой машине:
#
#   DOMAIN=qazaqnovel.kz REPO_URL=git@github.com:dauletra/qazaqnovel.git \
#   ADMIN_EMAIL=you@example.com ops/provision.sh
#
# Разбор шагов и что делать руками после — в docs/vps-setup.md.
#
# Повторный запуск не ломает уже настроенное: пакеты и firewall-правила
# идемпотентны сами по себе, пользователь/база/`.env` создаются только если
# их ещё нет, systemd- и nginx-конфиги перезаписываются шаблоном заново
# (это единственное, что правится этим скриптом, а не руками на сервере).
#
# Что скрипт **не** делает: не разворачивает код и не выпускает TLS-
# сертификат. Код разворачивает `ops/deploy.sh` — из этого же клона, после
# заполнения `.env`; сертификат просит DNS, указывающий на сервер уже
# сейчас, а не когда-нибудь, и падение certbot на середине провижининга не
# должно валить всё остальное.

set -euo pipefail

: "${DOMAIN:?нужен DOMAIN, например qazaqnovel.kz}"
: "${REPO_URL:?нужен REPO_URL — адрес git-репозитория}"
: "${ADMIN_EMAIL:?нужен ADMIN_EMAIL — на него придёт напоминание об истечении TLS-сертификата}"

APP_USER="qazaqnovel"
APP_DIR="/srv/qazaqnovel"
DB_NAME="qnovel_db"
DB_USER="qnovel_user"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[ "$(id -u)" -eq 0 ] || { echo "запускать от root (sudo -i)" >&2; exit 1; }

echo "── Пакеты ──────────────────────────────────────────────────────────"
apt-get update
apt-get install -y --no-install-recommends \
    git curl ca-certificates openssl gnupg rsync build-essential \
    postgresql postgresql-contrib \
    nginx certbot python3-certbot-nginx \
    ufw

# Node нужен только на сборке CSS (`npm run build` в deploy.sh) — в
# рантайме gunicorn отдаёт уже собранный output.css, второй процесс не
# держим.
if ! command -v node >/dev/null 2>&1; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
fi

echo "── Файрвол ─────────────────────────────────────────────────────────"
# SSH до включения — иначе первый же `ufw enable` отрежет сессию, из
# которой этот скрипт запущен.
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

echo "── Пользователь и каталоги ────────────────────────────────────────"
id -u "$APP_USER" >/dev/null 2>&1 || \
    useradd --system --create-home --home-dir "$APP_DIR" --shell /bin/bash "$APP_USER"
mkdir -p /var/log/qazaqnovel /backups
chown "$APP_USER:$APP_USER" /var/log/qazaqnovel

echo "── uv для $APP_USER ───────────────────────────────────────────────"
sudo -u "$APP_USER" -H bash -c \
    'command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh'

echo "── База данных ─────────────────────────────────────────────────────"
# Пароль генерируется один раз и живёт на диске: повторный запуск должен
# находить ту же роль с тем же паролем, а не переписывать `.env` заново.
DB_PASSWORD_FILE="/root/.qazaqnovel_db_password"
if [ ! -f "$DB_PASSWORD_FILE" ]; then
    openssl rand -base64 32 > "$DB_PASSWORD_FILE"
    chmod 600 "$DB_PASSWORD_FILE"
fi
DB_PASSWORD="$(cat "$DB_PASSWORD_FILE")"

# Без CREATEDB: в проде тесты не гоняют, а право создавать базы этой роли
# ни для чего, кроме тестов, не нужно (README — про роль для разработки).
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"

echo "── Код ─────────────────────────────────────────────────────────────"
if [ -d "$APP_DIR/.git" ]; then
    echo "репозиторий уже склонирован — пропускаю"
else
    sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
fi
chmod +x "$APP_DIR"/ops/*.sh

echo "── .env ────────────────────────────────────────────────────────────"
# Секреты, которые скрипт знает сам (пароль базы, ключ подписи), пишутся
# сразу. TELEGRAM_BOT_TOKEN и остальное — из внешних систем (@BotFather,
# GlitchTip), их заполняет человек: LAUNCH.md держит эти пункты открытыми
# не просто так.
if [ ! -f "$APP_DIR/.env" ]; then
    SECRET_KEY="$(sudo -u "$APP_USER" -H bash -c \
        "cd $APP_DIR && ~/.local/bin/uv run python -c 'import secrets; print(secrets.token_urlsafe(64))'")"
    cat > "$APP_DIR/.env" <<EOF
DATABASE_URL=postgres://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME
DJANGO_ENV=production
SECRET_KEY=$SECRET_KEY
DJANGO_ALLOWED_HOSTS=$DOMAIN,www.$DOMAIN
DJANGO_SITE_URL=https://$DOMAIN

# Обязательно перед первым запуском — без них check --deploy падает:
# @BotFather -> /newbot -> /setdomain на $DOMAIN
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=

# Необязательные — см. docs/vps-setup.md и docs/deploy.md:
SENTRY_DSN=
BACKUP_GPG_RECIPIENT=
BACKUP_REMOTE=
BACKUP_CHAT_ID=
EOF
    chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
    echo "создан $APP_DIR/.env — заполни TELEGRAM_BOT_TOKEN/USERNAME перед первым деплоем"
else
    echo "$APP_DIR/.env уже есть — не трогаю"
fi

echo "── systemd ─────────────────────────────────────────────────────────"
install -m 644 "$HERE/qazaqnovel.service" /etc/systemd/system/qazaqnovel.service
systemctl daemon-reload
systemctl enable qazaqnovel

echo "── sudo на перезапуск сервиса ──────────────────────────────────────"
# deploy.sh запускает $APP_USER без пароля к root, а перезапустить systemd-
# юнит без root не может никто. Разрешение — только на этот один рестарт.
cat > /etc/sudoers.d/qazaqnovel <<EOF
$APP_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart qazaqnovel, /usr/bin/systemctl status qazaqnovel
EOF
chmod 440 /etc/sudoers.d/qazaqnovel
visudo -cf /etc/sudoers.d/qazaqnovel

echo "── nginx ───────────────────────────────────────────────────────────"
sed "s/__DOMAIN__/$DOMAIN/g" "$HERE/nginx.conf" > /etc/nginx/sites-available/qazaqnovel
ln -sf /etc/nginx/sites-available/qazaqnovel /etc/nginx/sites-enabled/qazaqnovel
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo "── cron ────────────────────────────────────────────────────────────"
sed "s#__APP_DIR__#$APP_DIR#g" "$HERE/crontab" | crontab -u "$APP_USER" -

echo "── logrotate ───────────────────────────────────────────────────────"
install -m 644 "$HERE/logrotate.conf" /etc/logrotate.d/qazaqnovel

cat <<MSG

Готово. Дальше руками (по порядку):

  1. Заполнить TELEGRAM_BOT_TOKEN и TELEGRAM_BOT_USERNAME в $APP_DIR/.env
     (@BotFather -> /newbot -> /setdomain на $DOMAIN).
  2. Первый релиз:
       sudo -u $APP_USER bash -c 'cd $APP_DIR && ops/deploy.sh'
  3. TLS, когда DNS на $DOMAIN уже смотрит на этот сервер:
       certbot --nginx -d $DOMAIN -d www.$DOMAIN -m $ADMIN_EMAIL --agree-tos
  4. Проверить восстановление бэкапа хотя бы раз — docs/deploy.md,
     "Бэкап и восстановление".

MSG
