"""Каталог, поиск, жанры, теги и жинақтар.

Один движок на три режима: `/genres/<slug>/`, `/tag/<slug>/` и `/catalog/`.
Поиск — не отдельный режим, а обычный `?q=`
на `/catalog/`: до публичного запуска отдельная entry-страница ради SEO не
стоила двух копий одного движка и разного chrome вокруг одной и той же
выдачи. `/search/` остаётся рабочим адресом — редиректом на `/catalog/`.

Комбинации осей едут в query, но путь всегда сильнее — канонический адрес
остаётся источником истины.

Состояние выбора и адреса — в `links.CatalogState`; здесь остаётся разбор
запроса, выбор пустого экрана и рендер.
"""

from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.urls import reverse

from .. import data
from ..links import CATALOG_AXES, FILTER_GROUPS, CatalogState, catalog_links
from .common import _current_user, _found_or_404

# Что показывать вместо списка. Заголовок и текст зависят от режима: «ничего
# не найдено» на пустом жанре звучит как поломка, хотя это просто новый жанр.
_EMPTY = {
    'genre':   ("Әзірге шығарма жоқ",
                "Бұл жанрда әлі шығарма жарияланбаған."),
    'tag':     ("Бұл тегпен шығарма жоқ",
                "Басқа тегті көр немесе сүзгіні өзгерт."),
    'catalog': ("Шығарма табылмады", "Сүзгіні өзгертіп көр."),
}

# Сколько карточек на страницу: двадцать — четыре полных ряда по пять, то
# есть экран с небольшим запасом на прокрутку.
PAGE_SIZE = 20


def _accepted_tag(slug: str):
    """Тег, если он есть и прошёл модератора."""
    tag = data.tag_by_slug(slug) if slug else None
    return tag if (tag and tag.status == 'accepted') else None


def _render_catalog(request, *, mode: str, genre_slug: str = '', tag_slug: str = ''):
    """Единая точка рендера унифицированного каталога."""
    genre = data.genre_by_slug(genre_slug) if genre_slug else None
    tag = _accepted_tag(tag_slug)
    if mode == 'genre':
        _found_or_404(genre, f'Жанр «{genre_slug}» табылмады')
    if mode == 'tag':
        # Pending-тег публично не существует — тот же ответ,
        # что у выдуманного слага. Автору объяснять нечего: у его
        # собственного тега чип не ссылка, а подпись «проверкада».
        _found_or_404(tag, f'Тег «{tag_slug}» табылмады')

    # Вторая ось приходит query-параметром — но только если путь эту ось
    # не занял. Раньше код этот параметр не читал и терял его.
    eff_genre = genre_slug if genre else ''
    if not eff_genre:
        candidate = request.GET.get('genre', '')
        eff_genre = candidate if data.genre_by_slug(candidate) else ''
    eff_tag = tag_slug if tag else ''
    if not eff_tag:
        candidate = _accepted_tag(request.GET.get('tag', ''))
        eff_tag = candidate.slug if candidate else ''

    state = CatalogState.from_request(request, mode=mode,
                                      genre=eff_genre, tag=eff_tag)

    results = data.filter_catalog(query=state.query, genre=state.genre,
                                  tag=state.tag, sort=state.effective_sort,
                                  viewer=_current_user(request), **state.axes)
    # Пустой экран запроса — про сам запрос, а не про раздел: «в жанре пока
    # ничего» и «по твоим словам ничего» звучат по-разному, даже когда оба
    # случая пришли с одного и того же /catalog/.
    if state.query:
        empty_title = "Ештеңе табылмады"
        empty_text = (f"«{state.query}» бойынша шығарма табылмады. "
                      f"Атауын тексеріп көр.")
    else:
        empty_title, empty_text = _EMPTY.get(mode, _EMPTY['catalog'])

    # Мусор и выход за границы — первая страница, а не 404: `?page=99` это
    # старая ссылка или опечатка, и каталог обязан открыться.
    paginator = Paginator(results, PAGE_SIZE)
    page = paginator.get_page(request.GET.get('page'))

    sort = state.effective_sort
    ctx = {
        'has_right_rail': True,
        'mode':           mode,
        # Адрес, под которым эту выдачу стоит знать поисковику, и признак
        # «эта — не стоит». Шесть осей плюс страницы давали комбинаторно
        # много адресов с почти тем же содержимым, и на молодом домене
        # краулер тратил обход на них вместо работ. Страница считается
        # сужением наравне с осями — она и есть первая, которая плодится.
        'canonical':      state.canonical_href,
        'narrowed':       state.is_narrowed or page.number > 1,
        'results':        page.object_list,
        # Число под шапкой — про всю выдачу, а не про эту страницу:
        # «20 шығарма» на первой странице из трёх было бы неправдой.
        'total_results':  paginator.count,
        'page':           page,
        'page_base':      state.page_base,
        'page_qs':        state.page_qs,
        'query':          state.query,
        'sort':           sort,
        'sort_label':     dict(data.CATALOG_SORTS).get(sort, ''),
        'sorts':          data.CATALOG_SORTS,
        # Сортировки здесь больше нет (см. links.FILTER_GROUPS) — она своя
        # кнопка над списком, а не пункт этого цикла.
        'filter_groups': [
            {'name': name, 'legend': legend, 'options': dict(CATALOG_AXES)[name],
             'current': getattr(state, name)}
            for name, legend in FILTER_GROUPS
        ],
        'genres':             data.all_genres(),
        'current_genre_slug': state.genre,
        'genre':              genre,
        'current_tag_slug':   state.tag,
        'current_tag':        tag or _accepted_tag(state.tag),
        # `popular_tags` здесь не отдаётся: чипы тегов панели приходят
        # готовыми ссылками в `tag_options`, и второй список тех же тегов ни
        # один шаблон каталога не читает.
        # Жинақтар нужны ровно там, где сүзгі не дали результата:
        # пустой экран не должен быть тупиком с выходом только назад.
        'rail_collections':   data.all_collections()[:3],
        'empty_title':        empty_title,
        'empty_text':         empty_text,
    }
    # Отдельные ключи осей шаблон читает по имени (`{{ kind }}`) — панель
    # отмечает ими выбранное radio.
    ctx.update(state.axes)
    ctx.update(catalog_links(state))
    return render(request, 'pages/catalog/catalog.html', ctx)



