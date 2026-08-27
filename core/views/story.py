"""Страница произведения и инлайн-чтение главы (FR-STORY-*)."""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse

from .. import data
from .common import _current_username

# Что читатель уже открывал в этой сессии — против накрутки перезагрузкой.
# Список, а не множество: сессия сериализуется в JSON, где множества нет.
_SEEN_STORIES = 'seen_stories'
# Хвост ограничен, иначе сессия растёт вместе с прочитанным. Двести работ —
# это заметно больше, чем читают за один заход на портал, а вышедшая за
# край работа в худшем случае засчитается второй раз.
_SEEN_LIMIT = 200


def _count_view(request, story) -> None:
    """Один оқылым на работу за сессию.

    Счётчик до этого не рос вообще: в базу его клал только сид, и
    «Қазір танымал» — дефолтная сортировка каталога — навсегда
    показывала порядок демо-данных.

    Свой заход автору не засчитывается. Это не борьба с мошенничеством —
    от неё защищает не сессия, — а защита от самого частого способа
    надуть цифру случайно: открыть свою работу и обновить страницу.
    """
    if request.method != 'GET':
        return
    if request.user.is_authenticated and story.author_id == request.user.id:
        return

    seen = request.session.get(_SEEN_STORIES, [])
    if story.pk in seen:
        return
    seen.append(story.pk)
    request.session[_SEEN_STORIES] = seen[-_SEEN_LIMIT:]
    data.record_story_view(story)


def _back_to_story(slug, chapter_number=None, anchor=None):
    """PRG-редирект обратно на страницу произведения, к той же главе и,
    если есть на что, к якорю нового/задетого комментария."""
    url = reverse('core:story_detail', kwargs={'slug': slug})
    if chapter_number:
        url = f'{url}?chapter={chapter_number}'
    if anchor:
        url = f'{url}#{anchor}'
    return redirect(url)


# ───────────────────────── STORY — произведение и чтение ─────────────────
def story_detail(request, slug):
    # Неизвестный slug отдаёт None: страница остаётся валидной и говорит
    # «Шығарма табылмады», а не падает 500.
    story = data.story_by_slug(slug)
    chapters = data.chapters_of(slug)
    # Автор своего стори видит pending-теги (BR-TAG-07). Для прочих скрыты.
    viewer = _current_username(request)
    is_author = bool(story and viewer and story.author.username == viewer)

    if story is not None:
        _count_view(request, story)

    # Резолв текущей главы из ?chapter=N. Невалидное/отсутствующее значение:
    #  - авторизованный с прогрессом по этому slug → его глава
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
        current = data.chapter_of(slug, chapter_number, viewer)
    else:
        chapter_number = None
        current = None

    # Запоминаем место **после** резолва: `has_progress_here` выше отвечает
    # на «была ли закладка до этого захода», и от неё зависят и тизер, и
    # подпись главной кнопки. Записанный раньше прогресс сделал бы первое
    # знакомство с работой похожим на возвращение к ней.
    if current is not None and request.user.is_authenticated:
        data.record_reading_progress(request.user, story, chapter_number, chapters)
        # BR-61 / FR-LIB-02: полку двигает само чтение, а не только кнопка.
        data.move_to_shelf(request.user, story,
                           finished=chapter_number == len(chapters))

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
        'comments': (data.comments_of_chapter(slug, chapter_number, viewer)
                    if chapter_number else []),
        # FR-STORY-12 / DEC-32: пять реакций на главу вместо одиночного лайка
        'reactions': data.reactions_of(current) if current else [],
        # FR-STORY-13: опрос автора — необязателен, чаще всего его нет
        'poll': data.poll_of(slug, chapter_number, viewer) if chapter_number else None,
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


# ────────────────────── Комментарии (BR-30/31/33, Ф15 Этап 2) ────────────

