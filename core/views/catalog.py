"""Каталог, поиск, жанры, теги и жинақтар (DEC-27, DEC-36).

Один движок на четыре режима: `/search/`, `/genres/<slug>/`, `/tag/<slug>/`
и `/catalog/`. Канонические URL сохранены, комбинации осей едут в query
(`/genres/triller/?tag=mektep`); путь всегда сильнее query — канонический
адрес остаётся источником истины.

Состояние выбора живёт в `links.CatalogState`, и адреса строит он же:
здесь остаётся разбор запроса, выбор пустого экрана и рендер.
"""

from django.core.paginator import Paginator
from django.shortcuts import render

from .. import data
from ..links import CATALOG_AXES, FILTER_GROUPS, CatalogState, catalog_links
from .common import _found_or_404

# Что показывать вместо списка. Заголовок и текст зависят от режима: «ничего
# не найдено» на пустом жанре звучит как поломка, хотя это просто новый жанр.
_EMPTY = {
    'genre':   ("Әзірге шығарма жоқ",
                "Бұл жанрда әлі шығарма жарияланбаған."),
    'tag':     ("Бұл тегпен шығарма жоқ",
                "Басқа тегті көр немесе сүзгіні өзгерт."),
    'catalog': ("Шығарма табылмады", "Сүзгіні өзгертіп көр."),
}

# Сколько карточек на страницу. Двадцать — четыре полных ряда по пять
# (сетка держится `test_desktop_layout`), то есть экран с небольшим
# запасом на прокрутку. До этого каталог отдавал **всю** публичную выдачу
# разом: на двадцати трёх работах незаметно, на десяти тысячах это полная
# выборка со всеми join'ами в одном ответе (NFR-13).
PAGE_SIZE = 20

# Поиск без запроса — не «ничего не найдено», а «ещё не искали».
_SEARCH_IDLE = ("Не іздейміз?",
                "Шығарманың атауын немесе автордың атын жаз. "
                "Жанр бойынша іздесең — жанрлар бетіне өт.")


def _accepted_tag(slug: str):
    """Тег, если он есть и прошёл модератора (BR-TAG-07)."""
    tag = data.tag_by_slug(slug) if slug else None
    return tag if (tag and tag.status == 'accepted') else None


def _render_catalog(request, *, mode: str, genre_slug: str = '', tag_slug: str = ''):
    """Единая точка рендера унифицированного каталога (DEC-27)."""
    genre = data.genre_by_slug(genre_slug) if genre_slug else None
    tag = _accepted_tag(tag_slug)
    if mode == 'genre':
        _found_or_404(genre, f'Жанр «{genre_slug}» табылмады')
    if mode == 'tag':
        # Pending-тег для публики не существует (BR-TAG-07), и это тот же
        # ответ, что у выдуманного слага. Автору объяснять здесь нечего: у
        # его собственного тега чип не ссылка, а подпись «проверкада».
        _found_or_404(tag, f'Тег «{tag_slug}» табылмады')

    # Вторая ось приходит query-параметром — но только если путь эту ось
    # не занял. DEC-27 это описывал, а код параметр не читал и терял его.
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

    if mode == 'search' and not state.query:
        results, (empty_title, empty_text) = [], _SEARCH_IDLE
    else:
        results = data.filter_catalog(query=state.query, genre=state.genre,
                                      tag=state.tag, sort=state.effective_sort,
                                      **state.axes)
        if mode == 'search':
            empty_title = "Ештеңе табылмады"
            empty_text = (f"«{state.query}» бойынша шығарма табылмады. "
                          f"Атауын тексеріп көр.")
        else:
            empty_title, empty_text = _EMPTY.get(mode, _EMPTY['catalog'])

    # Номер страницы из запроса. Мусор и выход за границы — первая
    # страница, а не 404: `?page=99` это старая ссылка или опечатка, и
    # каталог обязан открыться.
    paginator = Paginator(results, PAGE_SIZE)
    page = paginator.get_page(request.GET.get('page'))

    sort = state.effective_sort
    ctx = {
        'has_right_rail': True,
        'mode':           mode,
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
        'filter_groups': [
            {'name': name, 'legend': legend,
             'options': data.CATALOG_SORTS if name == 'sort'
                        else dict(CATALOG_AXES)[name],
             'current': sort if name == 'sort' else getattr(state, name)}
            for name, legend in FILTER_GROUPS
        ],
        'genres':             data.all_genres(),
        'current_genre_slug': state.genre,
        'genre':              genre,
        'current_tag_slug':   state.tag,
        'current_tag':        tag or _accepted_tag(state.tag),
        # `popular_tags` здесь не отдаётся: чипы тегов панели приходят
        # готовыми ссылками в `tag_options` из `catalog_links`, и второй
        # список тех же тегов ни один шаблон каталога не читал — он стоил
        # запроса на каждую страницу раздела и молчал об этом.
        # Жинақтар — первичный вход в чтение (DEC-31). В каталоге они нужны
        # ровно там, где сүзгі не дали результата: пустой экран не должен быть
        # тупиком, из которого выход только назад.
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
    return _render_catalog(request, mode='search')


def catalog(request):
    """Нейтральная entry-страница каталога. URL: /catalog/"""
    return _render_catalog(request, mode='catalog')


def genre_index(request):
    # Счётчики жанров считаются, а не хранятся, поэтому список берётся
    # один раз: второй вызов — второй запрос с теми же агрегатами.
    genres = data.all_genres()
    return render(request, 'pages/catalog/genre_index.html', {
        'genres':        genres,
        'total_stories': sum(g.count for g in genres),
    })


def genre_detail(request, slug):
    return _render_catalog(request, mode='genre', genre_slug=slug)


def tag_detail(request, slug):
    """Каталог по UGC-тегу (docs/ui.md Phase 3, DEC-26+27). URL: /tag/<slug>/"""
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
