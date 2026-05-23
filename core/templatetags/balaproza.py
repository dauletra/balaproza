"""Шаблонные хелперы Balaproza.

Подключай в шаблоне через {% load balaproza %} — НО: filter `page_range`
автоматически доступен только если шаблон сам его load-ит. Pagination —
системный компонент, потому добавлю там {% load balaproza %} в начало.
"""

from django import template

register = template.Library()


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