def _chapter_from_post(request) -> int | None:
    raw = request.POST.get('chapter')
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def comment_create(request, slug):
    """Новый комментарий или ответ. Гость и несуществующий slug молча
    возвращаются на страницу — форма для них и так не рендерится."""
    story = data.story_by_slug(slug)
    username = _current_username(request)
    chapter_number = _chapter_from_post(request)
    if request.method != 'POST' or story is None or not username:
        return _back_to_story(slug, chapter_number)

    text = request.POST.get('text', '').strip()
    parent = None
    parent_id = request.POST.get('parent')
    if parent_id:
        # BR-30: ответ — только на верхнеуровневый комментарий этой же
        # работы. Чужой/несуществующий/уже-ответ id — не создаём ничего.
        parent = data.top_level_comment_of(slug, parent_id)
        if parent is None:
            messages.error(request, 'Бұл пікірге жауап беруге болмайды.')
            return _back_to_story(slug, chapter_number)

    if not text:
        messages.error(request, 'Пікір мәтінін жаз.')
        return _back_to_story(slug, chapter_number)

    comment = data.add_comment(story, request.user, text=text,
                               chapter_number=chapter_number, parent=parent)
    messages.success(request, 'Пікірің қосылды.')
    return _back_to_story(slug, chapter_number, anchor=f'comment-{comment.pk}')


def comment_delete(request, slug, comment_id):
    """GET безопасен — ничего не удаляет. Владение — `belongs_to` (BR-33),
    та же проверка, что уже решает, показывать «Жою» или «Шағым»."""
    username = _current_username(request)
    comment = data.comment_of(slug, comment_id)
    if (request.method == 'POST' and comment is not None
            and comment.belongs_to(username)):
        chapter_number = comment.chapter_number
        data.delete_comment(comment)
        messages.success(request, 'Пікір өшірілді.')
        return _back_to_story(slug, chapter_number)
    return _back_to_story(slug, _chapter_from_post(request))


def comment_like(request, slug, comment_id):
    """Toggle (BR-31) — авторизованный обязателен, на свой комментарий
    лайк тоже можно поставить (правило не запрещает)."""
    username = _current_username(request)
    comment = data.comment_of(slug, comment_id)
    if request.method == 'POST' and comment is not None and username:
        data.toggle_comment_like(comment, request.user)
        return _back_to_story(slug, comment.chapter_number, anchor=f'comment-{comment.pk}')
    return _back_to_story(slug, _chapter_from_post(request))


# ───────────────────── Библиотека (BR-60/61, FR-LIB-02) ──────────────────

def library_toggle(request, slug):
    """Кнопка «Сақтау»: положить работу в библиотеку или снять с полки.

    До этого кнопка меняла только своё состояние в браузере: тост
    обещал «Кітапханаға сақталды», а на полке не появлялось ничего, и
    после перезагрузки страницы обещание исчезало вместе с ним.

    Гостю кнопка не рендерится — она сразу ведёт на вход, — поэтому здесь
    просто возврат без записи, как у остальных действий страницы.
    """
    story = data.story_by_slug(slug)
    if request.method == 'POST' and story is not None and request.user.is_authenticated:
        saved = data.toggle_library_entry(request.user, story)
        messages.success(request, 'Кітапханаға сақталды' if saved
                         else 'Кітапханадан алынды')
    return _back_to_story(slug, _chapter_from_post(request))


# ───────────────────── Реакции на главу (BR-REACT-02/03, Ф15 Этап 3) ──────

def chapter_react(request, slug, chapter):
    """Ставит/снимает/меняет реакцию на главе — авторизованный обязателен,
    `kind` — один из пяти закрытого списка (BR-REACT-01)."""
    username = _current_username(request)
    ch = data.chapter_of(slug, chapter)
    kind = request.POST.get('kind', '')
    if (request.method == 'POST' and ch is not None and username
            and kind in data.REACTIONS_BY_SLUG):
        data.toggle_chapter_reaction(ch, request.user, kind)
    return _back_to_story(slug, chapter)


# ───────────────────── Опрос главы (BR-POLL-03/05, Ф15 Этап 4) ────────────

def poll_vote(request, slug, chapter):
    """Голос в опросе — авторизованный обязателен; закрытый опрос и
    невалидный/повторный вариант `data.cast_poll_vote` тихо отклоняет."""
    username = _current_username(request)
    poll = data.poll_of(slug, chapter)
    option_slug = request.POST.get('option', '')
    if request.method == 'POST' and poll is not None and username and option_slug:
        data.cast_poll_vote(poll, request.user, option_slug)
    return _back_to_story(slug, chapter)
