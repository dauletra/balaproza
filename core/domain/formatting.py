"""Как проект записывает даты, числа и «сколько времени назад».

Три формулировки, у каждой по одной реализации на весь проект: второй
экземпляр любой из них разошёлся бы с первым.
"""

from datetime import date
from typing import Optional

# Сокращения месяцев для дат конкурса: «10 қаз — 5 жел».
KK_MONTHS_SHORT = ("қаң", "ақп", "нау", "сәу", "мам", "мау",
                   "шіл", "там", "қыр", "қаз", "қар", "жел")


def kk_date(d: date) -> str:
    """«5 желтоқсан» в короткой форме — «5 жел»."""
    return f"{d.day} {KK_MONTHS_SHORT[d.month - 1]}"


def kk_period(starts: date, ends: date) -> str:
    """Диапазон дат одной строкой; однодневный этап — просто дата."""
    return kk_date(starts) if starts == ends else f"{kk_date(starts)} — {kk_date(ends)}"


def kk_ago(days: int, hours: Optional[int] = None,
           minutes: Optional[int] = None) -> str:
    """«Сколько времени назад» словами — одна формулировка на весь проект.

    Часы называются только сегодня: «26 сағат бұрын» человек в уме
    переводит в дни, и «кеше» короче. Минуты — только в пределах часа, и
    нужны они одному месту: под свежей главой комментарий, написанный
    сорок минут назад, «бүгін» описывает бесполезно.
    """
    if days <= 0:
        if not hours and minutes:
            return f"{minutes} мин бұрын"
        if hours:
            return f"{hours} сағат бұрын"
        return "бүгін"
    if days == 1:
        return "кеше"
    if days < 30:
        return f"{days} күн бұрын"
    if days < 365:
        return f"{days // 30} ай бұрын"
    return f"{days // 365} жыл бұрын"


def kk_updated(days: Optional[int]) -> str:
    """«Когда автор трогал работу»: «кеше», «3 күн бұрын», «2 апта бұрын».

    Своя лесенка, а не `kk_ago`, и разница ровно в одном делении — неделях.
    У события неделя ничего не добавляет: важно «вчера» или «давно». У
    своей работы она и есть главная единица — «две недели назад» отвечает
    на «я это забросил?», а «14 күн бұрын» заставляет считать в уме.
    """
    if days is None:
        return ""
    if days <= 0:
        return "бүгін"
    if days == 1:
        return "кеше"
    if days < 7:
        return f"{days} күн бұрын"
    if days < 30:
        return f"{days // 7} апта бұрын"
    return f"{days // 30} ай бұрын"


def spaced_number(value) -> str:
    """Разряды через неразрывный пробел: 500000 -> «500 000».

    Канонический вид числа для автора. Здесь, а не в фильтре
    `balaproza.spaced`: те же числа собираются на стороне данных, в
    подсказках `submission_checklist`, и фильтр зовёт эту же функцию.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return value
    return f"{n:,}".replace(",", " ")
