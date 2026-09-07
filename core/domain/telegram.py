"""Проверка подписи Telegram Login Widget (NFR-25).

Redirect-режим: виджет не шлёт JS-колбэк, а редиректит браузер на наш
`data-auth-url` с подписанными параметрами в query string. Алгоритм —
из документации Telegram (Login Widget): `secret_key = sha256(bot_token)`,
`data_check_string` — все поля кроме `hash`, отсортированные по ключу и
склеенные `\n`, подпись — `hmac_sha256(data_check_string, secret_key)`.

Чистая функция: не знает ни моделей, ни `core.data`, ни настроек Django —
токен приходит параметром, вызывающая сторона (view) берёт его из
`settings.TELEGRAM_BOT_TOKEN`.
"""

import hashlib
import hmac
import time

# Старше — подпись верна, но ссылку не принимаем: Telegram не даёт nonce,
# только `auth_date`, и это единственная защита от повторного использования
# утёкшего URL (в логах, в истории браузера).
MAX_AUTH_AGE = 24 * 60 * 60


def verify_telegram_auth(params: dict, bot_token: str, *,
                         max_age: int = MAX_AUTH_AGE) -> str | None:
    """`None` — подпись верна и свежа. Иначе код причины отказа.

    `params` — то, что пришло в query string (`request.GET`), значения
    строками. `id` и `auth_date` в них тоже строки — сравнение с ними
    делает вызывающая сторона своим типом.
    """
    received_hash = params.get('hash')
    if not received_hash:
        return 'missing_hash'

    auth_date = params.get('auth_date')
    if not auth_date or not auth_date.isdigit():
        return 'missing_auth_date'

    data_check_string = '\n'.join(
        f'{key}={value}' for key, value in sorted(params.items())
        if key != 'hash'
    )
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(),
                             hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed_hash, received_hash):
        return 'bad_signature'

    if int(auth_date) < time.time() - max_age:
        return 'stale'

    return None
