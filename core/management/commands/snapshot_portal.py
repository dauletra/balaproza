"""Суточный снимок портала — то, чего завтра уже не посчитать.

Запускается по расписанию, раз в сутки, и снимает **вчерашний** день:
сутки должны быть полными, иначе строка врёт про читателя тем сильнее,
чем раньше отработал cron.

Зачем это есть. Сводка `/moderation/summary/` отвечает «сколько сейчас»
и не умеет ответить «растёт или падает»: в базе лежат только текущие
числа. Накопленные счётчики при этом **убывают** — аккаунт удаляется
немедленно и полностью, работа сносится автором, — и «сколько нас было в
среду» после среды не восстанавливается ничем.

Возвращаемость читателя — главный вопрос выживания портала — тем более:
она считается по журналу `StoryView`, а тот живёт две недели и чистится
`recount_views`. Снять это число можно только вовремя, и в этом вся
причина команды.

Порядок с `recount_views` не важен: вчерашние строки журнала не бывают
старше окна, и вычистить их пересчёт не может. Важна регулярность —
наверстать пропуск `--day` можно, но не глубже окна, дальше читателя уже
не посчитать.

Идемпотентна: повторный запуск за тот же день переписывает строку, а не
заводит вторую.
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from core import data


class Command(BaseCommand):
    help = 'Замораживает сводку портала за сутки (по умолчанию за вчера).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--quiet', action='store_true',
            help='Без отчёта в stdout (для вызова из тестов).',
        )
        parser.add_argument(
            '--day', default='',
            help='Какой день снять, ГГГГ-ММ-ДД. По умолчанию — вчерашний.',
        )

    def handle(self, *args, **options):
        day = None
        if options['day']:
            try:
                day = date.fromisoformat(options['day'])
            except ValueError:
                raise CommandError('--day ожидает дату в виде ГГГГ-ММ-ДД')

        row = data.record_portal_day(day)

        if not options['quiet']:
            # Отчёт по-английски, как у остальных команд: это вывод
            # инструмента, а не строка интерфейса.
            self.stdout.write(
                f'{row.day}: {row.readers} readers, '
                f'{row.returning_readers} of them also read the day before, '
                f'{row.published} authors published, {row.overdue} overdue')
