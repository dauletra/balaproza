"""Библиотека читателя: три полки (FR-LIB-01..03)."""

from django.shortcuts import render
from django.urls import reverse

from .common import _current_user, _page_state

# ───────────────────────── LIB — библиотека ──────────────────────────────
_LIB_TABS = ("saved", "reading", "done")


_LIB_LABELS = {
    "saved":   "Сақталған",
    "reading": "Оқу үстіндегі",
    "done":    "Оқылғаны",
}


def library(request):
    """Библиотека читателя с тремя вкладками (FR-LIB-01..03).

    Реальное переключение через ?tab=saved|reading|done. Каждая вкладка
    рисует свои элементы; «Оқу үстіндегі» добавляет «Жалғастыру».
    """
    user = _current_user(request)
    tab = request.GET.get('tab', 'saved')
    if tab not in _LIB_TABS:
        tab = 'saved'
    # Полки режутся из одной выборки. Раньше вкладка стоила запроса, и
    # счётчики в сегментах добавляли ещё три — четыре выборки одной и той
    # же библиотеки ради трёх чисел над ней.
    entries = user.shelf(tab) if user else []
    items = [
        {
            'slug':  t,
            'label': _LIB_LABELS[t],
            'count': len(user.shelf(t)) if user else 0,
        }
        for t in _LIB_TABS
    ]
    return render(request, 'pages/library.html', {
        'page_state':   _page_state(request),
        'tab':          tab,
        'lib_items':    items,
        'entries':      entries,
        'catalog_href': reverse('core:catalog'),
    })
