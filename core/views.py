from urllib.parse import urlencode

from django.conf import settings
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import data


# ───────────────────────── DEC-17: демо-состояния ────────────────────────
# Page-state opt-in: ?state=loading или ?state=error превращает страницу
# в скелетон/ошибку. Только для дизайн-обзора — на проде заменится на
# реальные async-загрузки через htmx.
_PAGE_STATES = ('content', 'loading', 'error')


def _page_state(request) -> str:
    st = request.GET.get('state', 'content')
    return st if st in _PAGE_STATES else 'content'


# HOME
def home(request):
    """Главная — редакционная витрина. Гость vs возвращающийся (FR-HOME-01)."""
    is_signed_in = bool(request.session.get('signed_in'))
    username = request.session.get('user_username') if is_signed_in else None
    my_stories = data.my_stories_of(username) if username else []
    active_work = next((s for s in my_stories if s.status == 'OnProcess'), my_stories[0] if my_stories else None)
    progress = data.reading_progress_of(username) if is_signed_in else None

    # Design-system demo override for the four authenticated hero states.
    hero_state_demo = request.GET.get('hero_state')
    if is_signed_in and hero_state_demo in {'empty', 'reading', 'writing', 'full'}:
        if hero_state_demo == 'empty':
            progress = None
            active_work = None
        elif hero_state_demo == 'reading':
            active_work = None
        elif hero_state_demo == 'writing':
            progress = None

    if not is_signed_in:
        hero_focus = 'guest'
    elif active_work:
        hero_focus = 'writing'
    elif progress:
        hero_focus = 'reading'
    else:
        hero_focus = 'empty'

    # Не литерал 'Published': после DEC-37 опубликованный сериал носит
    # OnProcess или Completed, и по литералу с главной пропали бы все десять.
    published = list(data.public_stories())

    # Жанры на главной — полоса-вывеска, а не навигация (DEC-31): 12 цветных слов
    # объясняют, что это литературный портал, и ведут на /genres/<slug>/.
    # Скроллер произведений активного жанра убран вместе с ?genre= — его работу
    # делают жинақтар и тематические ряды.

    return render(request, 'pages/home.html', {
        'has_right_rail':  True,
        'page_state':      _page_state(request),
        'progress':        progress,
        'active_work':     active_work,
        'hero_focus':      hero_focus,
        'hero_contest':    data.hero_contest(),
        'collections':     data.all_collections(),
        'genres':          data.all_genres(),
        'book_of_week':    data.book_of_week(),
        'new_authors':     data.new_authors(4),
        'top_stories':     sorted(published, key=lambda s: s.views, reverse=True)[:5],
        'short_stories':   [s for s in published if s.is_single and s.read_minutes <= 15][:5],
        # Ряд называется «Жалғасып жатқан шығармалар» — значит именно те,
        # что продолжаются, а не все сериалы подряд.
        'serial_stories':  [s for s in published
                            if s.is_serial and s.status == 'OnProcess'][:5],
        'portal_stats':    data.portal_stats(),
        'popular_tags':    data.popular_tags(8),
        'trending_tags':   data.trending_tags(6),
        'school_links':    data.SCHOOL_LINKS,
    })


# ───────────────────────── AUTH (фейк-сессия) ─────────────────────────
# Простой переключатель «гость ↔ авторизованный» для проверки дизайна.
# Никаких моделей: только session['signed_in'].

def _safe_next(request, fallback='core:home'):
    """Защита от open-redirect: принимаем только относительные пути на нашем хосте.

    Отклоняем абсолютные URL (http://…), protocol-relative (//evil.com/) и пустое.
    """
    nxt = request.GET.get('next') or request.POST.get('next')
    if nxt and nxt.startswith('/') and not nxt.startswith('//'):
        return nxt
    return reverse(fallback)


def login_view(request):
    if request.method == 'POST':
        request.session['signed_in'] = True
        request.session['user_name'] = 'Айдана'
        request.session['user_username'] = 'aidana'
        return HttpResponseRedirect(_safe_next(request))
    return render(request, 'pages/auth/login.html', {'next': request.GET.get('next', '')})


@require_POST
def logout_view(request):
    request.session.pop('signed_in', None)
    request.session.pop('user_name', None)
    request.session.pop('user_username', None)
    return redirect('core:home')


def signup(request):
    if request.method == 'POST':
        request.session['signed_in'] = True
        request.session['user_name'] = request.POST.get('name') or 'Айдана'
        request.session['user_username'] = 'aidana'
        return redirect('core:signup_success')
    return render(request, 'pages/auth/signup.html')


def signup_success(request):
    return render(request, 'pages/auth/signup_success.html')


# ───────────────────────── CAT — каталог и поиск ─────────────────────────
def _catalog_default_sort(mode: str) -> str:
    """Дефолтная сортировка режима.

    Каталог, жанр и поиск открываются «Қазір танымал» — окном в 14 дней
    (DEC-36). Тег остаётся на «Жаңалары»: DEC-31 отдал ему роль самой быстрой
    оси портала, и там ценна свежесть сама по себе, а не набранные просмотры.
    """
    return 'recent' if mode == 'tag' else data.CATALOG_DEFAULT_SORT


def _catalog_controls(request, default_sort=None):
    """Достаёт оси сүзгі из GET с валидацией по белым спискам."""
    default_sort = default_sort or data.CATALOG_DEFAULT_SORT
    axes = {
        'status':   data.CATALOG_STATUS_FILTERS,
        'audience': data.CATALOG_AUDIENCE_FILTERS,
        'length':   data.CATALOG_LENGTH_FILTERS,
        'format':   data.CATALOG_FORMAT_FILTERS,
        'badge':    data.CATALOG_BADGE_FILTERS,
        'author_tier': data.CATALOG_AUTHOR_FILTERS,
        'kind':     data.CATALOG_KIND_FILTERS,
    }
    valid_sorts = {k for k, _ in data.CATALOG_SORTS}
    sort = request.GET.get('sort', default_sort)
    picked = {
        name: (request.GET.get(name, '')
               if request.GET.get(name, '') in {k for k, _ in table} else '')
        for name, table in axes.items()
    }
    return (
        sort if sort in valid_sorts else default_sort,
        picked['status'], picked['audience'], picked['length'],
        picked['format'], picked['badge'], picked['author_tier'],
        picked['kind'],
    )


