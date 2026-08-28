"""Мелочи, общие всем разделам: кто смотрит и в каком состоянии."""

from django.http import Http404
from django.urls import reverse

# ───────────────────────── DEC-17: демо-состояния ────────────────────────
# `?state=loading|error` превращает страницу в скелетон или ошибку. Только
# для дизайн-обзора: на проде это async-загрузки через htmx.
_PAGE_STATES = ('content', 'loading', 'error')


def _found_or_404(obj, what: str):
    """Публичный объект или 404 — как у профиля с первого дня (FR-PROF-02).
    Ответ 200 с карточкой «табылмады» заставлял бы каждый шаблон выдерживать
    `None`, а поисковика — индексировать любой выдуманный адрес."""
    if obj is None:
        raise Http404(what)
    return obj


def _page_state(request) -> str:
    st = request.GET.get('state', 'content')
    return st if st in _PAGE_STATES else 'content'


def _current_user(request):
    """Вошедший или `None` у гостя.

    Объект несёт снимок своих работ (`User.authored` и соседние
    `cached_property`), поэтому страница, спрашивающая их из восьми мест,
    платит один запрос. `request.user` — один экземпляр на запрос, то есть
    снимок живёт ровно запрос.
    """
    return request.user if request.user.is_authenticated else None


def _current_username(request) -> str:
    """Ник вошедшего или '' у гостя — там, где нужна именно строка
    (сравнение с `username` из адреса, `viewer` в шаблоне)."""
    return request.user.username if request.user.is_authenticated else ''


def _safe_next(request, fallback_url: str = ''):
    """Защита от open-redirect: только относительные пути на нашем хосте.

    `fallback_url` — готовый адрес, куда вернуться без `?next=`; имени
    маршрута тут мало, у профиля в адресе есть `username`.
    """
    nxt = request.GET.get('next') or request.POST.get('next')
    if nxt and nxt.startswith('/') and not nxt.startswith('//'):
        return nxt
    return fallback_url or reverse('core:home')
