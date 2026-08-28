"""Авторский кабинет (FR-WRITE-*).

Рейла у этих страниц нет вовсе (DEC-48): агрегаты автора живут в профиле,
кабинет отвечает на «что делать».

Владение проверяется везде одинаково: `story_by_slug_for_author` отдаёт
`None` и на несуществующий слаг, и на чужой (IDOR), поэтому POST-ветка,
завязанная на `story is not None`, уже отказывает и гостю, и постороннему.
Формы отвечают Post/Redirect/Get, исход приезжает тостом через
`django.contrib.messages`.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .. import data
from ..forms import ChapterForm, NewStoryForm, StorySettingsForm
from ..links import attention_links, checklist_links
from .common import _current_user, _page_state


def _report(request, form) -> None:
    """Ошибки формы — тостами (FR-SYS-01), по одной строке на причину.

    Вернуть заполненную форму с подсветкой полей на редиректе нельзя: у
    ответа нет тела. Сообщение называет, что поправить; хранить черновик
    ввода между запросами — отдельная работа.
    """
    for errors in form.errors.values():
        for error in errors:
            messages.error(request, error)


def my_stories(request):
    user = _current_user(request)
    # Агрегатов автора здесь больше нет — DEC-48. Они жили в правом рейле и
    # в полосе под шапкой, повторяя `partials/profile/_stats.html` слово
    # в слово, а на страницах одного произведения тот же рейл читался как
    # статистика этого произведения. Кабинет отвечает на «что делать»,
    # профиль — на «как идёт».
    return render(request, 'pages/write/my_stories.html', {
        # FR-WRITE-08: что требует внимания — модерация, новые пікір, пустой
        # черновик. Страница перечисляла имущество и молчала о том, что делать.
        'attention':  attention_links(user),
        'page_state': _page_state(request),
        # Снимок работ живёт на самом пользователе: полоса внимания и
        # список ниже смотрят в одну и ту же выборку, а не в две.
        'stories':    user.authored if user else [],
        'username':   user.username if user else '',
    })


def new_story(request):
    if request.method == 'POST' and request.user.is_authenticated:
        form = NewStoryForm(request.POST)
        if not form.is_valid():
            _report(request, form)
            return redirect('core:new_story')
        story = data.create_story(
            author=request.user,
            title=form.cleaned_data['title'],
            format=form.cleaned_data['format'],
            genre_primary=form.cleaned_data['genre_primary'])
        messages.success(request, 'Шығарма құрылды — енді мәтін.')
        return redirect('core:chapter_new', slug=story.slug)

    return render(request, 'pages/write/new_story.html', {
        # Форма — три поля (FR-WRITE-01). Название говорит, что увидит
        # читатель: тег к ненаписанному рассказу не выбирается, аннотация
        # к нему не пишется, а «Аяқталды» у нуля бөлім — невозможное
        # состояние (BR-10). Оба поля просятся при отправке на модерацию
        # (FR-WRITE-09), не при создании черновика.
        'genres': data.all_genres(),
    })


def manage_story(request, slug):
    story = data.story_by_slug_for_author(slug, _current_user(request))

    if request.method == 'POST' and story is not None:
        # Единственное действие этой страницы — «Модерацияға жіберу»
        # (publish_panel.html). Отдельного маршрута под него нет: страница
        # уже своя, а действие на ней ровно одно.
        try:
            data.submit_story_for_review(story)
            messages.success(request, 'Шығарма модерацияға жіберілді.')
        except ValueError:
            messages.error(
                request,
                'Әлі дайын емес — чек-листтегі міндетті тармақтарды толтыр.')
        return redirect('core:manage_story', slug=slug)

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
    story = data.story_by_slug_for_author(slug, _current_user(request))

    if request.method == 'POST' and story is not None:
        # Обложку проверяет валидатор поля (BR-46) — ручного вызова
        # `RASTER_ONLY` рядом больше нет, а вместе с ним и шанса забыть его
        # в третьем месте. Статус и второй жанр форма чинит молча: чужое
        # значение значит «не меняем», совпавший жанр — «не выбран».
        form = StorySettingsForm(request.POST, request.FILES, story=story)
        if form.is_valid():
            data.update_story_settings(
                story,
                title=form.cleaned_data['title'],
                annotation=form.cleaned_data['annotation'],
                format=form.cleaned_data['format'],
                genre_primary=form.cleaned_data['genre_primary'],
                genre_secondary=form.cleaned_data['genre_secondary'],
                audience=form.cleaned_data['audience'],
                status=form.cleaned_data['status'],
                cover=form.cleaned_data['cover'],
                tag_names=form.tag_names,
            )
            messages.success(request, 'Өзгертулер сақталды.')
        else:
            _report(request, form)
        return redirect('core:story_settings', slug=slug)

    return render(request, 'pages/write/story_settings.html', {
        'slug':   slug,
        'story':  story,
        'genres': data.all_genres(),
        # BR-10b: отметка выбирается автором, а не достаётся дефолтом.
        'story_audiences': data.STORY_AUDIENCES,
        # docs/ui.md: данные для tag_input + текущие теги стори для edit-режима
        'accepted_tags':    data.accepted_tags_json(),
        'blocked_patterns': data.blocked_tag_patterns_list(),
        'initial_tags':     data.tags_of(story) if story else [],
    })


def chapter_editor(request, slug, chapter=None):
    story = data.story_by_slug_for_author(slug, _current_user(request))

    if request.method == 'POST' and story is not None:
        form = ChapterForm(request.POST)
        if not form.is_valid():
            _report(request, form)
        else:
            saved = data.save_chapter(story, chapter,
                                      title=form.cleaned_data['title'],
                                      body=form.cleaned_data['body'])
            data.save_chapter_poll(saved, form.cleaned_data['poll_question'],
                                   request.POST.getlist('poll_option'))
            chapter = saved.number
            if request.POST.get('action') == 'submit_review':
                try:
                    data.submit_story_for_review(story)
                    messages.success(request, 'Сақталды және модерацияға жіберілді.')
                except ValueError:
                    messages.error(
                        request,
                        'Сақталды. Модерацияға жіберу үшін баптауларда '
                        'аннотация мен жас белгісін толтыр.')
            else:
                messages.success(request, 'Жоба сақталды.')

        if chapter is None:
            return redirect('core:chapter_new', slug=slug)
        return redirect('core:chapter_edit', slug=slug, chapter=chapter)

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


@require_POST
@login_required
def delete_story(request, slug):
    """Опасная зона (FR-WRITE-06): удаление происходит только POST'ом из
    `delete_confirm_modal.html`. Чужая работа не находится вовсе —
    `story_by_slug_for_author` режет по автору (IDOR)."""
    story = data.story_by_slug_for_author(slug, request.user)
    if story is not None:
        title = story.title
        story.delete()
        messages.success(request, f'«{title}» өшірілді.')
        return redirect('core:my_stories')
    return redirect('core:manage_story', slug=slug)