def _catalog_href(*, mode='catalog', genre='', tag='', query='', sort='',
                  status='', audience='', length='', format='', badge='',
                  author_tier='', kind=''):
    """Канонический URL каталога с сохранением остального состояния (DEC-27).

    Путь выбирает «главная» ось: жанр → /genres/<slug>/, иначе тег →
    /tag/<slug>/, иначе режим страницы. Всё остальное едет в query. До этого
    чипы жанра и тега вели на голый путь, и выбор жанра молча сбрасывал уже
    выставленные жас/формат/оқу уақыты.

    `sort` пустой означает «дефолт целевой страницы»: ссылка на тег из каталога
    не должна тащить туда popularity и ломать DEC-31.
    """
    params = {}
    if genre:
        path = reverse('core:genre_detail', kwargs={'slug': genre})
        params['tag'] = tag
        target_mode = 'genre'
    elif tag:
        path = reverse('core:tag_detail', kwargs={'slug': tag})
        target_mode = 'tag'
    elif mode == 'search':
        path = reverse('core:search_results')
        target_mode = 'search'
    else:
        path = reverse('core:catalog')
        target_mode = 'catalog'

    params.update({'q': query, 'status': status, 'audience': audience,
                   'length': length, 'format': format, 'badge': badge,
                   'author_tier': author_tier, 'kind': kind})
    if sort and sort != _catalog_default_sort(target_mode):
        params['sort'] = sort

    qs = urlencode({k: v for k, v in params.items() if v})
    return f'{path}?{qs}' if qs else path


def _catalog_links(state: dict) -> dict:
    """Ссылки-состояния каталога: активные чипы, жанры, теги, сброс.

    Собираются во view, а не в шаблоне: каждая ссылка — это «текущее состояние
    минус одна ось», а такой URL шаблонными средствами не построить.
    """
    def href(**over):
        return _catalog_href(**{**state, **over})

    presets = _catalog_presets(state, href)

    # Оси, которые уже показаны активным пресетом, отдельными чипами не
    # дублируем: «Бір отырыста» и рядом «Бір бөлімді» + «15 минутқа дейін» —
    # это один и тот же выбор, показанный трижды.
    covered = set()
    for preset in presets:
        if preset['active']:
            covered = set(preset['axes'])

    chips = []
    if state['query']:
        chips.append({'label': f'«{state["query"]}»', 'href': href(query='')})
    if state['genre']:
        g = data.genre_by_slug(state['genre'])
        chips.append({'label': g.name, 'hue': g.hue, 'href': href(genre='')})
    if state['tag']:
        t = data.tag_by_slug(state['tag'])
        chips.append({'label': f'#{t.name}', 'href': href(tag='')})
    for axis, table in (('kind',      data.CATALOG_KIND_FILTERS),
                        ('author_tier', data.CATALOG_AUTHOR_FILTERS),
                        ('badge',    data.CATALOG_BADGE_FILTERS),
                        ('status',   data.CATALOG_STATUS_FILTERS),
                        ('format',   data.CATALOG_FORMAT_FILTERS),
                        ('audience', data.CATALOG_AUDIENCE_FILTERS),
                        ('length',   data.CATALOG_LENGTH_FILTERS)):
        if state[axis] and axis not in covered:
            chips.append({'label': dict(table)[state[axis]],
                          'href': href(**{axis: ''})})

    # «Тазалау» снимает сүзгі, но не выкидывает из раздела: с /genres/triller/
    # уходить в общий каталог человек не просил. Выход из жанра — крестик на чипе.
    if state['mode'] == 'genre' and state['genre']:
        clear_href = _catalog_href(mode='genre', genre=state['genre'])
    elif state['mode'] == 'tag' and state['tag']:
        clear_href = _catalog_href(mode='tag', tag=state['tag'])
    elif state['mode'] == 'search':
        clear_href = _catalog_href(mode='search', query=state['query'])
    else:
        clear_href = _catalog_href(mode='catalog')

    # Бейдж на кнопке считает реально включённые оси, а не показанные чипы:
    # внутри панели галочки пресета видны как обычные radio, и число обязано
    # совпадать с тем, что там отмечено.
    axis_names = ('query', 'genre', 'tag', 'kind', 'badge', 'status',
                  'format', 'audience', 'length', 'author_tier')
    return {
        'active_chips': chips,
        'active_count': sum(1 for a in axis_names if state[a]),
        'clear_href':   clear_href,
        'genre_options': [
            {'genre': g, 'active': g.slug == state['genre'],
             'href': href(genre='' if g.slug == state['genre'] else g.slug)}
            for g in data.all_genres()
        ],
        'tag_options': [
            {'tag': t, 'active': t.slug == state['tag'],
             'href': href(tag='' if t.slug == state['tag'] else t.slug)}
            for t in data.popular_tags(8)
        ],
        'presets': presets,
    }


