"""Авторский кабинет (FR-WRITE-*).

Рейла у этих страниц нет вовсе — DEC-48: агрегаты автора живут в профиле,
кабинет отвечает на «что делать».
"""

from django.shortcuts import render

from .. import data
from ..links import attention_links, checklist_links
from .common import _current_username, _page_state

def my_stories(request):
    username = _current_username(request)
    # Агрегатов автора здесь больше нет — DEC-48. Они жили в правом рейле и
    # в полосе под шапкой, повторяя `partials/profile/_stats.html` слово
    # в слово, а на страницах одного произведения тот же рейл читался как
    # статистика этого произведения. Кабинет отвечает на «что делать»,
    # профиль — на «как идёт».
    facts = data.author_facts(username)
    return render(request, 'pages/write/my_stories.html', {
        # FR-WRITE-08: что требует внимания — модерация, новые пікір, пустой
        # черновик. Страница перечисляла имущество и молчала о том, что делать.
        'attention': attention_links(username, facts) if username else [],
        'page_state': _page_state(request),
        'stories':    facts.stories if username else [],
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


def manage_story(request, slug):
    story = data.story_by_slug_for_author(slug)
    return render(request, 'pages/write/manage_story.html', {
        'slug':     slug,
        'story':    story,
        'chapters': data.chapters_of(slug),
        # FR-WRITE-09: чек-лист как следующий шаг, а не как опись.
        'checklist':  checklist_links(story),
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
