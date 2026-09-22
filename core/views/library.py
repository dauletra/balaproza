"""Библиотека читателя: три полки (FR-LIB-01..03)."""

from django.shortcuts import render
from django.urls import reverse

from .. import data
from .common import LIST_PAGE, _current_user, _page_state

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

    # Числа над вкладками — одним `GROUP BY`, страница полки — отдельной
    # выборкой. Раньше и то и другое брали `len()` по библиотеке,
    # прочитанной целиком: три числа стоили того, что у читателя со
    # временем накапливается сотнями.
    counts = data.library_counts(user)
    total = counts.get(tab, 0)
    pages = max(1, -(-total // LIST_PAGE))
    raw = request.GET.get('page', '')
    number = min(max(int(raw) if raw.isdigit() else 1, 1), pages)

    entries = (data.library_of(user, tab, offset=(number - 1) * LIST_PAGE,
                               limit=LIST_PAGE) if user else [])
    items = [
        {'slug': t, 'label': _LIB_LABELS[t], 'count': counts.get(t, 0)}
        for t in _LIB_TABS
    ]
    return render(request, 'pages/library.html', {
        'page_state':   _page_state(request),
        'tab':          tab,
        'lib_items':    items,
        'entries':      entries,
        'lib_page':     number,
        'lib_pages':    pages,
        # Компоненту нужен путь без query; вкладка едет с ним, иначе
        # вторая страница «Оқылғаны» открывала бы «Сақталған».
        'page_base':    request.path,
        'page_qs':      f'tab={tab}',
        'catalog_href': reverse('core:catalog'),
    })