def _catalog_presets(state: dict, href) -> list:
    """Пресеты «Не оқимын?» — готовые комбинации осей одним тапом.

    Считаем каждому пресету реальный размер выборки: чип, ведущий в пустоту,
    хуже отсутствующего чипа. Счёт берётся в текущем разделе (жанр/тег/запрос
    сохраняются), поэтому «Бір отырыста» внутри жанра честно показывает,
    сколько коротких историй есть именно там.
    """
    out = []
    for preset in data.CATALOG_PRESETS:
        axes = {'format': '', 'length': '', 'status': '', 'badge': '',
                'author_tier': '', 'kind': ''}
        axes.update(preset['filters'])
        active = all(state[k] == v for k, v in axes.items())
        count = len(data.filter_catalog(
            query=state['query'], genre=state['genre'], tag=state['tag'], **axes))
        if not count and not active:
            continue
        out.append({
            'slug':   preset['slug'],
            'label':  preset['label'],
            'count':  count,
            'active': active,
            'axes':   tuple(preset['filters']),
            # Повторный тап по активному пресету снимает его — иначе выйти из
            # пресета можно было бы только через чипы отдельных осей.
            'href':   href(**{k: '' for k in axes}) if active else href(**axes),
        })
    return out


def _render_catalog(request, *, mode: str, genre_slug: str = '', tag_slug: str = ''):
    """Единая точка рендера унифицированного каталога (DEC-27).

    Используется search_results / catalog / genre_detail / tag_detail.
    Вторая ось приходит query-параметром (`/genres/triller/?tag=mektep`) —
    DEC-27 это описывал, но код параметр не читал и молча его терял.
    Путь всегда сильнее query: канонический URL остаётся источником истины.
    """
    query = request.GET.get('q', '').strip()
    (sort, status, audience, length, format, badge, author_tier,
     kind) = _catalog_controls(
        request, default_sort=_catalog_default_sort(mode),
    )

    genre = data.genre_by_slug(genre_slug) if genre_slug else None
    tag = data.tag_by_slug(tag_slug) if tag_slug else None
    not_found = ((mode == 'genre' and genre is None)
                 or (mode == 'tag' and (tag is None or tag.status != 'accepted')))

    # Вторая ось из query — только если путь эту ось не занял.
    eff_genre = genre_slug if genre else ''
    if not eff_genre:
        candidate = request.GET.get('genre', '')
        eff_genre = candidate if data.genre_by_slug(candidate) else ''
    eff_tag = tag_slug if (tag and tag.status == 'accepted') else ''
    if not eff_tag:
        candidate = data.tag_by_slug(request.GET.get('tag', ''))
        eff_tag = candidate.slug if candidate and candidate.status == 'accepted' else ''

    empty_title, empty_text = "Шығарма табылмады", "Сүзгіні өзгертіп көр."
    if not_found:
        results = []
        empty_title = empty_text = ''
    elif mode == 'search' and not query:
        # Idle — без запроса не запускаем фильтр
        results = []
        empty_title = "Не іздейміз?"
        empty_text = (
            "Шығарманың атауын немесе автордың атын жаз. "
            "Жанр бойынша іздесең — жанрлар бетіне өт."
        )
    else:
        results = data.filter_catalog(query=query, genre=eff_genre, tag=eff_tag,
                                           status=status, sort=sort,
                                           audience=audience, length=length,
                                           format=format, badge=badge,
                                           author_tier=author_tier, kind=kind)
        if mode == 'genre':
            empty_title = "Әзірге шығарма жоқ"
            empty_text = "Бұл жанрда әлі шығарма жарияланбаған."
        elif mode == 'tag':
            empty_title = "Бұл тегпен шығарма жоқ"
            empty_text = "Басқа тегті көр немесе сүзгіні өзгерт."
        elif mode == 'search':
            empty_title = "Ештеңе табылмады"
            empty_text = f"«{query}» бойынша шығарма табылмады. Атауын тексеріп көр."

    # sort в ссылках несём только когда он выбран явно: иначе переход на тег из
    # каталога тащил бы туда «Қазір танымал» и отменял «жаңалары вперёд» (DEC-31).
    state = {
        'mode': mode, 'genre': eff_genre, 'tag': eff_tag, 'query': query,
        'sort': sort if 'sort' in request.GET else '',
        'status': status, 'audience': audience, 'length': length,
        'format': format, 'badge': badge, 'author_tier': author_tier,
        'kind': kind,
    }

    sort_labels = dict(data.CATALOG_SORTS)
    ctx = {
        'has_right_rail': True,
        'mode':           mode,
        'results':        results,
        'query':          query,
        'sort':           sort,
        'sort_label':     sort_labels.get(sort, ''),
        'sorts':          data.CATALOG_SORTS,
        'status':         status,
        'audience':       audience,
        'length':         length,
        'format':         format,
        'badge':          badge,
        'author_tier':    author_tier,
        'kind':           kind,
        # Панель сүзгі рендерится одним циклом по группам — пять почти одинаковых
        # fieldset'ов в шаблоне расходились при каждой правке.
        'filter_groups': [
            {'name': 'sort',     'legend': 'Сұрыптау',   'options': data.CATALOG_SORTS,            'current': sort},
            {'name': 'kind',     'legend': 'Түрі',       'options': data.CATALOG_KIND_FILTERS,     'current': kind},
            {'name': 'badge',    'legend': 'Белгі',      'options': data.CATALOG_BADGE_FILTERS,    'current': badge},
            {'name': 'author_tier', 'legend': 'Автор',   'options': data.CATALOG_AUTHOR_FILTERS,   'current': author_tier},
            {'name': 'audience', 'legend': 'Жасың',      'options': data.CATALOG_AUDIENCE_FILTERS, 'current': audience},
            {'name': 'length',   'legend': 'Оқу уақыты', 'options': data.CATALOG_LENGTH_FILTERS,   'current': length},
        ],
        'genres':             data.all_genres(),
        'not_found_slug':     (genre_slug or tag_slug) if not_found else '',
        'current_genre_slug': eff_genre,
        'genre':              genre,
        'current_tag_slug':   eff_tag,
        'current_tag':        tag if (tag and tag.status == 'accepted') else data.tag_by_slug(eff_tag),
        'popular_tags':       data.popular_tags(),
        # Жинақтар — первичный вход в чтение (DEC-31). В каталоге они нужны
        # ровно там, где сүзгі не дали результата: пустой экран не должен быть
        # тупиком, из которого выход только назад.
        'rail_collections':   data.all_collections()[:3],
        'empty_title':        empty_title,
        'empty_text':         empty_text,
    }
    ctx.update(_catalog_links(state))
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
    """Каталог по UGC-тегу (docs/11 Phase 3, DEC-26+27). URL: /tag/<slug>/"""
    return _render_catalog(request, mode='tag', tag_slug=slug)


