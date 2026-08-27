"""Данные плюс адрес: где к ответу слоя запросов добавляется URL.

Правило проекта — **URL-ы не спускаются ни в слой данных, ни в шаблон**.
`writer_attention` отдаёт `kind`/`count`/`slug`, `publish_checklist` —
состояние пункта, `CATALOG_PRESETS` — набор осей; куда всё это ведёт,
знает только этот модуль.

Раньше он был размазан по `views.py` пятью приватными функциями. Вместе
они больше половины того файла и не делали ничего, кроме сборки ссылок, —
а `_catalog_href` вдобавок выписывал восемь осей каталога в своей
сигнатуре, четвёртой копией к тем, что стояли в `_catalog_controls`,
в словаре состояния и в контексте шаблона. Девятая ось означала бы правку
в пяти местах и не перепутать порядок при распаковке кортежа.
"""

from dataclasses import dataclass, fields, replace
from urllib.parse import urlencode

from django.urls import reverse

from . import data


# ─────────────────────────── Каталог (DEC-27) ────────────────────────────
# Оси каталога — один список на весь проект. Ключ это контракт URL
# (`?kind=`), таблица — источник и валидации, и подписи чипа. Порядок
# значим: в нём чипы активных осей встают на экране.
CATALOG_AXES = (
    ('kind',        data.CATALOG_KIND_FILTERS),
    ('author_tier', data.CATALOG_AUTHOR_FILTERS),
    ('badge',       data.CATALOG_BADGE_FILTERS),
    ('status',      data.CATALOG_STATUS_FILTERS),
    ('audience',    data.CATALOG_AUDIENCE_FILTERS),
    ('length',      data.CATALOG_LENGTH_FILTERS),
)

# Панель сүзгі рендерится одним циклом по группам: пять почти одинаковых
# fieldset'ов в шаблоне расходились при каждой правке. Сортировка стоит
# первой и осью не считается — она не сужает выдачу.
FILTER_GROUPS = (
    ('sort',        'Сұрыптау'),
    ('kind',        'Түрі'),
    ('badge',       'Белгі'),
    ('author_tier', 'Автор'),
    ('audience',    'Жасың'),
    ('length',      'Оқу уақыты'),
)


def catalog_default_sort(mode: str) -> str:
    """Дефолтная сортировка режима.

    Каталог, жанр и поиск открываются «Қазір танымал» — окном в 14 дней
    (DEC-36). Тег остаётся на «Жаңалары»: DEC-31 отдал ему роль самой быстрой
    оси портала, и там ценна свежесть сама по себе, а не набранные просмотры.
    """
    return 'recent' if mode == 'tag' else data.CATALOG_DEFAULT_SORT


