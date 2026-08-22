"""Шаблонные хелперы Balaproza.

Подключай в шаблоне через {% load balaproza %} — НО: filter `page_range`
автоматически доступен только если шаблон сам его load-ит. Pagination —
системный компонент, потому добавлю там {% load balaproza %} в начало.
"""

from django import template

register = template.Library()


@register.filter(name="compact_count")
def compact_count(value):
    """Компактный счётчик для карточек: 840 → 840, 8920 → 8,9 мың, 12482 → 12 мың.

    На мобильном карточка узкая (138px), полное число просмотров съедает строку
    с автором. Разделитель дробной части — запятая (казахская типографика).

    Ветка выбирается по **округлённому** значению, а не по сырому `n`. Раньше
    9970 попадало в ветку с десятичной (9970 < 10000), округлялось до
    «10,0 мың» и вставало в каталоге рядом с «10 мың» у 10000 — одно и то же
    число в двух формах на одном экране.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return value

    if n < 1000:
        return str(n)

    k = n / 1000
    if round(k, 1) < 10:
        return f"{k:.1f}".replace('.', ',') + " мың"
    # Округление, а не `n // 1000`: усечение вернуло бы «9 мың» ровно для тех
    # значений (9950-9999), ради которых ветка и выбирается по округлённому.
    return f"{round(k)} мың"


@register.filter(name="spaced")
def spaced(value):
    """Разряды через неразрывный пробел: 500000 → 500 000.

    Нужен для сумм в тенге: `stringformat:"d"` выводил «500000» сплошняком.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return value

    return f"{n:,}".replace(',', ' ')


@register.filter(name="belongs_to")
def belongs_to(comment, username):
    """Свой ли это комментарий — для набора пунктов меню (BR-33).

    Фильтр, а не вычисление во view: комментарии вложены (BR-30), и view
    пришлось бы разворачивать нити в плоскую структуру только ради одного
    булева поля. Логика владения живёт в `StoryComment.belongs_to`.
    """
    checker = getattr(comment, "belongs_to", None)
    return bool(checker and checker(username or ""))


@register.filter(name="page_range")
def page_range(total, current):
    """Список номеров страниц для пагинации.
    0 в результате означает «…» (gap).

    Логика:
      total <= 7              → [1..total]
      current близко к началу → [1,2,3,4,5,0,total]
      current близко к концу  → [1,0,total-4,...,total]
      иначе                   → [1,0,current-1,current,current+1,0,total]
    """
    try:
        total = int(total)
        current = int(current)
    except (TypeError, ValueError):
        return []

    if total <= 7:
        return list(range(1, total + 1))

    if current <= 4:
        return [1, 2, 3, 4, 5, 0, total]
    if current >= total - 3:
        return [1, 0, total - 4, total - 3, total - 2, total - 1, total]
    return [1, 0, current - 1, current, current + 1, 0, total]