def search_results(request):
    """Legacy-адрес: /search/?q=... живёт редиректом на /catalog/
    с тем же querystring — старые ссылки и закладки не 404, а просто ведут
    туда же, куда теперь ведёт и шапка.

    `request.GET.urlencode()`, а не сырой `META['QUERY_STRING']`: последний
    в WSGI-environ — latin1-строка из голых байт, и склеенный как есть в
    Location-заголовок, он уходит через `iri_to_uri` на повторное
    percent-encoding — non-ASCII запрос долетает битым. `GET` уже разобран
    Django правильно, `urlencode()` кодирует по новой ровно один раз."""
    qs = request.GET.urlencode()
    target = reverse('core:catalog')
    return redirect(f'{target}?{qs}' if qs else target)


def catalog(request):
    """Нейтральная entry-страница каталога. URL: /catalog/"""
    return _render_catalog(request, mode='catalog')


def genre_index(request):
    # Счётчики жанров считаются, а не хранятся, поэтому список берётся
    # один раз: второй вызов — второй запрос с теми же агрегатами.
    genres = data.all_genres()
    return render(request, 'pages/catalog/genre_index.html', {
        'genres':        genres,
        # Число работ — то же, что в хиро главной, а не сумма по жанрам:
        # работа с основным и дополнительным жанром стоит в двух карточках,
        # и сумма считала её дважды — «32 шығарма» при 21 в каталоге.
        'total_stories': data.portal_stats()['stories'],
    })


def genre_detail(request, slug):
    return _render_catalog(request, mode='genre', genre_slug=slug)


def tag_detail(request, slug):
    """Каталог по UGC-тегу (docs/ui.md). URL: /tag/<slug>/"""
    return _render_catalog(request, mode='tag', tag_slug=slug)


def collections(request):
    return render(request, 'pages/catalog/collections.html', {
        'collections': data.all_collections(),
    })


def collection_detail(request, slug):
    collection = _found_or_404(data.collection_by_slug(slug),
                               f'Жинақ «{slug}» табылмады')
    return render(request, 'pages/catalog/collection_detail.html', {
        'slug':       slug,
        'collection': collection,
    })
