"""Библиотека и место, на котором читатель остановился.

Продолжение чтения — первоклассный сценарий (FR-HOME-02): им живут и
хиро главной, и подпись кнопки на странице произведения. Поэтому прогресс
спрашивается по человеку, а не берётся единственным демо-объектом, как в
стабе.
"""

from django.db import IntegrityError, transaction
from django.db.models import OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from ..models import ReadingProgress
from .catalog import CHARS_PER_MINUTE, chapter_count_subquery


def progress_chapter_subquery(user_ref: str = 'user', story_ref: str = 'story'):
    """На какой главе читатель — подзапросом, для аннотации `progress_chapter`.

    Нужен полке библиотеки: строка «оқу үстінде» показывает «4 / 12
    бөлім». Раньше номер главы лежал колонкой в самой `LibraryEntry`, то
    есть один и тот же факт хранился дважды — и в корпусе уже разошёлся:
    `kronchessii` стоял на полке с четвёртой главой, а записи о прогрессе
    у него не было вовсе (DEC-52).

    Без записи — первая глава: работа лежит на полке, но не открыта.
    """
    return Coalesce(
        Subquery(
            ReadingProgress.objects.filter(
                user=OuterRef(user_ref), story=OuterRef(story_ref),
            ).values('current_chapter')[:1],
        ),
        Value(1),
    )


def record_reading_progress(user, story, chapter_number: int, chapters) -> None:
    """Запомнить, где читатель остановился (FR-HOME-02).

    До этого запись создавал только сид: «Оқуды жалғастыру» на главной
    всегда указывало в одно и то же место, сколько бы читатель ни читал.

    `minutes_left` считается по главам **после** текущей. Внутри главы
    позиции у нас нет — читалка не сообщает, где закрыли страницу, — и
    прикидывать её долю значило бы выдумывать число. Дочитанная работа
    честно показывает ноль.

    `quote` не трогается: сочинять цитату не из чего, а уже сохранённую
    перезаписывать пустой строкой тем более незачем.

    Сначала UPDATE, и только на ноль задетых строк — вставка. Это
    происходит на **каждом** открытии главы, то есть на самом частом
    действии портала, а `update_or_create` стоил бы там четырёх запросов
    (транзакция, выборка, запись) вместо одного. Первый заход платит
    больше; все следующие — один UPDATE.

    Гонка двух одновременных первых заходов упирается в уникальность пары
    «читатель — работа». Ловим её и дописываем тем же UPDATE: это ровно
    то, что делает внутри себя `update_or_create`.
    """
    remaining = sum(c.char_count for c in chapters if c.number > chapter_number)
    values = {
        'current_chapter': chapter_number,
        'minutes_left': (remaining + CHARS_PER_MINUTE - 1) // CHARS_PER_MINUTE,
        'last_read_on': timezone.localdate(),
    }
    rows = ReadingProgress.objects.filter(user=user, story=story).update(**values)
    if rows:
        return
    try:
        with transaction.atomic():
            ReadingProgress.objects.create(user=user, story=story, **values)
    except IntegrityError:
        ReadingProgress.objects.filter(user=user, story=story).update(**values)


def reading_progress_of(username: str):
    """Последнее, что читатель не дочитал, или None.

    Одна запись, а не список: «Оқуды жалғастыру» отвечает на «что открыть
    сейчас», и выбор из пяти вариантов — это уже библиотека.

    Число частей едет той же строкой: хиро главной рисует полосу
    «3 / 12 бөлім», и без подсказки `Story.chapters` спросил бы базу
    отдельно (тот же приём, что в `library_of`).
    """
    if not username:
        return None
    progress = (ReadingProgress.objects
                .filter(user__username=username)
                .select_related('story', 'story__author',
                                'story__primary_genre')
                .annotate(story_chapters=chapter_count_subquery('story'))
                .first())
    if progress is not None:
        progress.story.chapter_count = progress.story_chapters
    return progress
