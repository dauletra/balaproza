#!/usr/bin/env bash
#
# Восстановление из снимка, снятого `backup.sh`.
#
# Половина, без которой первая половина не существует: бэкап, который
# никто не восстанавливал, бэкапом не является — он копия неизвестного
# качества. Этот скрипт нужен не в день беды, а **до** него: пункт
# чек-листа закрывается тогда, когда восстановление прошло хотя бы раз, на
# пустой базе, и сайт после него открылся.
#
#   ops/restore.sh /backups/daily/2026-09-19
#
# Переменные — те же, что у `backup.sh`: DATABASE_URL, MEDIA_DIR.
#
# Скрипт **перезаписывает** базу, на которую указывает DATABASE_URL, и
# каталог media/. Поэтому спрашивает подтверждение: единственный способ
# потерять данные при восстановлении — восстановить не туда.

set -euo pipefail

snapshot="${1:-}"
[ -n "$snapshot" ] || { echo "укажи каталог снимка: ops/restore.sh <путь>" >&2; exit 1; }

: "${DATABASE_URL:?нужна переменная DATABASE_URL}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEDIA_DIR="${MEDIA_DIR:-$here/../media}"

# ── Расшифровка, если снимок зашифрован ──────────────────────────────────
#
# `backup.sh` шифрует дамп, когда задан получатель. Восстановление обязано
# понимать оба вида снимка: бэкап, который нельзя восстановить, бэкапом не
# является, а шифрование — ровно тот шаг, на котором это ломается молча.
#
# Расшифрованное кладётся во временный каталог и удаляется при выходе:
# оставить открытый дамп рядом с зашифрованным значило бы отменить
# шифрование задним числом.
work="$snapshot"
if [ ! -f "$snapshot/db.dump" ] && [ -f "$snapshot/db.dump.gpg" ]; then
    command -v gpg >/dev/null 2>&1 || {
        echo "снимок зашифрован, а gpg не установлен" >&2; exit 1; }
    work="$(mktemp -d)"
    trap 'rm -rf "$work"' EXIT
    echo "снимок зашифрован — расшифровываю во временный каталог"
    for cipher in "$snapshot"/*.gpg; do
        [ -f "$cipher" ] || continue
        plain="$work/$(basename "${cipher%.gpg}")"
        gpg --batch --yes --output "$plain" --decrypt "$cipher"
    done
fi

[ -f "$work/db.dump" ] || { echo "нет $snapshot/db.dump" >&2; exit 1; }

cat "$snapshot/manifest.txt" 2>/dev/null || true
echo
echo "База будет ПЕРЕЗАПИСАНА: ${DATABASE_URL%%\?*}"
echo "media/ будет ПЕРЕЗАПИСАНА: $MEDIA_DIR"
read -r -p "Продолжить? напиши yes: " answer
[ "$answer" = "yes" ] || { echo "отменено"; exit 1; }

# `--clean --if-exists`: снести то, что есть, и положить снимок. Без
# `--clean` восстановление в непустую базу падает на первом же конфликте
# ключей и оставляет её наполовину чужой.
pg_restore --clean --if-exists --no-owner --no-privileges \
           --dbname="$DATABASE_URL" "$work/db.dump"

if [ -f "$work/media.tar.gz" ]; then
    mkdir -p "$MEDIA_DIR"
    # Старое убирается целиком: файл, которого нет в снимке, — это файл,
    # про который база ничего не знает.
    rm -rf "${MEDIA_DIR:?}/"*
    tar --extract --gzip --file="$work/media.tar.gz" -C "$MEDIA_DIR"
fi

echo "восстановлено из $snapshot"
echo "проверь: открой главную и страницу произведения с обложкой"
