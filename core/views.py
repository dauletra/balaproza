from urllib.parse import urlencode

from django.conf import settings
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import stub_data


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
    my_stories = stub_data.my_stories_of(username) if username else []
    active_work = next((s for s in my_stories if s.status == 'OnProcess'), my_stories[0] if my_stories else None)
    progress = stub_data.SAMPLE_PROGRESS if is_signed_in else None

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
    published = [s for s in stub_data.STORIES
                 if s.status in stub_data.PUBLIC_STATUSES]

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
        'hero_contest':    stub_data.HERO_CONTEST,
        'collections':     stub_data.COLLECTIONS,
        'genres':          stub_data.GENRES,
        'book_of_week':    stub_data.BOOK_OF_WEEK,
        'new_authors':     stub_data.new_authors(4),
        'top_stories':     sorted(published, key=lambda s: s.views, reverse=True)[:5],
        'short_stories':   [s for s in published if s.is_single and s.read_minutes <= 15][:5],
        # Ряд называется «Жалғасып жатқан шығармалар» — значит именно те,
        # что продолжаются, а не все сериалы подряд.
        'serial_stories':  [s for s in published
                            if s.is_serial and s.status == 'OnProcess'][:5],
        'portal_stats':    stub_data.portal_stats(),
        'popular_tags':    stub_data.popular_tags(8),
        'trending_tags':   stub_data.trending_tags(6),
        'school_links':    stub_data.SCHOOL_LINKS,
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
    return 'recent' if mode == 'tag' else stub_data.CATALOG_DEFAULT_SORT