@dataclass(frozen=True)
class CatalogState:
    """Что читатель выбрал в каталоге — одним объектом.

    Неизменяемый: «состояние минус одна ось» это новый объект, а не правка
    старого, и `replace()` не даёт забыть поле. Раньше то же самое ездило
    семикортежем из `_catalog_controls` плюс рукописным словарём, и оба
    приходилось держать в согласии глазами.

    `sort` пустой означает «дефолт целевой страницы»: ссылка на тег из
    каталога не должна тащить туда popularity и ломать DEC-31.
    """

    mode: str = 'catalog'
    genre: str = ''
    tag: str = ''
    query: str = ''
    sort: str = ''
    kind: str = ''
    author_tier: str = ''
    badge: str = ''
    status: str = ''
    audience: str = ''
    length: str = ''

    # ── Разбор запроса ───────────────────────────────────────────────────
    @classmethod
    def from_request(cls, request, *, mode: str, genre: str = '', tag: str = ''):
        """Оси из GET с валидацией по белым спискам.

        Неизвестное значение — пустая ось, а не 404: `?kind=no-such` это
        опечатка или старая ссылка, и страница обязана открыться.
        """
        picked = {}
        for name, table in CATALOG_AXES:
            got = request.GET.get(name, '')
            picked[name] = got if got in {k for k, _ in table} else ''

        sort = request.GET.get('sort', '')
        if sort not in {k for k, _ in data.CATALOG_SORTS}:
            sort = ''
        return cls(mode=mode, genre=genre, tag=tag,
                   query=request.GET.get('q', '').strip(),
                   sort=sort, **picked)

    @property
    def effective_sort(self) -> str:
        """Чем сортировать сейчас. Пустой `sort` — дефолт режима."""
        return self.sort or catalog_default_sort(self.mode)

    @property
    def axes(self) -> dict:
        """Только сужающие оси — то, что уходит в `filter_catalog`."""
        return {name: getattr(self, name) for name, _ in CATALOG_AXES}

    def replace(self, **over) -> 'CatalogState':
        return replace(self, **over)

    # ── Адреса ───────────────────────────────────────────────────────────
    def href(self, **over) -> str:
        """Канонический URL этого состояния с изменёнными осями (DEC-27).

        Путь выбирает «главная» ось: жанр → /genres/<slug>/, иначе тег →
        /tag/<slug>/, иначе режим страницы. Всё остальное едет в query. До
        этого чипы жанра и тега вели на голый путь, и выбор жанра молча
        сбрасывал уже выставленные жас и оқу уақыты.
        """
        st = self.replace(**over) if over else self
        params = {}
        if st.genre:
            path = reverse('core:genre_detail', kwargs={'slug': st.genre})
            params['tag'] = st.tag
            target_mode = 'genre'
        elif st.tag:
            path = reverse('core:tag_detail', kwargs={'slug': st.tag})
            target_mode = 'tag'
        elif st.mode == 'search':
            path = reverse('core:search_results')
            target_mode = 'search'
        else:
            path = reverse('core:catalog')
            target_mode = 'catalog'

        params.update({'q': st.query}, **st.axes)
        if st.sort and st.sort != catalog_default_sort(target_mode):
            params['sort'] = st.sort

        qs = urlencode({k: v for k, v in params.items() if v})
        return f'{path}?{qs}' if qs else path

    @property
    def clear_href(self) -> str:
        """«Тазалау» снимает сүзгі, но не выкидывает из раздела: с
        /genres/triller/ уходить в общий каталог человек не просил. Выход
        из жанра — крестик на чипе."""
        bare = CatalogState(mode=self.mode)
        if self.mode == 'genre' and self.genre:
            return bare.replace(genre=self.genre).href()
        if self.mode == 'tag' and self.tag:
            return bare.replace(tag=self.tag).href()
        if self.mode == 'search':
            return bare.replace(query=self.query).href()
        return bare.href()

    @property
    def page_base(self) -> str:
        """Путь без query. `components/pagination.html` дописывает `?page=N`
        сам, поэтому адрес отдаётся ему разобранным на две половины."""
        return self.href().split('?')[0]

    @property
    def page_qs(self) -> str:
        """Query текущего состояния — без номера страницы.

        Номер в состоянии не живёт: страница это позиция в выдаче, а не ось
        выбора, и нести её через чипы жанра и тега значило бы уводить со
        второй страницы каталога на вторую страницу жанра, которой может и
        не быть.
        """
        return self.href().partition('?')[2]

    @property
    def active_count(self) -> int:
        """Сколько осей реально включено — бейдж на кнопке сүзгі.

        Считает включённые, а не показанные чипы: внутри панели галочки
        пресета видны как обычные radio, и число обязано совпадать с тем,
        что там отмечено. `mode` и `sort` осями не считаются — первый это
        раздел, второй порядок, а не сужение.
        """
        skip = {'mode', 'sort'}
        return sum(1 for f in fields(self)
                   if f.name not in skip and getattr(self, f.name))


def catalog_presets(state: CatalogState) -> list:
    """Пресеты «Не оқимын?» — готовые комбинации осей одним тапом.

    Считаем каждому пресету реальный размер выборки: чип, ведущий в пустоту,
    хуже отсутствующего чипа. Счёт берётся в текущем разделе (жанр/тег/запрос
    сохраняются), поэтому «Бір отырыста» внутри жанра честно показывает,
    сколько коротких историй есть именно там.
    """
    blank = {name: '' for name, _ in CATALOG_AXES}
    out = []
    for preset in data.CATALOG_PRESETS:
        axes = {**blank, **preset['filters']}
        active = all(getattr(state, k) == v for k, v in axes.items())
        # `.count()`, а не `len()`: последний выполняет выдачу целиком и
        # строит список ORM-объектов со всеми тегами — шесть раз за
        # страницу, ради шести цифр на чипах.
        count = data.filter_catalog(query=state.query, genre=state.genre,
                                    tag=state.tag, **axes).count()
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
            'href':   state.href(**(blank if active else axes)),
        })
    return out


