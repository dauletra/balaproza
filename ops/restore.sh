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
[ -f "$snapshot/db.dump" ] || { echo "нет $snapshot/db.dump" >&2; exit 1; }

: "${DATABASE_URL:?нужна переменная DATABASE_URL}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEDIA_DIR="${MEDIA_DIR:-$here/../media}"

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
           --dbname="$DATABASE_URL" "$snapshot/db.dump"

if [ -f "$snapshot/media.tar.gz" ]; then
    mkdir -p "$MEDIA_DIR"
    # Старое убирается целиком: файл, которого нет в снимке, — это файл,
    # про который база ничего не знает.
    rm -rf "${MEDIA_DIR:?}/"*
    tar --extract --gzip --file="$snapshot/media.tar.gz" -C "$MEDIA_DIR"
fi

echo "восстановлено из $snapshot"
echo "проверь: открой главную и страницу произведения с обложкой"
