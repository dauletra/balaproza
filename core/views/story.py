"""Страница произведения и инлайн-чтение главы (FR-STORY-*)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .. import data
from ..forms import CommentForm
from .common import _current_user, _found_or_404, _safe_next, _throttled

# Что читатель уже открывал в этой сессии — против накрутки перезагрузкой.
# Список, а не множество: сессия сериализуется в JSON, где множества нет.
_SEEN_STORIES = 'seen_stories'
# Хвост ограничен, иначе сессия растёт вместе с прочитанным. Вышедшая за
# край работа в худшем случае засчитается второй раз.
_SEEN_LIMIT = 200


def _count_view(request, story) -> None:
    """Один оқылым на работу за сессию.

    Свой заход автору не засчитывается. Это не борьба с мошенничеством —
    от неё сессия не защищает, — а защита от самого частого способа надуть
    цифру случайно: открыть свою работу и обновить страницу.
    """
    if request.method != 'GET':
        return
    # Непубличное не читают — его смотрят: автор свой черновик, модератор
    # работу в очереди (BR-76). Засчитанный им оқылым — цифра, которую
    # работа принесёт в каталог, ещё не побывав у читателя.
    if not story.is_public:
        return
    if request.user.is_authenticated and story.author_id == request.user.id:
        return

    seen = request.session.get(_SEEN_STORIES, [])
    if story.pk in seen:
        return
    seen.append(story.pk)
    request.session[_SEEN_STORIES] = seen[-_SEEN_LIMIT:]
    data.record_story_view(
        story, request.user if request.user.is_authenticated else None)


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
    # Кто смотрит — раньше, чем что показываем: от зрителя зависит само
    # существование страницы (BR-76). Чужой черновик не «запрещён», его
    # нет — 404, как у несуществующего слага.
    viewer = _current_user(request)
    story = _found_or_404(data.story_by_slug(slug, viewer),
                          f'Шығарма «{slug}» табылмады')
    # Автор своего стори видит pending-теги (BR-TAG-07). Для прочих скрыты.
    is_author = bool(viewer and story.author_id == viewer.pk)
    # Предпросмотр (BR-76/79): автор и модератор видят и неопубликованные
    # главы, и рабочую копию текста. Читателю их не существует — у него
    # только то, что прошло модератора.
    previewing = bool(is_author or (viewer and viewer.is_staff))
    chapters = data.chapters_of(slug, as_author=previewing)

    _count_view(request, story)

    # Резолв текущей главы из ?chapter=N. Мусор и пустое: вошедшему — глава
    # его закладки, иначе первая; глав нет вовсе — None и no-op в шаблоне.
    explicit_chapter = request.GET.get('chapter')
    progress = data.reading_progress_of(viewer)
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
        current = data.chapter_among(chapters, chapter_number, viewer)
    else:
        chapter_number = None
        current = None

    # Первый «голый» заход на гл.1 без ?chapter и без прежней закладки —
    # первое знакомство с произведением, а не чтение: гл.1 открылась сама,
    # читатель её не выбирал. Текст при этом показывается полностью
    # (DEC-59 убрал обрезку тизера), но заход всё равно не считается
    # стартом чтения — от него не двигаем полку и не показываем счётчик
    # прогресса. Возвращающийся или тот, кто явно выбрал главу, → False.
    is_first_look = bool(
        current and chapter_number == 1 and not explicit_chapter
        and not has_progress_here and not story.is_single
    )

    # Запоминаем место **после** резолва: `has_progress_here` отвечает на
    # «была ли закладка до этого захода», и от неё зависят is_first_look и
    # подпись главной кнопки. Записанный раньше, прогресс сделал бы первое
    # знакомство с работой похожим на возвращение.
    # Полка и закладка — тоже след чтения, и у непубличной работы его быть
    # не может: автор не «читает» свой черновик, модератор не ставит
    # очередь себе на полку (BR-76).
    if current is not None and request.user.is_authenticated and story.is_public:
        # Продвижение, а не повторный показ того же места: глава, отличная
        # от закладки, либо первый заход не тем самым «голым» гл.1. Полку
        # двигает только оно (BR-61) — иначе снятие кнопкой воскресало бы
        # на редиректе сюда же. Неравенство, а не «дальше»: повторное
        # чтение дочитанного начинается с первой главы и обязано вернуть
        # работу на `reading`.
        advanced = (chapter_number != progress.current_chapter
                    if has_progress_here else not is_first_look)
        data.record_reading_progress(request.user, story, chapter_number, chapters)
        # BR-61 / FR-LIB-02: полку двигает само чтение, а не только кнопка.
        data.move_to_shelf(request.user, story, advanced=advanced,
                           finished=chapter_number == len(chapters))

    return render(request, 'pages/story/story_detail.html', {
        'has_right_rail': True,
        'slug':     slug,
        'story':    story,
        'chapters': chapters,
        'chapter_number': chapter_number,
        'current':  current,
        'has_prev': bool(current) and chapter_number > 1,
        'has_next': bool(current) and chapter_number < len(chapters),
        'is_first_look': is_first_look,
        'comments': (data.comments_of_chapter(slug, chapter_number, viewer)
                    if chapter_number else []),
        # FR-STORY-12 / DEC-32: пять реакций на главу вместо одиночного лайка
        'reactions': data.reactions_of(current) if current else [],
        # FR-STORY-13: опрос автора — необязателен, чаще всего его нет
        'poll': data.poll_for(current, viewer),
        # Подсветка в правом рейле — текущая отображаемая глава.
        'current_chapter_number': chapter_number,
        # FR-STORY-02: блок «Басқа шығармалар» внизу страницы
        'related':  data.related_stories(slug, limit=6),
        # docs/ui.md: UGC-теги произведения (resolved Tag-объекты)
        'tags':      story.tags_resolved,
        # DEC-31: обратный вход в настроение — подборки, где лежит произведение
        'in_collections': data.collections_of(story),
        'is_author': is_author,
        # Предпросмотр (BR-76): страница открыта, но читателю её ещё нет.
        # Автору и модератору об этом говорится вслух — иначе публичная и
        # непубличная работа выглядят одинаково, и «Сайтта қарау» из
        # кабинета читается как «уже опубликовано».
        'is_preview': not story.is_public,
        # Шапка (FR-STORY-01): подпись главной кнопки — «начать» или «продолжить».
        'has_progress': bool(has_progress_here),
        # Кнопка «Сақтау» и подписка на автора в карточке автора.
        'in_library':  data.in_library(viewer, slug),
        'is_followed': data.is_following(viewer, story.author),
    })


# ────────────────────── Комментарии (BR-30/31/33, Ф15 Этап 2) ────────────

def _chapter_from_post(request) -> int | None:
    raw = request.POST.get('chapter')
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


@require_POST
@login_required
def comment_create(request, slug):
    """Новый комментарий или ответ. Несуществующий slug молча возвращается
    на страницу — как и невидимый этому человеку (BR-76): страницы, на
    которой он комментирует, у него нет."""
    story = data.story_by_slug(slug, request.user)
    chapter_number = _chapter_from_post(request)
    if story is None:
        return _back_to_story(slug, chapter_number)
    # Предел частоты (C4): поле без него означало сто комментариев за
    # минуту и страницу произведения, которую больше некому читать.
    if _throttled(request, 'comment'):
        return _back_to_story(slug, chapter_number)

    form = CommentForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Пікір мәтінін жаз.')
        return _back_to_story(slug, chapter_number)

    parent = None
    parent_id = form.cleaned_data['parent']
    if parent_id:
        # BR-30: ответ — только на верхнеуровневый комментарий этой же
        # работы. Чужой, несуществующий и уже-ответ — не создаём ничего.
        parent = data.top_level_comment_of(slug, parent_id)
        if parent is None:
            messages.error(request, 'Бұл пікірге жауап беруге болмайды.')
            return _back_to_story(slug, chapter_number)

    comment = data.add_comment(story, request.user,
                               text=form.cleaned_data['text'],
                               chapter_number=chapter_number, parent=parent)
    if comment.held:
        # Задержанный комментарий не виден никому (D2), и молчать об этом
        # нельзя: человек решит, что форма сломалась, и напишет ещё раз.
        messages.info(request, 'Пікірің тексеруге жіберілді — модератор қарайды.')
        return _back_to_story(slug, chapter_number)
    messages.success(request, 'Пікірің қосылды.')
    return _back_to_story(slug, chapter_number, anchor=f'comment-{comment.pk}')


@require_POST
@login_required
def comment_delete(request, slug, comment_id):
    """Владение — `belongs_to` (BR-33), та же проверка, что уже решает,
    показывать «Жою» или «Шағым». Чужой комментарий молча не удаляется."""
    comment = data.comment_of(slug, comment_id)
    if comment is not None and comment.belongs_to(request.user.username):
        chapter_number = comment.chapter_number
        data.delete_comment(comment)
        messages.success(request, 'Пікір өшірілді.')
        return _back_to_story(slug, chapter_number)
    return _back_to_story(slug, _chapter_from_post(request))


@require_POST
@login_required
def comment_like(request, slug, comment_id):
    """Toggle (BR-31); на свой комментарий лайк тоже можно поставить —
    правило не запрещает."""
    comment = data.comment_of(slug, comment_id)
    if comment is not None:
        data.toggle_comment_like(comment, request.user)
        return _back_to_story(slug, comment.chapter_number, anchor=f'comment-{comment.pk}')
    return _back_to_story(slug, _chapter_from_post(request))


# ───────────────────── Жалоба (BR-33, FR-STORY-09) ────────────────────────

@require_POST
@login_required
def story_report(request, slug):
    """Шағым бүкіл жұмысқа. `create_report` өзін-өзі шағымдаудан және
    бос себептен қорғайды (BR-33) — форма үнсіз ештеңе жасамай қайтады."""
    if _throttled(request, 'report'):
        return redirect('core:story_detail', slug=slug)
    story = data.story_by_slug(slug, request.user)
    if story is not None:
        report = data.create_report(
            request.user, story=story,
            reason=request.POST.get('reason', ''),
            note=request.POST.get('comment', ''))
        if report is not None:
            messages.success(request, 'Шағымың жіберілді.')
    return redirect('core:story_detail', slug=slug)


@require_POST
@login_required
def comment_report(request, slug, comment_id):
    """Шағым бір пікірге — `comment_like`/`comment_delete` секілді,
    сол бетке, сол якорьмен қайтады."""
    if _throttled(request, 'report'):
        return _back_to_story(slug, _chapter_from_post(request))
    comment = data.comment_of(slug, comment_id)
    if comment is not None:
        report = data.create_report(
            request.user, comment=comment,
            reason=request.POST.get('reason', ''),
            note=request.POST.get('comment', ''))
        if report is not None:
            messages.success(request, 'Шағымың жіберілді.')
        return _back_to_story(slug, comment.chapter_number, anchor=f'comment-{comment.pk}')
    return _back_to_story(slug, _chapter_from_post(request))


# ───────────────────── Библиотека (BR-60/61, FR-LIB-02) ──────────────────

@require_POST
@login_required
def library_toggle(request, slug):
    """Кнопка «Сақтау»: положить работу в библиотеку или снять с полки.
    Гостю она не рендерится — сразу ведёт на вход. Чужой черновик на полку
    не кладётся: его для этого человека нет (BR-76).

    Кнопка живёт и на карточке (BR-96), поэтому возврат идёт по `next`:
    без него сохранение с главной уносило читателя на страницу работы —
    то есть кнопка «сохранить на потом» открывала это самое «потом».
    Адрес чистится `_safe_next` (только относительные пути), умолчание —
    прежний возврат на страницу произведения.
    """
    story = data.story_by_slug(slug, request.user)
    if story is not None:
        saved = data.toggle_library_entry(request.user, story)
        messages.success(request, 'Кітапханаға сақталды' if saved
                         else 'Кітапханадан алынды')
    if request.POST.get('next'):
        return redirect(_safe_next(request))
    return _back_to_story(slug, _chapter_from_post(request))


# ───────────────────── Реакции на главу (BR-REACT-02/03, Ф15 Этап 3) ──────

@require_POST
@login_required
def chapter_react(request, slug, chapter):
    """Ставит, снимает или меняет реакцию на главе; `kind` — один из пяти
    закрытого списка (BR-REACT-01).

    htmx-запрос (`HX-Request`) получает в ответ сам компонент, заново
    отрисованный со свежим счётом, — `reaction_bar.html` подменяет им
    себя же (`hx-swap="outerHTML"`), без перезагрузки страницы. Обычная
    отправка формы (JS выключен) идёт прежним путём — PRG-редирект.
    """
    # Глава ищется по слагу работы, поэтому видимость проверяется по самой
    # работе (BR-76): без этого реакция ставилась бы на главу чужого
    # черновика — страницы нет, а кнопка отвечает.
    visible = data.story_by_slug(slug, request.user) is not None
    ch = data.chapter_of(slug, chapter) if visible else None
    kind = request.POST.get('kind', '')
    # Предел частоты (C4) — молча: у реакции нет своей страницы, и тост
    # поверх htmx-перерисовки читался бы как поломка. Кнопка просто
    # возвращается в прежнее состояние.
    if data.too_often('reaction', request.user):
        ch = None
    if ch is not None and kind in data.REACTIONS_BY_SLUG:
        data.toggle_chapter_reaction(ch, request.user, kind)
    if request.headers.get('HX-Request') == 'true':
        # Голосование обновляет ChapterReaction отдельным UPDATE (F()),
        # а `ch` выше пришёл с prefetch до него — счёт в объекте устарел,
        # поэтому свежий рендер берёт главу заново, а не переиспользует `ch`.
        fresh = data.chapter_of(slug, chapter, request.user)
        return render(request, 'components/reaction_bar.html', {
            'items': data.reactions_of(fresh) if fresh else [],
            'story_slug': slug,
            'chapter_number': chapter,
        })
    return _back_to_story(slug, chapter)


# ───────────────────── Опрос главы (BR-POLL-03/05, Ф15 Этап 4) ────────────

@require_POST
@login_required
def poll_vote(request, slug, chapter):
    """Голос в опросе; закрытый опрос и невалидный или повторный вариант
    `data.cast_poll_vote` тихо отклоняет."""
    # Та же проверка видимости, что у реакции: опрос живёт под главой, а
    # глава — под работой, которой для этого человека может не быть (BR-76).
    poll = (data.poll_of(slug, chapter)
            if data.story_by_slug(slug, request.user) is not None else None)
    option_slug = request.POST.get('option', '')
    if poll is not None and option_slug:
        data.cast_poll_vote(poll, request.user, option_slug)
    return _back_to_story(slug, chapter)
