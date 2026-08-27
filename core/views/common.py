"""Мелочи, общие всем разделам: кто смотрит и в каком состоянии.

Два вопроса, которые задаёт почти каждая страница. Держать их в разделе
(`auth`, `home`) значило бы, что половина модулей импортирует другую
половину ради одной функции.
"""

from django.http import Http404
from django.urls import reverse

# ───────────────────────── DEC-17: демо-состояния ────────────────────────
# Page-state opt-in: ?state=loading или ?state=error превращает страницу
# в скелетон/ошибку. Только для дизайн-обзора — на проде заменится на
# реальные async-загрузки через htmx.
_PAGE_STATES = ('content', 'loading', 'error')


def _found_or_404(obj, what: str):
    """Публичный объект или 404.

    Раньше несуществующий slug отдавал 200 с карточкой «табылмады» внутри
    страницы. Отсюда следовали две вещи: каждый шаблон обязан был
    выдерживать `story=None` — ветка на весь файл, — а поисковик
    индексировал любой выдуманный адрес как живую страницу. Профиль отвечал
    404 с первого дня (FR-PROF-02), и разнобой был именно разнобоем.
    """
    if obj is None:
        raise Http404(what)
    return obj


def _page_state(request) -> str:
    st = request.GET.get('state', 'content')
    return st if st in _PAGE_STATES else 'content'


def _current_user(request):
    """Вошедший или `None` у гостя.

    Слой данных принимает пользователя, а не ник: гость — это `None`, и
    каждый хелпер отвечает на него пустотой. Заодно объект несёт снимок
    своих работ (`User.authored` и соседние `cached_property`), поэтому
    страница, которая спрашивает их из восьми мест, платит один запрос.

    `request.user` — один экземпляр на запрос, то есть снимок живёт ровно
    запрос и не переиспользуется между ними.
    """
    return request.user if request.user.is_authenticated else None


def _current_username(request) -> str:
    """Ник вошедшего или '' у гостя — там, где нужна именно строка
    (сравнение с `username` из адреса, `viewer` в шаблоне)."""
    return request.user.username if request.user.is_authenticated else ''


def _safe_next(request, fallback_url: str = ''):
    """Защита от open-redirect: принимаем только относительные пути на нашем хосте.

    Отклоняем абсолютные URL (http://…), protocol-relative (//evil.com/) и пустое.

    `fallback_url` — готовый адрес, куда вернуться без `?next=`. Кнопка
    подписки стоит на двух разных страницах и возвращает на ту, с которой
    нажали; имени маршрута тут мало — у профиля в адресе есть `username`.
    """
    nxt = request.GET.get('next') or request.POST.get('next')
    if nxt and nxt.startswith('/') and not nxt.startswith('//'):
        return nxt
    return fallback_url or reverse('core:home')
