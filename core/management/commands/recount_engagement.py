"""Сверка счётчиков-кэшей (`Story.comments`/`likes`, `User.followers`,
`StoryComment.likes`, `PollOption.votes`) с реальными строками.

Сигналы в `core/counters.py` двигают эти счётчики на каждом создании и
удалении строки, включая массовое удаление в админке и каскад от удаления
пользователя. Но у сигналов есть слепая зона — `bulk_create`/`bulk_update`
их не шлют — и всегда остаётся риск прямой правки в базе в обход Django.
Команда — страховка поверх сигналов, а не замена: запускается по
расписанию, идемпотентна, повтор через минуту не меняет ничего сверх нормы.
"""

from core import data

from ._base import QuietCommand


class Command(QuietCommand):
    help = 'Пересчитывает Story.comments/likes, User.followers и смежные счётчики от реальных строк.'

    def handle(self, *args, **options):
        touched = data.recount_engagement()
        for name, count in touched.items():
            self.say(options, f'{name}: {count} rows recounted')
