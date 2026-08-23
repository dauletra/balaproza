"""Библиотека и место, на котором читатель остановился.

Продолжение чтения — первоклассный сценарий (FR-HOME-02): им живут и
хиро главной, и подпись кнопки на странице произведения. Поэтому прогресс
спрашивается по человеку, а не берётся единственным демо-объектом, как в
стабе.
"""

from ..models import ReadingProgress


def reading_progress_of(username: str):
    """Последнее, что читатель не дочитал, или None.

    Одна запись, а не список: «Оқуды жалғастыру» отвечает на «что открыть
    сейчас», и выбор из пяти вариантов — это уже библиотека.
    """
    if not username:
        return None
    return (ReadingProgress.objects
            .filter(user__username=username)
            .select_related('story', 'story__author', 'story__primary_genre')
            .first())