def catalog_links(state: CatalogState) -> dict:
    """Ссылки-состояния каталога: активные чипы, жанры, теги, сброс.

    Собираются здесь, а не в шаблоне: каждая ссылка — это «текущее состояние
    минус одна ось», а такой URL шаблонными средствами не построить.
    """
    presets = catalog_presets(state)

    # Оси, которые уже показаны активным пресетом, отдельными чипами не
    # дублируем: «Бір отырыста» и рядом «Бір бөлімді» + «15 минутқа дейін» —
    # это один и тот же выбор, показанный трижды.
    covered = set()
    for preset in presets:
        if preset['active']:
            covered = set(preset['axes'])

    chips = []
    if state.query:
        chips.append({'label': f'«{state.query}»', 'href': state.href(query='')})
    if state.genre:
        g = data.genre_by_slug(state.genre)
        chips.append({'label': g.name, 'hue': g.hue, 'href': state.href(genre='')})
    if state.tag:
        t = data.tag_by_slug(state.tag)
        chips.append({'label': f'#{t.name}', 'href': state.href(tag='')})
    for axis, table in CATALOG_AXES:
        value = getattr(state, axis)
        if value and axis not in covered:
            chips.append({'label': dict(table)[value],
                          'href': state.href(**{axis: ''})})

    return {
        'active_chips':  chips,
        'active_count':  state.active_count,
        'clear_href':    state.clear_href,
        'genre_options': [
            {'genre': g, 'active': g.slug == state.genre,
             'href': state.href(genre='' if g.slug == state.genre else g.slug)}
            for g in data.all_genres()
        ],
        'tag_options': [
            {'tag': t, 'active': t.slug == state.tag,
             'href': state.href(tag='' if t.slug == state.tag else t.slug)}
            for t in data.popular_tags(8)
        ],
        'presets': presets,
    }


# ─────────────────────────── Кабинет автора ──────────────────────────────
def attention_links(username: str, facts=None) -> list:
    """Сигналы кабинета с готовыми ссылками (FR-WRITE-08).

    `writer_attention` отдаёт только данные — kind/count/slug. Пустой
    `href` значит «вести некуда» — так помечены сигналы, за которыми стоит
    больше одной работы.
    """
    items = []
    for item in data.writer_attention(username, facts=facts):
        if item['kind'] == 'comments':
            href = reverse('core:notifications')
        elif item['slug']:
            href = reverse('core:manage_story', kwargs={'slug': item['slug']})
        else:
            href = ''
        items.append({**item, 'href': href})
    return items


def checklist_links(story) -> list:
    """Пункты чек-листа с готовыми ссылками (FR-WRITE-09).

    `publish_checklist` отдаёт только состояние. Пункт без адреса — пункт,
    который автор не может закрыть: чек-лист, показывающий недостачу и не
    ведущий к полю, заставляет искать это поле самому.
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


def notification_href(n) -> str:
    """Куда ведёт уведомление (BR-72a, FR-NOTIF-05).

    Предмет у каждого типа свой: отклик и комментарий открывают работу,
    новый подписчик — его профиль, решение модератора — работу **в
    авторском кабинете** (публично её может не быть, BR-73), конкурсное —
    конкурс.

    Собирается здесь, а не в шаблоне, потому что этот же адрес нужен
    вью: клик по уведомлению проходит через `notification_open`, которое
    снимает «непрочитано» и отправляет дальше (BR-71). Два экземпляра
    одной таблицы соответствий разошлись бы на первом же новом типе.

    Пусто — предмета нет (объект удалили): уведомление остаётся строкой
    без ссылки, а не ведёт на битый адрес.
    """
    if n.kind == 'moderation':
        return (reverse('core:manage_story', kwargs={'slug': n.story.slug})
                if n.story_id else '')
    if n.kind == 'contest':
        return (reverse('core:contest_detail', kwargs={'slug': n.contest.slug})
                if n.contest_id else '')
    if n.kind == 'follower':
        return (reverse('core:profile_other', kwargs={'username': n.actor.username})
                if n.actor_id else '')
    if n.story_id:
        return reverse('core:story_detail', kwargs={'slug': n.story.slug})
    if n.actor_id:
        return reverse('core:profile_other', kwargs={'username': n.actor.username})
    return ''
