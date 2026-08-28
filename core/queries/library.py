"""Библиотека и место, на котором читатель остановился.

Продолжение чтения — первоклассный сценарий (FR-HOME-02): им живут и хиро
главной, и подпись кнопки на странице произведения.
"""

from django.db import IntegrityError, transaction
from django.db.models import OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from ..models import LibraryEntry, ReadingProgress
from ..managers import CHARS_PER_MINUTE, chapter_count_subquery


def progress_chapter_subquery(user_ref: str = 'user', story_ref: str = 'story'):
    """На какой главе читатель — подзапросом, для аннотации `progress_chapter`.

    Нужен полке библиотеки: строка «оқу үстінде» показывает «4 / 12 бөлім».
    Своей колонки у `LibraryEntry` нет — один факт в двух местах однажды
    разошёлся (DEC-52). Без записи — первая глава: работа на полке, но не
    открыта.
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

    `minutes_left` считается по главам **после** текущей: позиции внутри
    главы у нас нет, и прикидывать её долю значило бы выдумывать число.
    `quote` не трогается — сочинять цитату не из чего.

    Сначала UPDATE, вставка — только на ноль задетых строк. Это самое
    частое действие портала, а `update_or_create` стоил бы здесь четырёх
    запросов вместо одного. Гонку двух первых заходов ловит уникальность
    пары «читатель — работа» и дописывает тем же UPDATE.
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


def move_to_shelf(user, story, *, finished: bool) -> None:
    """Автопереход полки по факту чтения (BR-61, FR-LIB-02).

    Начало чтения кладёт работу на «оқу үстінде», прочтение всех глав — на
    «оқылған». Полки не пересекаются, поэтому это перевод, а не вторая
    запись; создаётся она и без кнопки «Сақтау» — на полку попадают по
    факту чтения. Повторное чтение дочитанной возвращает её на «оқу
    үстінде»: строка `done` предлагает «Қайта оқу», и после нажатия она
    обязана описывать то, что происходит.
    """
    kind = 'done' if finished else 'reading'
    if LibraryEntry.objects.filter(user=user, story=story).update(kind=kind):
        return
    try:
        with transaction.atomic():
            LibraryEntry.objects.create(user=user, story=story, kind=kind)
    except IntegrityError:
        LibraryEntry.objects.filter(user=user, story=story).update(kind=kind)


def toggle_library_entry(user, story) -> bool:
    """Кнопка «Сақтау»: работа в библиотеке или нет, отдаёт новое состояние.

    Отвечает на вопрос присутствия, а не выбирает полку — так и подписана,
    и снимает работу с любой. Ручное сохранение кладёт на «сақталған»
    (BR-61); дальше её двигает само чтение.
    """
    entry = LibraryEntry.objects.filter(user=user, story=story).first()
    if entry is not None:
        entry.delete()
        return False
    LibraryEntry.objects.create(user=user, story=story, kind='saved')
    return True


def reading_progress_of(user):
    """Последнее, что читатель не дочитал, или None.

    Одна запись, а не список: «Оқуды жалғастыру» отвечает на «что открыть
    сейчас», и выбор из пяти вариантов — это уже библиотека. Число частей
    едет той же строкой — хиро рисует полосу «3 / 12 бөлім».
    """
    if user is None:
        return None
    progress = (ReadingProgress.objects
                .filter(user=user)
                .select_related('story', 'story__author',
                                'story__primary_genre')
                .annotate(story_chapters=chapter_count_subquery('story'))
                .first())
    if progress is not None:
        progress.story.chapter_count = progress.story_chapters
    return progress
