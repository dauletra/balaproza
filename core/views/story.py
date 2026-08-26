"""Страница произведения и инлайн-чтение главы (FR-STORY-*)."""

from django.shortcuts import render

from .. import data
from .common import _current_username

# ───────────────────────── STORY — произведение и чтение ─────────────────
def story_detail(request, slug):
    # Неизвестный slug отдаёт None: страница остаётся валидной и говорит
    # «Шығарма табылмады», а не падает 500.
    story = data.story_by_slug(slug)
    chapters = data.chapters_of(slug)
    # Автор своего стори видит pending-теги (BR-TAG-07). Для прочих скрыты.
    viewer = _current_username(request)
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
