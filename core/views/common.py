"""Мелочи, общие всем разделам: кто смотрит и в каком состоянии."""

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404
from django.urls import reverse

from .. import data

# ───────────────────────── DEC-17: демо-состояния ────────────────────────
# `?state=loading|error` превращает страницу в скелетон или ошибку. Только
# для дизайн-обзора: на проде это async-загрузки через htmx.
#
# И только при `DEBUG`. Страницы `/_design/` закрыты этой же проверкой с
# первого дня, а переключатель, который их показывает на живом сайте,
# закрыт не был: любой посетитель мог открыть главную с `?state=error` и
# увидеть «жүктеу мүмкін болмады» там, где всё работает.
_PAGE_STATES = ('content', 'loading', 'error')


def _found_or_404(obj, what: str):
    """Публичный объект или 404 — как у профиля с первого дня (FR-PROF-02).
    Ответ 200 с карточкой «табылмады» заставлял бы каждый шаблон выдерживать
    `None`, а поисковика — индексировать любой выдуманный адрес."""
    if obj is None:
        raise Http404(what)
    return obj


def _page_state(request) -> str:
    if not settings.DEBUG:
        return 'content'
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


# Что человек видит, упёршись в предел. Без укоров и без чисел: «не
# больше десяти в минуту» — правило системы, а не его забота.
_TOO_OFTEN = 'Тым жиі. Сәл кідіріп, қайта көр.'


def _throttled(request, action: str) -> bool:
    """Исчерпан ли предел частоты; заодно говорит об этом человеку.

    Проверка стоит во вью, а не в слое записей, потому что отказ у
    каждого действия свой: комментарий возвращается на страницу тостом,
    реакция молча перерисовывает себя прежней. Само правило одно и живёт
    в `queries/throttle`.
    """
    if not data.too_often(action, _current_user(request)):
        return False
    messages.error(request, _TOO_OFTEN)
    return True


# Сколько строк на странице списка — всюду, кроме каталога и разговора
# под главой: у тех свои числа со своими причинами (четыре ряда по пять
# карточек; двадцать верхнеуровневых реплик). Совпадают они случайно, и
# сводить три константы в одну значило бы связать три разных решения.
#
# Списки, которым это нужно: подписчики, очередь модерации, жалобы,
# задержанные комментарии, библиотека, работы в профиле. До этого все
# шесть отдавались целиком, и росли они не у того, кто на них смотрит:
# у автора, которого читают, подписчиков однажды станет тысяча, а очередь
# модерации тяжелеет ровно в тот день, когда с ней не справляются.
LIST_PAGE = 20


def _paged(request, rows, *, per_page: int = LIST_PAGE):
    """Страница списка — та же механика, что у каталога.

    `get_page`, а не `page`: мусор читается первой страницей, слишком
    большое число — последней, и ни то, ни другое не отвечает 404.
    Старая ссылка и опечатка не должны закрывать раздел.

    Принимает выдачу, а не список: `Paginator` нарезает её `LIMIT/OFFSET`,
    то есть до базы доезжает ровно страница. Список сюда тоже придёт —
    но тогда он уже целиком в памяти, и смысла в пагинации нет.
    """
    return Paginator(rows, per_page).get_page(request.GET.get('page'))


def _safe_next(request, fallback_url: str = ''):
    """Защита от open-redirect: только относительные пути на нашем хосте.

    `fallback_url` — готовый адрес, куда вернуться без `?next=`; имени
    маршрута тут мало, у профиля в адресе есть `username`.
    """
    nxt = request.GET.get('next') or request.POST.get('next')
    if nxt and nxt.startswith('/') and not nxt.startswith('//'):
        return nxt
    return fallback_url or reverse('core:home')
