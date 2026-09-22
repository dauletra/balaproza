"""Доставка уведомлений в Telegram — тем же ботом, которым человек вошёл.

Запускается по расписанию, раз в минуту. Не в запросе пользователя: ходить
в чужой сервис внутри обработки формы значит поставить скорость
комментирования в зависимость от Telegram, а его недоступность — в
зависимость от того, сохранится ли комментарий вообще. Событие пишется в
базу сразу (`queries/notifications`), доставка догоняет.

Почему это вообще нужно. До неё уведомление ждало, пока человек сам зайдёт
на сайт и посмотрит на колокольчик: автор, отправивший главу на модерацию,
узнавал решение, только вернувшись и проверив. Аудитория портала живёт в
Telegram, право писать ей получено ещё на входе (виджет просит
`request-access=write`) — и не использовалось.

Идемпотентна в том смысле, в каком бывает отправка: повторный запуск не
шлёт то, что уже ушло (`Notification.pushed_at`). Повтор **того же** прохода
после падения посередине может отправить одно сообщение дважды — отметка
ставится после ответа Telegram, и иначе никак: выбор стоит между «дважды
показали» и «молча потеряли», и первое честнее.
"""

import time
from contextlib import contextmanager

from django.conf import settings
from django.db import connection

from core import data
from core.domain.telegram import PUSH_BLOCKED, PUSH_OK, send_telegram_message
from core.links import push_message

from ._base import QuietCommand

# Пауза между сообщениями. Bot API держит около тридцати в секунду; 40 мс
# укладываются в предел с запасом и не растягивают проход: двести
# сообщений это восемь секунд.
PAUSE_SECONDS = 0.04

# Ключ блокировки. Произвольное число, но постоянное: по нему два запуска
# узнают друг о друге.
_LOCK_KEY = 4_820_260_922


@contextmanager
def single_run():
    """Один проход за раз — консультативной блокировкой Postgres.

    Команда ходит раз в минуту и берёт до двухсот строк, а таймаут на
    сообщение — десять секунд: медленная сеть растягивает проход на
    полчаса. Отметка «отправлено» ставится **после** ответа Telegram и
    пачкой в конце, поэтому второй запуск, стартовавший через минуту,
    видит те же неотмеченные строки и шлёт их второй раз.

    То есть идемпотентность ломалась не от падения, а от штатной
    медленной сети — и человек получал дубли.

    `flock` в cron решал бы то же, но снаружи и молча: забытый при
    переносе на другой сервер, он ничем о себе не напомнит. Блокировка
    здесь едет вместе с командой.

    Она **консультативная и посессионная**: Postgres сам отпускает её,
    когда соединение умирает, — упавший посреди прохода процесс не
    оставляет очередь запертой навсегда.
    """
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [_LOCK_KEY])
        acquired = cursor.fetchone()[0]
    try:
        yield acquired
    finally:
        if acquired:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s)', [_LOCK_KEY])


class Command(QuietCommand):
    help = 'Отправляет неотправленные уведомления в Telegram.'

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            '--limit', type=int, default=data.PUSH_BATCH,
            help=f'Сколько уведомлений за проход (по умолчанию {data.PUSH_BATCH}).',
        )

    def handle(self, *args, **options):
        with single_run() as acquired:
            if not acquired:
                # Прошлый запуск ещё идёт. Не ошибка: хвост подберёт
                # следующая минута, а дубль у человека не исправить.
                self.say(options, 'another run is still going, skipped')
                return
            self._send(**options)

    def _send(self, **options):
        if not settings.TELEGRAM_BOT_TOKEN:
            # В разработке без бота это норма, а не ошибка: событие уже
            # записано и видно на сайте. Молчать всё же нельзя — иначе
            # «почему не приходит» выясняется гаданием.
            self.stderr.write('TELEGRAM_BOT_TOKEN не задан — рассылка пропущена')
            return

        queue = data.pending_pushes(options['limit'])
        sent, blocked, failed = [], 0, 0
        # Кому уже отказано навсегда: остальные его сообщения в этом же
        # проходе слать незачем — выборка сделана до того, как выключатель
        # снялся.
        gone = set()

        for notification in queue:
            recipient = notification.user
            if recipient.pk in gone:
                sent.append(notification)
                continue

            outcome = send_telegram_message(
                settings.TELEGRAM_BOT_TOKEN, recipient.telegram_id,
                push_message(notification))

            if outcome == PUSH_OK:
                sent.append(notification)
            elif outcome == PUSH_BLOCKED:
                # Дверь закрыта: снимаем канал и отмечаем отправленным —
                # иначе строка крутится в очереди до истечения срока.
                data.disable_push(recipient)
                gone.add(recipient.pk)
                sent.append(notification)
                blocked += 1
            else:
                # Временное: оставляем без отметки, подберёт следующий
                # проход — пока событие не станет слишком старым, чтобы
                # его вообще стоило слать.
                failed += 1

            time.sleep(PAUSE_SECONDS)

        data.mark_pushed(sent)

        if not options['quiet']:
            # Отчёт по-английски, как у остальных команд: это вывод
            # инструмента, а не строка интерфейса.
            self.stdout.write(
                f'{len(sent) - blocked} pushed, {blocked} recipients disabled, '
                f'{failed} left for the next run')
