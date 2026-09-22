"""Пересчёт окна «Қазір танымал» по журналу просмотров (DEC-55).

Запускается по расписанию, раз в сутки: `Story.recent_views` растёт на
каждом прочтении, а убывать сам по себе не умеет — из окна выходят строки,
а не колонка. Команда делает обе половины работы: считает колонку заново по
`StoryView` внутри окна и удаляет всё, что из него вышло.

Без неё ось DEC-36 со временем сходится с «Ең көп оқылған»: два разных
вопроса на главной начинают давать один и тот же порядок.

Идемпотентна: повтор через минуту не меняет ничего.
"""

from core import data
from core.domain.story import RECENT_VIEWS_DAYS

from ._base import QuietCommand


class Command(QuietCommand):
    help = f'Пересчитывает окно в {RECENT_VIEWS_DAYS} дней и чистит журнал.'

    def handle(self, *args, **options):
        touched, removed = data.recount_recent_views()
        self.say(options,
                 f'{touched} stories recounted, {removed} views pruned '
                 f'(window: {RECENT_VIEWS_DAYS} days)')