def _catalog_controls(request, default_sort=None):
    """Достаёт оси сүзгі из GET с валидацией по белым спискам."""
    default_sort = default_sort or stub_data.CATALOG_DEFAULT_SORT
    axes = {
        'status':   stub_data.CATALOG_STATUS_FILTERS,
        'audience': stub_data.CATALOG_AUDIENCE_FILTERS,
        'length':   stub_data.CATALOG_LENGTH_FILTERS,
        'format':   stub_data.CATALOG_FORMAT_FILTERS,
        'badge':    stub_data.CATALOG_BADGE_FILTERS,
        'author_tier': stub_data.CATALOG_AUTHOR_FILTERS,
        'kind':     stub_data.CATALOG_KIND_FILTERS,
    }
    valid_sorts = {k for k, _ in stub_data.CATALOG_SORTS}
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
        g = stub_data.GENRES_BY_SLUG[state['genre']]
        chips.append({'label': g.name, 'hue': g.hue, 'href': href(genre='')})
    if state['tag']:
        t = stub_data.tag_by_slug(state['tag'])
        chips.append({'label': f'#{t.name}', 'href': href(tag='')})
    for axis, table in (('kind',      stub_data.CATALOG_KIND_FILTERS),
                        ('author_tier', stub_data.CATALOG_AUTHOR_FILTERS),
                        ('badge',    stub_data.CATALOG_BADGE_FILTERS),
                        ('status',   stub_data.CATALOG_STATUS_FILTERS),
                        ('format',   stub_data.CATALOG_FORMAT_FILTERS),
                        ('audience', stub_data.CATALOG_AUDIENCE_FILTERS),
                        ('length',   stub_data.CATALOG_LENGTH_FILTERS)):
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
            for g in stub_data.GENRES
        ],
        'tag_options': [
            {'tag': t, 'active': t.slug == state['tag'],
             'href': href(tag='' if t.slug == state['tag'] else t.slug)}
            for t in stub_data.popular_tags(8)
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
    for preset in stub_data.CATALOG_PRESETS:
        axes = {'format': '', 'length': '', 'status': '', 'badge': '',
                'author_tier': '', 'kind': ''}
        axes.update(preset['filters'])
        active = all(state[k] == v for k, v in axes.items())
        count = len(stub_data.filter_catalog(
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

    genre = stub_data.GENRES_BY_SLUG.get(genre_slug) if genre_slug else None
    tag = stub_data.tag_by_slug(tag_slug) if tag_slug else None
    not_found = ((mode == 'genre' and genre is None)
                 or (mode == 'tag' and (tag is None or tag.status != 'accepted')))

    # Вторая ось из query — только если путь эту ось не занял.
    eff_genre = genre_slug if genre else ''
    if not eff_genre:
        candidate = request.GET.get('genre', '')
        eff_genre = candidate if candidate in stub_data.GENRES_BY_SLUG else ''
    eff_tag = tag_slug if (tag and tag.status == 'accepted') else ''
    if not eff_tag:
        candidate = stub_data.tag_by_slug(request.GET.get('tag', ''))
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
        results = stub_data.filter_catalog(query=query, genre=eff_genre, tag=eff_tag,
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

    sort_labels = dict(stub_data.CATALOG_SORTS)
    ctx = {
        'has_right_rail': True,
        'mode':           mode,
        'results':        results,
        'query':          query,
        'sort':           sort,
        'sort_label':     sort_labels.get(sort, ''),
        'sorts':          stub_data.CATALOG_SORTS,
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
            {'name': 'sort',     'legend': 'Сұрыптау',   'options': stub_data.CATALOG_SORTS,            'current': sort},
            {'name': 'kind',     'legend': 'Түрі',       'options': stub_data.CATALOG_KIND_FILTERS,     'current': kind},
            {'name': 'badge',    'legend': 'Белгі',      'options': stub_data.CATALOG_BADGE_FILTERS,    'current': badge},
            {'name': 'author_tier', 'legend': 'Автор',   'options': stub_data.CATALOG_AUTHOR_FILTERS,   'current': author_tier},
            {'name': 'audience', 'legend': 'Жасың',      'options': stub_data.CATALOG_AUDIENCE_FILTERS, 'current': audience},
            {'name': 'length',   'legend': 'Оқу уақыты', 'options': stub_data.CATALOG_LENGTH_FILTERS,   'current': length},
        ],
        'genres':             stub_data.GENRES,
        'not_found_slug':     (genre_slug or tag_slug) if not_found else '',
        'current_genre_slug': eff_genre,
        'genre':              genre,
        'current_tag_slug':   eff_tag,
        'current_tag':        tag if (tag and tag.status == 'accepted') else stub_data.tag_by_slug(eff_tag),
        'popular_tags':       stub_data.popular_tags(),
        # Жинақтар — первичный вход в чтение (DEC-31). В каталоге они нужны
        # ровно там, где сүзгі не дали результата: пустой экран не должен быть
        # тупиком, из которого выход только назад.
        'rail_collections':   stub_data.COLLECTIONS[:3],
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
    return render(request, 'pages/catalog/genre_index.html', {
        'genres':       stub_data.GENRES,
        'total_stories': sum(g.count for g in stub_data.GENRES),
    })


def genre_detail(request, slug):
    return _render_catalog(request, mode='genre', genre_slug=slug)


def tag_detail(request, slug):
    """Каталог по UGC-тегу (docs/11 Phase 3, DEC-26+27). URL: /tag/<slug>/"""
    return _render_catalog(request, mode='tag', tag_slug=slug)


def collections(request):
    return render(request, 'pages/catalog/collections.html', {
        'collections': stub_data.COLLECTIONS,
    })


def collection_detail(request, slug):
    collection = stub_data.COLLECTIONS_BY_SLUG.get(slug)
    return render(request, 'pages/catalog/collection_detail.html', {
        'slug':       slug,
        'collection': collection,
    })


# ───────────────────────── STORY — произведение и чтение ─────────────────
def _story_or_stub(slug):
    """Резолвить Story из стаба; для неизвестных slug отдаём None — UI
    остаётся валидным («Шығарма табылмады» в шаблоне можно показывать)."""
    return stub_data.STORIES_BY_SLUG.get(slug)


def story_detail(request, slug):
    story = _story_or_stub(slug)
    chapters = stub_data.chapters_of(slug)
    # Автор своего стори видит pending-теги (BR-TAG-07). Для прочих скрыты.
    viewer = request.session.get('user_username') or ''
    is_author = bool(story and viewer and story.author.username == viewer)

    # Резолв текущей главы из ?chapter=N. Невалидное/отсутствующее значение:
    #  - авторизованный с прогрессом по этому slug → SAMPLE_PROGRESS.current_chapter
    #  - иначе → 1
    # Если глав нет вовсе — chapter_number=None, current=None (no-op в шаблоне).
    explicit_chapter = request.GET.get('chapter')
    has_progress_here = (
        request.session.get('signed_in')
        and stub_data.SAMPLE_PROGRESS.story_slug == slug
    )
    if chapters:
        try:
            chapter_number = int(explicit_chapter) if explicit_chapter else None
        except (TypeError, ValueError):
            chapter_number = None
        if not chapter_number or chapter_number < 1 or chapter_number > len(chapters):
            chapter_number = (
                stub_data.SAMPLE_PROGRESS.current_chapter if has_progress_here else 1
            )
        current = stub_data.chapter_of(slug, chapter_number)
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
        'comments': stub_data.comments_of_chapter(slug, chapter_number) if chapter_number else [],
        # FR-STORY-12 / DEC-32: пять реакций на главу вместо одиночного лайка
        'reactions': stub_data.reactions_of(current) if current else [],
        # FR-STORY-13: опрос автора — необязателен, чаще всего его нет
        'poll': stub_data.poll_of(slug, chapter_number) if chapter_number else None,
        # Подсветка в правом рейле — текущая отображаемая глава.
        'current_chapter_number': chapter_number,
        # FR-STORY-02: блок «Басқа шығармалар» внизу страницы
        'related':  stub_data.related_stories(slug, limit=6) if story else [],
        # docs/11: UGC-теги произведения (resolved Tag-объекты)
        'tags':      stub_data.tags_of(story) if story else [],
        # DEC-31: обратный вход в настроение — подборки, где лежит произведение
        'in_collections': stub_data.collections_of(story) if story else [],
        'is_author': is_author,
        # Шапка (FR-STORY-01): подпись главной кнопки — «начать» или «продолжить».
        'has_progress': bool(has_progress_here),
        # Кнопка «Сақтау» и подписка на автора в карточке автора.
        'in_library':  stub_data.in_library(viewer, slug) if viewer else False,
        'is_followed': (
            stub_data.is_following(viewer, story.author.username)
            if viewer and story else False
        ),
    })


# ───────────────────────── WRITE — авторский кабинет ─────────────────────
def _current_username(request) -> str:
    """Имя из фейк-сессии (см. core.views.login_view). Для гостя — ''."""
    return request.session.get('user_username', '') if request.session.get('signed_in') else ''


def my_stories(request):
    username = _current_username(request)
    stories = stub_data.my_stories_of(username) if username else []
    stats = stub_data.writer_stats(username) if username else None
    return render(request, 'pages/write/my_stories.html', {
        # Рейл писателя целиком построен на stats: без них
        # partials/right_rail/writer.html не рендерит ничего, и гость получал
        # пустую колонку в 300px, которая просто сдвигала гейт от центра.
        'has_right_rail': bool(stats),
        'page_state': _page_state(request),
        'stories':    stories,
        'stats':      stats,
    })


def new_story(request):
    return render(request, 'pages/write/new_story.html', {
        'has_right_rail': True,
        'genres':           stub_data.GENRES,
        # docs/11: данные для tag_input
        'accepted_tags':    stub_data.accepted_tags_json(),
        'blocked_patterns': stub_data.blocked_tag_patterns_list(),
        'initial_tags':     [],   # новая стори — без тегов
    })


def manage_story(request, slug):
    story = stub_data.STORIES_BY_SLUG.get(slug)
    stats = stub_data.writer_stats(story.author_username) if story else None
    return render(request, 'pages/write/manage_story.html', {
        # То же, что в my_stories: неизвестный slug отдаёт «Шығарма табылмады»,
        # и рядом с ним не должно висеть пустого рейла.
        'has_right_rail': bool(stats),
        'slug':     slug,
        'story':    story,
        'chapters': stub_data.chapters_of(slug),
        'stats':    stats,
    })


def story_settings(request, slug):
    story = stub_data.STORIES_BY_SLUG.get(slug)
    return render(request, 'pages/write/story_settings.html', {
        'has_right_rail': True,
        'slug':   slug,
        'story':  story,
        'genres': stub_data.GENRES,
        # docs/11: данные для tag_input + текущие теги стори для edit-режима
        'accepted_tags':    stub_data.accepted_tags_json(),
        'blocked_patterns': stub_data.blocked_tag_patterns_list(),
        'initial_tags':     stub_data.tags_of(story) if story else [],
    })


def chapter_editor(request, slug, chapter=None):
    story = stub_data.STORIES_BY_SLUG.get(slug)
    current = stub_data.chapter_of(slug, chapter) if chapter else None
    return render(request, 'pages/write/chapter_editor.html', {
        'has_right_rail': True,
        'slug':    slug,
        'story':   story,
        'chapter': chapter,
        'current': current,
        'is_new':  chapter is None,
        # FR-STORY-13: опрос главы, если автор его уже создал
        'poll':    stub_data.poll_of(slug, chapter) if chapter else None,
    })


# ───────────────────────── PROF — профиль ────────────────────────────────
_PROF_TABS_ME    = ("works", "library", "about")
_PROF_TABS_OTHER = ("works", "about")


def _resolve_prof_tab(request, allowed) -> str:
    tab = request.GET.get('tab', 'works')
    return tab if tab in allowed else 'works'


def _prof_items(username: str, allowed: tuple, is_self: bool) -> list:
    """Сегменты PROF (label + count)."""
    works_n = len(stub_data.my_stories_of(username))
    lib_n   = len(stub_data.library_of(username)) if is_self else 0
    labels = {
        "works":   ("Шығармалар", works_n),
        "library": ("Кітапхана",  lib_n),
        "about":   ("Туралы",     0),
    }
    return [{'slug': k, 'label': labels[k][0], 'count': labels[k][1]} for k in allowed]


def profile_me(request):
    """Свой профиль (FR-PROF-01/03). Реальное переключение секций через ?tab=."""
    username = _current_username(request)
    author = stub_data.AUTHORS_BY_USERNAME.get(username)
    tab = _resolve_prof_tab(request, _PROF_TABS_ME)
    return render(request, 'pages/profile/profile_me.html', {
        'has_right_rail':  True,
        'profile_user':    author,
        'username':        username,
        'is_self':         True,
        'tab':             tab,
        'prof_items':      _prof_items(username, _PROF_TABS_ME, True) if username else [],
        'works':           stub_data.my_stories_of(username) if username else [],
        'lib_reading':     stub_data.library_of(username, 'reading') if username else [],
        'lib_saved':       stub_data.library_of(username, 'saved') if username else [],
        'stats':           stub_data.reader_stats(username) if username else None,
        'followers':       stub_data.followers_of(username) if username else [],
        'following':       stub_data.following_of(username) if username else [],
        'new_story_href':  reverse('core:new_story'),
        'catalog_href':    reverse('core:catalog'),
    })


def profile_me_edit(request):
    """Редактирование своего профиля (FR-PROF-01). Stub: рендерит форму, без сабмита."""
    username = _current_username(request)
    author = stub_data.AUTHORS_BY_USERNAME.get(username) if username else None
    return render(request, 'pages/profile/profile_me_edit.html', {
        'profile_user': author,
        'username':     username,
    })


def profile_other(request, username):
    """Чужой профиль (FR-PROF-02/04). Кнопка «Жазылу» — если гость, ведёт на login."""
    author = stub_data.AUTHORS_BY_USERNAME.get(username)
    me = _current_username(request)
    tab = _resolve_prof_tab(request, _PROF_TABS_OTHER)
    return render(request, 'pages/profile/profile_other.html', {
        'has_right_rail': True,
        'profile_user':  author,
        'username':      username,
        'is_self':       False,
        'tab':           tab,
        'prof_items':    _prof_items(username, _PROF_TABS_OTHER, False) if author else [],
        'works':         stub_data.my_stories_of(username),
        'stats':         stub_data.reader_stats(username) if author else None,
        'following':     stub_data.following_of(username) if author else [],
        'is_followed':   stub_data.is_following(me, username) if me else False,
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
    entries = stub_data.library_of(username, tab) if username else []
    items = [
        {
            'slug':  t,
            'label': _LIB_LABELS[t],
            'count': len(stub_data.library_of(username, t)) if username else 0,
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
    grouped = stub_data.notifications_for_user(username) if username else {}
    has_any = any(grouped.get(b) for b in stub_data.NOTIF_BUCKETS)
    return render(request, 'pages/notifications.html', {
        'page_state':    _page_state(request),
        'grouped':       grouped,
        'buckets':       stub_data.NOTIF_BUCKETS,
        'bucket_labels': stub_data.NOTIF_BUCKET_LABELS,
        'has_any':       has_any,
        'unread_total':  stub_data.unread_count_for_user(username) if username else 0,
    })


# ───────────────────────── CONT — конкурсы ───────────────────────────────
def contest_list(request):
    return render(request, 'pages/contests/contest_list.html', {
        'active_contests':   [c for c in stub_data.CONTESTS if c.status == 'active'],
        'finished_contests': [c for c in stub_data.CONTESTS if c.status == 'finished'],
    })


def contest_detail(request, slug):
    contest = stub_data.CONTESTS_BY_SLUG.get(slug)
    username = _current_username(request)
    return render(request, 'pages/contests/contest_detail.html', {
        'has_right_rail': True,
        'slug':           slug,
        'contest':        contest,
        'already_submitted': stub_data.has_submission(username, slug) if username else False,
    })


def contest_submit(request, slug):
    contest = stub_data.CONTESTS_BY_SLUG.get(slug)
    username = _current_username(request)
    eligible = stub_data.eligible_for_contest(username, slug) if (username and contest) else []
    # Чек-лист считаем для первого подходящего произведения (превью).
    preview_story = next((e['story'] for e in eligible if e['eligible']), None)
    checklist = (
        stub_data.submission_checklist(preview_story, contest)
        if preview_story and contest else []
    )
    return render(request, 'pages/contests/contest_submit.html', {
        'has_right_rail':    True,
        'slug':              slug,
        'contest':           contest,
        'eligible':          eligible,
        'preview_story':     preview_story,
        'checklist':         checklist,
        'already_submitted': stub_data.has_submission(username, slug) if username else False,
    })


def my_submissions(request):
    username = _current_username(request)
    return render(request, 'pages/contests/my_submissions.html', {
        'submissions': stub_data.submissions_of(username) if username else [],
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
                for s in stub_data.STORIES
                # Тот же набор, что и в каталоге: по литералу 'Published'
                # из Cmd+K выпали бы все сериалы (DEC-37).
                if s.status in stub_data.PUBLIC_STATUSES
            ],
            'authors': [
                {'username': a.username, 'name': a.public_name}
                for a in stub_data.AUTHORS
            ],
            # docs/11 Phase 3: теги в Cmd+K (только accepted)
            'tags': [
                {'slug': t.slug, 'name': t.name, 'usage_count': t.usage_count}
                for t in stub_data.TAGS if t.status == 'accepted'
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
    data = _LEGAL_PAGES[key]
    def view(request):
        return render(request, 'pages/legal.html', {
            'page_title':    data['title'],
            'page_subtitle': data['subtitle'],
            'page_body':     data['body'],
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
    accepted = [t for t in stub_data.TAGS if t.status == 'accepted']
    pending  = [t for t in stub_data.TAGS if t.status == 'pending']
    # Микс accepted + pending — иллюстрирует фильтрацию tag_list по viewer
    mixed = accepted[:3] + pending[:2]
    return render(request, 'pages/_design/components.html', {
        'genres':    stub_data.GENRES,
        'stories':   stub_data.STORIES,
        'authors':   stub_data.AUTHORS,
        # docs/11 — showcase тегов
        'showcase_tags_accepted': accepted[:8],
        'showcase_tags_pending':  pending,
        'showcase_tags_mixed':    mixed,
        # для интерактивного tag_input
        'accepted_tags':    stub_data.accepted_tags_json(),
        'blocked_patterns': stub_data.blocked_tag_patterns_list(),
    })


def design_states(request):
    """Каталог всех loading/error/empty состояний (DEC-17). Только при DEBUG."""
    if not settings.DEBUG:
        raise Http404
    return render(request, 'pages/_design/states.html', {
        'sample_story':   stub_data.STORIES[0],
        'sample_entry':   stub_data.LIBRARY_BY_USER['aidana'][0],
        'sample_notif':   stub_data.NOTIFICATIONS_BY_USER['aidana'][0],
        'sample_comment': stub_data.COMMENTS_BY_STORY['dalney-berega'][0],
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
