#!/usr/bin/env bash
#
# Деплой обновлений на уже настроенном сервере (после ops/provision.sh).
# Запускать от пользователя qazaqnovel, из каталога с кодом:
#
#   cd /srv/qazaqnovel && ops/deploy.sh
#
# `set -e` останавливает скрипт на первой ошибке: упавшая миграция или
# непройденный `check --deploy` не должны доехать до перезапуска сервиса —
# старый процесс продолжает отвечать, пока никто не поймёт, что не так.

set -euo pipefail

# uv ставится в ~/.local/bin, а неинтерактивный shell (cron, `sudo -u user
# bash script.sh`) читает PATH не из .bashrc.
export PATH="$HOME/.local/bin:$PATH"

cd "$(dirname "${BASH_SOURCE[0]}")/.."

branch="$(git rev-parse --abbrev-ref HEAD)"
echo "── git pull ($branch) ────────────────────────────────────────────"
git pull --ff-only origin "$branch"

echo "── зависимости ────────────────────────────────────────────────────"
uv sync --no-dev --group prod
npm ci
npm run build

echo "── миграции и статика ───────────────────────────────────────────"
uv run python manage.py migrate --noinput
uv run python manage.py collectstatic --noinput

echo "── проверка прод-настроек ───────────────────────────────────────"
# Тот же список, что README требует проверять перед каждым деплоем
# (docs/deploy.md, «Безопасность»). Ноль предупреждений — условие
# перезапуска, а не совет.
uv run python manage.py check --deploy --fail-level WARNING

echo "── перезапуск ───────────────────────────────────────────────────"
sudo systemctl restart qazaqnovel

# Рестарт асинхронный: команда возвращается раньше, чем gunicorn успевает
# подняться или упасть. Пауза короткая — воркеры стартуют за доли секунды,
# и смысл проверки не «подождать долго», а не отчитаться «готово» поверх
# уже упавшего процесса.
sleep 2
if systemctl is-active --quiet qazaqnovel; then
    echo "готово: $(git rev-parse --short HEAD) ($branch)"
else
    echo "qazaqnovel не поднялся после рестарта — смотри: journalctl -u qazaqnovel -n 50" >&2
    exit 1
fi
