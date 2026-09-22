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
import json
import time
import urllib.error
import urllib.request

# Старше — подпись верна, но ссылку не принимаем: Telegram не даёт nonce,
# только `auth_date`, и это единственная защита от повторного использования
# утёкшего URL (в логах прокси, в истории браузера).
#
# Пять минут, а не сутки. Суток тут не требовалось ничем: виджет
# редиректит браузер сразу, и между подписью и нашим callback проходят
# секунды. А подписанный адрес всё это время равен входу в аккаунт —
# кто его прочёл, тот вошёл. Пяти минут хватает на медленную сеть,
# закрытую крышку ноутбука и повторную отправку формы; на то, чтобы
# ссылка дожила до чтения логов, — уже нет.
MAX_AUTH_AGE = 5 * 60


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


# ── Отправка сообщения ───────────────────────────────────────────────────
#
# Тот же бот, которым человек вошёл, и то же разрешение: виджет входа
# просит `data-request-access="write"`, то есть право писать получено ещё
# на входе — отдельного «нажми Start у бота» не требуется. Разрешение
# можно и не дать, и отозвать потом; оба случая приходят сюда отказом.
#
# Здесь, рядом с проверкой подписи, по той же причине: Telegram — внешний
# протокол, а не часть предметной области портала. Ни моделей, ни
# настроек Django — токен приходит параметром.
#
# `urllib`, а не `requests`: один POST с JSON не стоит шестой зависимости
# в проекте, где их пять.

_SEND_URL = 'https://api.telegram.org/bot{token}/sendMessage'

# Что вернула отправка. Пусто — доставлено; остальное объясняет, что
# делать дальше, и это два **разных** ответа: «повторять бессмысленно» и
# «сейчас не вышло».
PUSH_OK = ''
PUSH_BLOCKED = 'blocked'
PUSH_FAILED = 'failed'

# Ответы, после которых повторять нечего: адресат закрыл бота, удалил
# аккаунт, не дал права писать. Telegram отвечает на них 4xx с текстом —
# по коду их не отличить от «неверный токен», поэтому смотрим описание.
_PERMANENT = (
    'bot was blocked',
    'user is deactivated',
    'chat not found',
    "bot can't initiate conversation",
)


def _description(error) -> str:
    """Человеческая часть отказа Telegram. Тело читается один раз и может
    оказаться не-JSON (прокси, страница ошибки) — тогда пусто, и отказ
    считается временным: лучше повторить лишний раз, чем замолчать
    навсегда из-за чужой HTML-страницы."""
    try:
        return json.loads(error.read().decode()).get('description', '').lower()
    except (ValueError, OSError, AttributeError):
        return ''


def send_telegram_message(bot_token: str, chat_id: int, text: str, *,
                          timeout: int = 10) -> str:
    """Отправить сообщение. `PUSH_OK` — доставлено, иначе код причины.

    Исключений не бросает вовсе: зовут её из команды по расписанию, где
    одно упавшее сообщение не должно уносить всю очередь.
    """
    payload = json.dumps({
        'chat_id': chat_id,
        'text': text,
        # Своя же ссылка под каждым уведомлением развернулась бы карточкой
        # с обложкой — в ленте бота это шум, а не помощь.
        'link_preview_options': {'is_disabled': True},
    }).encode()
    request = urllib.request.Request(
        _SEND_URL.format(token=bot_token), data=payload,
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return PUSH_OK if response.status == 200 else PUSH_FAILED
    except urllib.error.HTTPError as error:
        description = _description(error)
        return (PUSH_BLOCKED if any(m in description for m in _PERMANENT)
                else PUSH_FAILED)
    except (urllib.error.URLError, OSError, ValueError):
        # Сеть, таймаут, DNS. Временное по определению.
        return PUSH_FAILED
