"""Сверка счётчиков-кэшей (`Story.comments`/`likes`, `User.followers`,
`StoryComment.likes`, `PollOption.votes`) с реальными строками.

Сигналы в `core/counters.py` двигают эти счётчики на каждом создании и
удалении строки, включая массовое удаление в админке и каскад от удаления
пользователя. Но у сигналов есть слепая зона — `bulk_create`/`bulk_update`
их не шлют — и всегда остаётся риск прямой правки в базе в обход Django.
Команда — страховка поверх сигналов, а не замена: запускается по
расписанию, идемпотентна, повтор через минуту не меняет ничего сверх нормы.
"""

from django.core.management.base import BaseCommand

from core import data


class Command(BaseCommand):
    help = 'Пересчитывает Story.comments/likes, User.followers и смежные счётчики от реальных строк.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--quiet', action='store_true',
            help='Без отчёта в stdout (для вызова из тестов).',
        )

    def handle(self, *args, **options):
        touched = data.recount_engagement()
        if not options['quiet']:
            for name, count in touched.items():
                self.stdout.write(f'{name}: {count} rows recounted')
