"""Мелочи, общие всем разделам: кто смотрит и в каком состоянии.

Два вопроса, которые задаёт почти каждая страница. Держать их в разделе
(`auth`, `home`) значило бы, что половина модулей импортирует другую
половину ради одной функции.
"""

from django.urls import reverse

# ───────────────────────── DEC-17: демо-состояния ────────────────────────
# Page-state opt-in: ?state=loading или ?state=error превращает страницу
# в скелетон/ошибку. Только для дизайн-обзора — на проде заменится на
# реальные async-загрузки через htmx.
_PAGE_STATES = ('content', 'loading', 'error')


def _page_state(request) -> str:
    st = request.GET.get('state', 'content')
    return st if st in _PAGE_STATES else 'content'


def _current_username(request) -> str:
    """Ник вошедшего или '' у гостя.

    Слой данных принимает ник строкой (docs/19 §19.2), поэтому здесь имя,
    а не объект: переход на объекты — отдельное решение и отдельный проход
    по всем вызовам.
    """
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
