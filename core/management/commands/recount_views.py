"""Пересчёт окна «Қазір танымал» по журналу просмотров (DEC-55).

Запускается по расписанию, раз в сутки: `Story.recent_views` растёт на
каждом прочтении, а убывать сам по себе не умеет — из окна выходят строки,
а не колонка. Команда делает обе половины работы: считает колонку заново по
`StoryView` внутри окна и удаляет всё, что из него вышло.

Без неё ось DEC-36 со временем сходится с «Ең көп оқылған»: два разных
вопроса на главной начинают давать один и тот же порядок.

Идемпотентна: повтор через минуту не меняет ничего.
"""

from django.core.management.base import BaseCommand

from core import data
from core.domain.story import RECENT_VIEWS_DAYS


class Command(BaseCommand):
    help = f'Пересчитывает окно в {RECENT_VIEWS_DAYS} дней и чистит журнал.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--quiet', action='store_true',
            help='Без отчёта в stdout (для вызова из тестов).',
        )

    def handle(self, *args, **options):
        touched, removed = data.recount_recent_views()
        if not options['quiet']:
            # Отчёт по-английски, как у seed_demo: это вывод инструмента,
            # а не строка интерфейса.
            self.stdout.write(
                f'{touched} stories recounted, {removed} views pruned '
                f'(window: {RECENT_VIEWS_DAYS} days)')