def collections(request):
    return render(request, 'pages/catalog/collections.html', {
        'collections': data.all_collections(),
    })


def collection_detail(request, slug):
    collection = data.collection_by_slug(slug)
    return render(request, 'pages/catalog/collection_detail.html', {
        'slug':       slug,
        'collection': collection,
    })


# ───────────────────────── STORY — произведение и чтение ─────────────────
def story_detail(request, slug):
    # Неизвестный slug отдаёт None: страница остаётся валидной и говорит
    # «Шығарма табылмады», а не падает 500.
    story = data.story_by_slug(slug)
    chapters = data.chapters_of(slug)
    # Автор своего стори видит pending-теги (BR-TAG-07). Для прочих скрыты.
    viewer = request.session.get('user_username') or ''
    is_author = bool(story and viewer and story.author.username == viewer)

    # Резолв текущей главы из ?chapter=N. Невалидное/отсутствующее значение:
    #  - авторизованный с прогрессом по этому slug → SAMPLE_PROGRESS.current_chapter
    #  - иначе → 1
    # Если глав нет вовсе — chapter_number=None, current=None (no-op в шаблоне).
    explicit_chapter = request.GET.get('chapter')
    progress = data.reading_progress_of(viewer) if viewer else None
    has_progress_here = bool(progress and progress.story.slug == slug)
    if chapters:
        try:
            chapter_number = int(explicit_chapter) if explicit_chapter else None
        except (TypeError, ValueError):
            chapter_number = None
        if not chapter_number or chapter_number < 1 or chapter_number > len(chapters):
            chapter_number = (
                progress.current_chapter if has_progress_here else 1
            )
        current = data.chapter_of(slug, chapter_number)
    else:
        chapter_number = None
        current = None

    # Тизер с разворотом — только для гл.1 при «голом» URL без ?chapter (первое
    # знакомство с произведением). Возвращающийся юзер или явный выбор главы → полный текст.
    is_teaser = bool(
        current and chapter_number == 1 and not explicit_chapter
        and not has_progress_here and not (story and story.is_single)
    )

    return render(request, 'pages/story/story_detail.html', {
        'has_right_rail': True,
        'slug':     slug,
        'story':    story,
        'chapters': chapters,
        'chapter_number': chapter_number,
        'current':  current,
        'has_prev': bool(current) and chapter_number > 1,
        'has_next': bool(current) and chapter_number < len(chapters),
        'is_teaser': is_teaser,
        'comments': data.comments_of_chapter(slug, chapter_number) if chapter_number else [],
        # FR-STORY-12 / DEC-32: пять реакций на главу вместо одиночного лайка
        'reactions': data.reactions_of(current) if current else [],
        # FR-STORY-13: опрос автора — необязателен, чаще всего его нет
        'poll': data.poll_of(slug, chapter_number) if chapter_number else None,
        # Подсветка в правом рейле — текущая отображаемая глава.
        'current_chapter_number': chapter_number,
        # FR-STORY-02: блок «Басқа шығармалар» внизу страницы
        'related':  data.related_stories(slug, limit=6) if story else [],
        # docs/11: UGC-теги произведения (resolved Tag-объекты)
        'tags':      story.tags_resolved if story else [],
        # DEC-31: обратный вход в настроение — подборки, где лежит произведение
        'in_collections': data.collections_of(story) if story else [],
        'is_author': is_author,
        # Шапка (FR-STORY-01): подпись главной кнопки — «начать» или «продолжить».
        'has_progress': bool(has_progress_here),
        # Кнопка «Сақтау» и подписка на автора в карточке автора.
        'in_library':  data.in_library(viewer, slug) if viewer else False,
        'is_followed': (
            data.is_following(viewer, story.author.username)
            if viewer and story else False
        ),
    })


# ───────────────────────── WRITE — авторский кабинет ─────────────────────
def _current_username(request) -> str:
    """Имя из фейк-сессии (см. core.views.login_view). Для гостя — ''."""
    return request.session.get('user_username', '') if request.session.get('signed_in') else ''


def _attention_links(username: str) -> list:
    """Сигналы кабинета с готовыми ссылками (FR-WRITE-08).

    `writer_attention` отдаёт только данные — kind/count/slug. Ссылку строит
    view, как и в каталоге (`_catalog_href`): URL-ы не спускаются ни в слой
    данных, ни в шаблон. Пустой `href` значит «вести некуда» — так помечены
    сигналы, за которыми стоит больше одной работы.
    """
    items = []
    for item in data.writer_attention(username):
        if item['kind'] == 'comments':
            href = reverse('core:notifications')
        elif item['slug']:
            href = reverse('core:manage_story', kwargs={'slug': item['slug']})
        else:
            href = ''
        items.append({**item, 'href': href})
    return items


def my_stories(request):
    username = _current_username(request)
    # Агрегатов автора здесь больше нет — DEC-48. Они жили в правом рейле и
    # в полосе под шапкой, повторяя `partials/profile/_stats.html` слово
    # в слово, а на страницах одного произведения тот же рейл читался как
    # статистика этого произведения. Кабинет отвечает на «что делать»,
    # профиль — на «как идёт».
    return render(request, 'pages/write/my_stories.html', {
        # FR-WRITE-08: что требует внимания — модерация, новые пікір, пустой
        # черновик. Страница перечисляла имущество и молчала о том, что делать.
        'attention': _attention_links(username) if username else [],
        'page_state': _page_state(request),
        'stories':    data.my_stories_of(username) if username else [],
        'username':   username,
    })


