"""Файлы в `media/`, которых не держит ни одна строка.

Сигналы `core/media_cleanup.py` убирают файл, когда объект меняется или
удаляется через ORM, и этого хватает на всё, кроме одного случая: файл,
записанный в транзакции, которая потом откатилась. Диск про откат не
знает, и такой файл остаётся навсегда.

Копится он незаметно и до счёта выглядит мелочью. Счёт: 12 825 файлов на
341 МБ при пятнадцати строках в базе, то есть 99,9% папки — ничьё. Цена
не только в месте: `ops/backup.sh` возит `media/` целиком, и суточная
копия платформы на 99% состояла из мусора.

**Без `--apply` команда ничего не удаляет.** Это не осторожность ради
осторожности: она стирает содержимое платформы, и единственная ошибка в
сверке — например, поле, забытое в `RASTER_FIELDS`, — означает обложки,
которых не вернуть. Сначала отчёт, потом решение.

Отсрочка (`--older-than`, по умолчанию сутки) закрывает гонку: файл
пишется до `COMMIT`, и в момент прохода строки на него может ещё не
быть.

В cron — раз в сутки, рядом с `prune_old_rows`. Отдельной командой, а не
внутри неё: та удаляет строки и обратима бэкапом базы, эта удаляет файлы
и обратима только бэкапом `media/`.
"""

from django.core.management.base import BaseCommand

from core import data


class Command(BaseCommand):
    help = ('Показывает (а с --apply удаляет) файлы в media/, '
            'на которые не ссылается ни одна строка.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--quiet', action='store_true',
            help='Без отчёта в stdout (для вызова из тестов).',
        )
        parser.add_argument(
            '--apply', action='store_true',
            help='Действительно удалить. Без него — только отчёт.',
        )
        parser.add_argument(
            '--older-than', type=int, default=24, metavar='HOURS',
            help='Не трогать файлы моложе стольких часов (по умолчанию 24).',
        )

    def handle(self, *args, **options):
        orphans = data.orphan_media_files(older_than_hours=options['older_than'])
        total_bytes = sum(path.stat().st_size for path in orphans)

        removed = 0
        if options['apply']:
            for path in orphans:
                try:
                    path.unlink()
                except OSError:
                    # Файл мог уйти между сверкой и удалением — сигналом
                    # или второй копией команды. Это ровно тот исход,
                    # которого мы и добивались, а не повод падать.
                    continue
                removed += 1

        if not options['quiet']:
            megabytes = total_bytes / 1048576
            verb = f'{removed} removed' if options['apply'] else 'dry run'
            self.stdout.write(
                f'{len(orphans)} orphan media files ({megabytes:.1f} MB), '
                f'{verb}')
