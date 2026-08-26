"""Лента событий автора (FR-NOTIF-01)."""

from django.shortcuts import render

from .. import data
from .common import _current_username, _page_state

# ───────────────────────── NOTIF — уведомления ───────────────────────────
def notifications(request):
    """Список уведомлений с группировкой БҮГІН / КЕШЕ / ӨТКЕН АПТАДА (FR-NOTIF-01)."""
    username = _current_username(request)
    grouped = data.notifications_for_user(username) if username else {}
    has_any = any(grouped.get(b) for b in data.NOTIF_BUCKETS)
    state = _page_state(request)
    # Готовые секции вместо словаря и списка ключей. Django-шаблон не умеет
    # `grouped[b]`, поэтому прежняя разметка обходила это дословной копией
    # блока на каждый бакет с ключом-литералом внутри: `buckets` уезжал в
    # контекст и не читался никем. Порядок задаёт реестр, пустые группы
    # не доезжают — заголовок без строк не рисуется.
    sections = [
        {'key': b, 'label': data.NOTIF_BUCKET_LABELS[b], 'items': grouped[b]}
        for b in data.NOTIF_BUCKETS if grouped.get(b)
    ]
    return render(request, 'pages/notifications.html', {
        'page_state':    state,
        'sections':      sections,
        'has_any':       has_any,
        # Шапка страницы стояла выше ветвления по состоянию и говорила о
        # данных, которых на экране нет: в `?state=error` сводка «4
        # оқылмаған» и кнопка «отметить всё» соседствовали с сообщением
        # о неудачной загрузке (DEC-17).
        'has_data':      state == 'content',
        'unread_total':  data.unread_count_for_user(username) if username else 0,
    })