def new_story(request):
    return render(request, 'pages/write/new_story.html', {
        # Форма — три поля (FR-WRITE-01): атау, формат, негізгі жанр. Теги
        # переехали в баптаулар вместе с аннотацией и доп. жанром: тег к
        # ненаписанному рассказу не выбирается, а `tag_input` со своим
        # автокомплитом был самым тяжёлым элементом формы создания.
        'genres': data.all_genres(),
    })


def _checklist_links(story) -> list:
    """Пункты чек-листа с готовыми ссылками (FR-WRITE-09).

    `publish_checklist` отдаёт только состояние — ссылку строит view, как и
    в `_attention_links`. Пункт без адреса — пункт, который автор не может
    закрыть: чек-лист, показывающий недостачу и не ведущий к полю, заставляет
    искать это поле самому.
    """
    if story is None:
        return []
    settings_href = reverse('core:story_settings', kwargs={'slug': story.slug})
    if story.is_single and story.text_chapter:
        text_href = reverse('core:chapter_edit',
                            kwargs={'slug': story.slug, 'chapter': story.text_chapter})
    else:
        text_href = reverse('core:chapter_new', kwargs={'slug': story.slug})
    hrefs = {'settings': settings_href, 'text': text_href}
    return [{**item, 'href': hrefs[item['target']]}
            for item in data.publish_checklist(story)]


def manage_story(request, slug):
    story = data.story_by_slug_for_author(slug)
    return render(request, 'pages/write/manage_story.html', {
        'slug':     slug,
        'story':    story,
        'chapters': data.chapters_of(slug),
        # FR-WRITE-09: чек-лист как следующий шаг, а не как опись.
        'checklist':  _checklist_links(story),
        'can_submit': data.can_submit_for_review(story),
        'missing':    data.missing_for_review(story) if story else [],
    })


def story_settings(request, slug):
    story = data.story_by_slug_for_author(slug)
    return render(request, 'pages/write/story_settings.html', {
        'slug':   slug,
        'story':  story,
        'genres': data.all_genres(),
        # BR-10b: отметка выбирается автором, а не достаётся дефолтом.
        'story_audiences': data.STORY_AUDIENCES,
        # docs/11: данные для tag_input + текущие теги стори для edit-режима
        'accepted_tags':    data.accepted_tags_json(),
        'blocked_patterns': data.blocked_tag_patterns_list(),
        'initial_tags':     data.tags_of(story) if story else [],
    })


def chapter_editor(request, slug, chapter=None):
    story = data.story_by_slug_for_author(slug)
    current = data.chapter_of(slug, chapter) if chapter else None
    return render(request, 'pages/write/chapter_editor.html', {
        'slug':    slug,
        'story':   story,
        'chapter': chapter,
        'current': current,
        'is_new':  chapter is None,
        # FR-STORY-13: опрос главы, если автор его уже создал
        'poll':    data.poll_of(slug, chapter) if chapter else None,
    })


# ───────────────────────── PROF — профиль ────────────────────────────────
_PROF_TABS_ME    = ("works", "library", "stats", "about")
_PROF_TABS_OTHER = ("works", "about")


def _resolve_prof_tab(request, allowed) -> str:
    tab = request.GET.get('tab', 'works')
    return tab if tab in allowed else 'works'


def _prof_items(username: str, allowed: tuple, is_self: bool) -> list:
    """Сегменты PROF (label + count).

    Счётчик работ считается по `public_stories_of` **для обоих** — DEC-44.
    Пока владелец видел здесь ещё и черновики, у сегмента было две
    арифметики, и «Шығармалар 5» открывало список из трёх у постороннего.
    Одно правило, посчитанное один раз, разойтись не может.
    """
    works_n = len(data.public_stories_of(username))
    lib_n   = len(data.library_of(username)) if is_self else 0
    labels = {
        "works":   ("Шығармалар", works_n),
        "library": ("Кітапхана",  lib_n),
        # Счётчика у «Статистика» нет: число рядом обещало бы количество
        # чего-то, а вкладка — про состояние, а не про список.
        "stats":   ("Статистика", 0),
        "about":   ("Туралы",     0),
    }
    return [{'slug': k, 'label': labels[k][0], 'count': labels[k][1]} for k in allowed]


def profile_me(request):
    """Свой профиль (FR-PROF-01/03). Реальное переключение секций через ?tab=."""
    username = _current_username(request)
    author = data.AUTHORS_BY_USERNAME.get(username)
    tab = _resolve_prof_tab(request, _PROF_TABS_ME)
    # Рейл профиля состоит из одного блока «Жазылулар»: без него
    # partials/right_rail/profile.html не рендерит ничего, и гость получал
    # пустую колонку в 300px, которая просто сдвигала гейт от центра.
    following = data.following_of(username) if username else []
    catalog = data.award_catalog(username) if username else []
    ladder = data.read_ladder(username) if username else []
    return render(request, 'pages/profile/profile_me.html', {
        'has_right_rail':  bool(author and following),
        'profile_user':    author,
        'username':        username,
        'is_self':         True,
        'tab':             tab,
        'prof_items':      _prof_items(username, _PROF_TABS_ME, True) if username else [],
        # DEC-44: профиль — публичный вид на автора, а не второй кабинет.
        # `?tab=works` показывал `my_stories_of` строками `my_story_row` —
        # то есть ровно список из `/my-stories/` минус полоса внимания.
        # Теперь здесь то же, что видит читатель; черновики и модерация
        # живут только в кабинете, а их количество автор видит во вкладке
        # «Статистика» под пометкой «Тек саған көрінеді» (FR-PROF-08).
        'works':           data.public_stories_of(username) if username else [],
        'hidden_n':        (len(data.my_stories_of(username))
                            - len(data.public_stories_of(username))) if username else 0,
        'my_stories_href': reverse('core:my_stories'),
        'lib_reading':     data.library_of(username, 'reading') if username else [],
        'lib_saved':       data.library_of(username, 'saved') if username else [],
        'stats':           data.reader_stats(username) if username else None,
        'achievements':    data.achievements_of(username) if username else [],
        'contest_awards':  data.contest_awards_of(username) if username else [],
        'contests_n':      len(data.submissions_of(username)) if username else 0,
        'contest_history': data.contest_history(username, is_self=True) if username else [],
        # FR-PROF-08 — своя статистика. Ничего из этого посторонний не видит.
        'writer':          data.writer_stats(username) if username else None,
        'award_catalog':   catalog,
        'awards_earned':   sum(1 for a in catalog if a['earned']),
        'read_ladder':     ladder,
        'reads_total':     data.reads_total(username) if username else 0,
        'next_tier':       next((s for s in ladder if s['is_next']), None),
        'following':       following,
        'new_story_href':  reverse('core:new_story'),
        'catalog_href':    reverse('core:catalog'),
    })


