"""Лента событий автора (FR-NOTIF-01)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .. import data
from ..links import notification_href
from .common import _current_user, _page_state

# ───────────────────────── NOTIF — уведомления ───────────────────────────
def notifications(request):
    """Список уведомлений с группировкой БҮГІН / КЕШЕ / ӨТКЕН АПТАДА (FR-NOTIF-01)."""
    user = _current_user(request)
    grouped = data.notifications_for_user(user)
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
        'unread_total':  data.unread_count_for_user(user),
    })


@login_required
def notification_open(request, pk):
    """Открыть уведомление: снять «непрочитано» и уйти к его предмету.

    BR-71 говорит, что метку снимает **открытие уведомления**, а не ленты:
    строка, погасшая раньше, чем её прочли, обесценивает бейдж. Адрес
    собирает `notification_href` — тот же, что рисует ссылки в карточке.
    Предмета может не быть (объект удалили): тогда возвращаемся в ленту.
    """
    notification = data.mark_notification_read(request.user, pk)
    if notification is None:
        return redirect('core:notifications')
    return redirect(notification_href(notification) or reverse('core:notifications'))


@require_POST
@login_required
def notifications_read_all(request):
    """«Барлығын оқылды деп белгілеу» — кнопка над лентой (FR-NOTIF-04).

    Была формой с `@submit.prevent` и тостом «(демо)»: бейдж в шапке
    после неё показывал ровно то же число.
    """
    cleared = data.mark_all_notifications_read(request.user)
    if cleared:
        messages.success(request, 'Барлығы оқылды деп белгіленді.')
    return redirect('core:notifications')