def profile_me_edit(request):
    """Редактирование своего профиля (FR-PROF-01). Stub: рендерит форму, без сабмита."""
    username = _current_username(request)
    author = data.AUTHORS_BY_USERNAME.get(username) if username else None
    return render(request, 'pages/profile/profile_me_edit.html', {
        'profile_user': author,
        'username':     username,
    })


def profile_other(request, username):
    """Чужой профиль (FR-PROF-02/04). Кнопка «Жазылу» — если гость, ведёт на login.

    Несуществующий автор — 404, а не страница-заглушка с кодом 200: в проекте
    есть брендированная `404.html`, а прежняя заглушка позволяла поисковику
    проиндексировать любой выдуманный `@username`.

    Данные — только публичные (`public_stories_of` / `public_stats`).
    """
    author = data.AUTHORS_BY_USERNAME.get(username)
    if not author:
        raise Http404(f'Автор @{username} табылмады')
    me = _current_username(request)
    tab = _resolve_prof_tab(request, _PROF_TABS_OTHER)
    works = data.public_stories_of(username)
    # Рейл чужого профиля — «Ең көп оқылғаны», а не «на кого он подписан»
    # (FR-PROF-09). Список чужих подписок читателю ничего не сообщает, а
    # занимал единственный блок рейла.
    #
    # Порог в четыре работы — против дубля: на вкладке «Шығармалар» тело
    # показывает те же самые работы целиком, и топ-3 из трёх был бы точной
    # копией соседней колонки (то же, за что убирали числа —
    # test_desktop_layout.ProfileStatsNotDuplicated). На «Туралы» работ в
    # теле нет вовсе, поэтому там блок полезен с первой.
    rail_top = (
        data.top_stories_of(username)
        if tab == 'about' or len(works) >= 4 else []
    )
    return render(request, 'pages/profile/profile_other.html', {
        'has_right_rail': bool(rail_top),
        'profile_user':  author,
        'username':      username,
        'is_self':       False,
        'tab':           tab,
        'prof_items':    _prof_items(username, _PROF_TABS_OTHER, False),
        'works':         works,
        'rail_top':      rail_top,
        'stats':         data.public_stats(username),
        # Знаки одинаковы для владельца и для постороннего: достижение
        # публично по определению (FR-PROF-06). Число конкурсов — участие
        # без статуса, поэтому совпадает с длиной публичного списка и не
        # выдаёт вычитанием, что какая-то заявка отклонена (BR-74a).
        'achievements':  data.achievements_of(username),
        'contest_awards': data.contest_awards_of(username),
        'contests_n':    len(data.submissions_of(username)),
        # is_self=False режет результат и комментарий жюри (BR-74a)
        'contest_history': data.contest_history(username),
        'is_followed':   data.is_following(me, username) if me else False,
    })


_PEOPLE_KINDS = {
    'followers': ('Жазылушылар', data.followers_of),
    'following': ('Жазылулар',   data.following_of),
}


def profile_people(request, username, kind):
    """Подписчики и подписки автора (FR-PROF-10).

    Оба списка публичны — BR-75. Число подписчиков и так стоит плиткой в
    профиле, а подписки показывал рейл; закрывать список, число из которого
    объявлено, значило бы закрывать не данные, а возможность их прочесть.

    Один view на два набора: страницы отличаются тем, кого показывают, и
    ничем больше. Неизвестный `kind` и неизвестный автор — 404.
    """
    author = data.AUTHORS_BY_USERNAME.get(username)
    if not author or kind not in _PEOPLE_KINDS:
        raise Http404(f'@{username}: {kind} табылмады')

    title, fetch = _PEOPLE_KINDS[kind]
    me = _current_username(request)
    return render(request, 'pages/profile/profile_people.html', {
        'profile_user': author,
        'username':     username,
        'kind':         kind,
        'title':        title,
        'people':       fetch(username),
        'is_self':      me == username,
        # Сегменты ведут между двумя списками одного автора. `?tab=` здесь
        # не годится — список это путь, а не состояние страницы, — поэтому
        # каждый сегмент несёт готовый `href`.
        'people_items': [
            {
                'slug':  k,
                'label': lbl,
                'count': len(f(username)),
                'href':  reverse('core:profile_people',
                                 kwargs={'username': username, 'kind': k}),
            }
            for k, (lbl, f) in _PEOPLE_KINDS.items()
        ],
        'catalog_href': reverse('core:catalog'),
    })


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
    username = _current_username(request)
    tab = request.GET.get('tab', 'saved')
    if tab not in _LIB_TABS:
        tab = 'saved'
    entries = data.library_of(username, tab) if username else []
    items = [
        {
            'slug':  t,
            'label': _LIB_LABELS[t],
            'count': len(data.library_of(username, t)) if username else 0,
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


# ───────────────────────── CONT — конкурсы ───────────────────────────────
def contest_list(request):
    return render(request, 'pages/contests/contest_list.html', {
        # DEC-17 требует состояний на всех data-зависимых страницах, и
        # раздел конкурсов был единственным, где их не было ни на одной.
        'page_state':        _page_state(request),
        # Секций по-прежнему две, но «идущий» больше не значит «принимает
        # заявки»: точную фазу называет бейдж на карточке (DEC-45).
        'active_contests':   data.open_contests(),
        'finished_contests': data.finished_contests(),
    })


# С какого числа работ в выборе появляется поиск по ним. Ниже порога поле
# только отнимает строку: список и так виден целиком. Выше — выбор
# превращается в прокрутку, и работа, которую автор ищет, может быть
# сороковой. Порог, а не «всегда»: у большинства авторов работ единицы.
PICKER_SEARCH_FROM = 8


def _contest_rail_has_content(contest, *, submitted: bool, hide_cta: bool) -> bool:
    """Есть ли что показать в правом рейле конкурса (DEC-25).

    Флаг ставится по наличию данных, а не безусловно: `partials/right_rail/
    contest.html` пуст у неизвестного слага и у завершённого конкурса, все
    этапы которого уже позади, — а пустая колонка в 300px не пустует, она
    сдвигает контент от центра. Ровно эту ошибку в кабинете закрывал
    `test_write.MyStoriesGuestHasNoEmptyRail`.
    """
    if not contest:
        return False
    if contest.current_stage or contest.next_stage:
        return True
    # Блок «моя заявка» живёт только у активного конкурса, а на самой
    # странице подачи от него остаётся лишь строка об уже поданной работе.
    return contest.is_accepting and (submitted or not hide_cta)


def contest_detail(request, slug):
    contest = data.contest_by_slug(slug)
    username = _current_username(request)
    submitted = data.has_submission(username, slug) if username else False
    return render(request, 'pages/contests/contest_detail.html', {
        'has_right_rail': _contest_rail_has_content(contest, submitted=submitted,
                                                    hide_cta=False),
        'page_state':     _page_state(request),
        'slug':           slug,
        'contest':        contest,
        # Общие правила приходят из одного реестра (BR-48a), а не
        # переписываются в `conditions` каждого конкурса.
        'common_rules':   data.common_rules(contest) if contest else [],
        # Присуждения, а не просто работы: строка победителя называет
        # номинацию, а её знает только грант (DEC-46).
        'grants':         contest.grants if contest else [],
        'already_submitted': submitted,
    })


def contest_submit(request, slug):
    contest = data.contest_by_slug(slug)
    username = _current_username(request)
    submitted = data.has_submission(username, slug) if username else False
    candidates = (data.submission_candidates(username, slug)
                  if (username and contest) else [])

    # Выбранная по умолчанию — первая без заметок, иначе просто первая.
    # Отклонять форма ничего не отклоняет (BR-24), но начинать выбор с
    # работы, о которой есть что сказать, незачем.
    preview_story = next((c['story'] for c in candidates if not c['notes']),
                         candidates[0]['story'] if candidates else None)
    checklist = (
        data.submission_checklist(preview_story, contest)
        if preview_story and contest else []
    )
    # Чек-лист зависит от выбранной работы, а выбор меняется в браузере.
    # Раньше он считался один раз для превью и застывал: автор переключал
    # радио, а объём под ним оставался чужим. Пересчёт — на стороне
    # клиента, из этой таблицы (FR-CONT-04).
    volumes = {}
    for item in candidates:
        vol = next(c for c in data.submission_checklist(item['story'], contest)
                   if c['key'] == 'volume')
        volumes[item['story'].slug] = {
            'passed': vol['passed'],
            'hint':   vol['hint'],
            # Название нужно поиску по списку: фильтровать по DOM-тексту
            # значит зависеть от вёрстки метки.
            'title':  item['story'].title,
        }
    return render(request, 'pages/contests/contest_submit.html', {
        'has_right_rail':    _contest_rail_has_content(contest, submitted=submitted,
                                                       hide_cta=True),
        # Кнопка «Қатысу» в рейле вела бы на страницу, которая уже открыта.
        'hide_submit_cta':   True,
        'slug':              slug,
        'contest':           contest,
        'candidates':        candidates,
        'preview_story':     preview_story,
        'initial_slug':      preview_story.slug if preview_story else '',
        'volumes':           volumes,
        # Поиск по своим работам появляется, только когда список длинный:
        # у автора с тремя работами поле над ними — лишний элемент.
        'picker_search':     len(candidates) > PICKER_SEARCH_FROM,
        'checklist':         checklist,
        'can_withdraw':      data.can_withdraw(username, slug) if username else False,
        'already_submitted': submitted,
    })


def my_submissions(request):
    username = _current_username(request)
    # «Когда узнаю?» — первый вопрос после подачи, и до CONT-5 страница на
    # него не отвечала вовсе: статус «Қаралуда» стоял без единой даты.
    items = [
        {
            'sub':          sub,
            'contest':      sub.contest,
            'can_withdraw': data.can_withdraw(username, sub.contest.slug),
        }
        for sub in (data.submissions_of(username) if username else [])
    ]
    return render(request, 'pages/contests/my_submissions.html', {
        'page_state': _page_state(request),
        'items': items,
        # Модалка подключается только когда ей есть что подтверждать:
        # иначе на странице висел бы слушатель события, которое некому
        # послать.
        'any_withdrawable': any(i['can_withdraw'] for i in items),
    })


# ───────────────────── API — search_index для popup ──────────────────────
_SEARCH_INDEX_CACHE = None


def search_index_json(request):
    """JSON-индекс для search_popup (Cmd+K). Lazy-fetch — данные приходят
    только при первом открытии popup, не в каждом HTML.
    Кэшируется на время жизни процесса (stub неизменен).
    """
    global _SEARCH_INDEX_CACHE
    if _SEARCH_INDEX_CACHE is None:
        _SEARCH_INDEX_CACHE = {
            'stories': [
                {
                    'slug':   s.slug,
                    'title':  s.title,
                    'author': s.author.public_name if s.author else '',
                    # Обложки лежат в /media/ (после Фазы интеграции реальных файлов)
                    'cover':  ('/media/' + s.cover) if s.cover else '',
                }
                for s in data.public_stories()
                # Тот же набор, что и в каталоге: по литералу 'Published'
                # из Cmd+K выпали бы все сериалы (DEC-37).
                if s.status in data.PUBLIC_STATUSES
            ],
            'authors': [
                {'username': a.username, 'name': a.public_name}
                for a in data.all_authors()
            ],
            # docs/11 Phase 3: теги в Cmd+K (только accepted)
            'tags': [
                {'slug': t.slug, 'name': t.name, 'usage_count': t.usage_count}
                for t in data.all_tags() if t.status == 'accepted'
            ],
        }
    return JsonResponse(_SEARCH_INDEX_CACHE)


# ───────────────────── LEGAL/INFO — статичные правовые стабы ──────────────
# Stub-контент. Финальный текст готовит контент-менеджер. Используются для
# того чтобы footer-ссылки не вели в пустоту (FR-AUTH-05, docs/07.5).
_LEGAL_PAGES = {
    'moderation_rules': {
        'title':    'Модерация ережелері',
        'subtitle': 'Қандай шығармалар платформаға жіберіледі және не үшін шеттетіледі.',
        'body':     '',  # заполнится контентщиком
    },
    'publishing_terms': {
        'title':    'Жариялау шарттары',
        'subtitle': 'Авторлық құқық, мазмұнға қойылатын талаптар, лицензия.',
        'body':     '',
    },
    'about': {
        'title':    'Проект туралы',
        'subtitle': 'Balaproza — жас прозаиктерге арналған қазақ тіліндегі әдеби алаң.',
        'body':     '',
    },
    'terms': {
        'title':    'Пайдалану ережелері',
        'subtitle': 'Сервистің жалпы шарттары.',
        'body':     '',
    },
    'privacy': {
        'title':    'Құпиялылық саясаты',
        'subtitle': 'Дербес деректерді жинау, сақтау және өңдеу туралы.',
        'body':     '',
    },
}


def _legal(key):
    page = _LEGAL_PAGES[key]
    def view(request):
        return render(request, 'pages/legal.html', {
            'page_title':    page['title'],
            'page_subtitle': page['subtitle'],
            'page_body':     page['body'],
            'last_updated':  None,
        })
    view.__name__ = f'legal_{key}'
    return view


legal_moderation_rules = _legal('moderation_rules')
legal_publishing_terms = _legal('publishing_terms')
legal_about            = _legal('about')
legal_terms            = _legal('terms')
legal_privacy          = _legal('privacy')


# ───────────────────── DESIGN — внутренние страницы (только DEBUG) ────────
def design_components(request):
    """Каталог всех атомов во всех состояниях. Только при DEBUG."""
    if not settings.DEBUG:
        raise Http404
    accepted = [t for t in data.all_tags() if t.status == 'accepted']
    pending  = [t for t in data.all_tags() if t.status == 'pending']
    # Микс accepted + pending — иллюстрирует фильтрацию tag_list по viewer
    mixed = accepted[:3] + pending[:2]
    return render(request, 'pages/_design/components.html', {
        'genres':    data.all_genres(),
        'stories':   data.public_stories(),
        'authors':   data.all_authors(),
        # Стаб-набор покрывает все четыре фазы (DEC-45), поэтому showcase
        # бейджа — это просто перебор конкурсов, а не четыре ручных вызова
        # с выдуманными аргументами, которые разойдутся с компонентом.
        'contests':  data.all_contests(),
        # docs/11 — showcase тегов
        'showcase_tags_accepted': accepted[:8],
        'showcase_tags_pending':  pending,
        'showcase_tags_mixed':    mixed,
        # для интерактивного tag_input
        'accepted_tags':    data.accepted_tags_json(),
        'blocked_patterns': data.blocked_tag_patterns_list(),
    })


def design_states(request):
    """Каталог всех loading/error/empty состояний (DEC-17). Только при DEBUG."""
    if not settings.DEBUG:
        raise Http404
    return render(request, 'pages/_design/states.html', {
        'sample_story':   data.public_stories().first(),
        'sample_entry':   data.LIBRARY_BY_USER['aidana'][0],
        'sample_notif':   data.NOTIFICATIONS_BY_USER['aidana'][0],
        'sample_comment': data.COMMENTS_BY_STORY['dalney-berega'][0],
    })


def design_tokens(request):
    if not settings.DEBUG:
        raise Http404
    icon_names = [
        # навигация
        'search', 'arrow-right', 'arrow-left', 'angle-left', 'angle-right',
        'chevron-left', 'chevron-right', 'x',
        # действия
        'home', 'bookmark', 'bookmark-filled', 'bell', 'user-circle', 'plus',
        'pen', 'cog', 'trash', 'upload', 'paper-plane', 'list', 'check',
        'adjustments', 'book', 'arrow-right-to-bracket',
        # метрики
        'thumbs-up', 'thumbs-up-filled', 'eye', 'message-caption',
        'heart', 'heart-filled',
        # меню
        'dots-horizontal', 'dots-vertical',
    ]
    return render(request, 'pages/_design/tokens.html', {'icon_names': icon_names})
