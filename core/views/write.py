"""Авторский кабинет (FR-WRITE-*).

Рейла у этих страниц нет вовсе — DEC-48: агрегаты автора живут в профиле,
кабинет отвечает на «что делать».

Ф15, Этап 1: формы читают и пишут. Владение проверяется одним и тем же
способом везде — `data.story_by_slug_for_author(slug, username)` отдаёт
`None` и на несуществующий slug, и на чужой (Ф15, IDOR): POST-ветка,
завязанная на `story is not None`, тем самым уже отказывает и гостю
(`username == ''` не совпадёт ни с одним автором), и постороннему автору —
отдельной проверки авторизации на эти четыре view не нужно. Формы отвечают
Post/Redirect/Get: `django.contrib.messages` + мост в `base.html`
(`core/tests/test_toast_bridge.py`) превращает исход в тот же toast, что
раньше рисовала Alpine-заглушка.
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from .. import data
from ..links import attention_links, checklist_links
from ..models import RASTER_ONLY
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
    if request.method == 'POST' and request.user.is_authenticated:
        title = request.POST.get('title', '').strip()
        fmt = request.POST.get('format', '')
        genre = data.genre_by_slug(request.POST.get('genre_primary', ''))
        if not title or fmt not in data.STORY_FORMATS or genre is None:
            messages.error(request, 'Атауын, форматын және негізгі жанрын таңда.')
            return redirect('core:new_story')
        story = data.create_story(
            author=request.user, title=title, format=fmt, genre_primary=genre)
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
    username = _current_username(request)
    story = data.story_by_slug_for_author(slug, username)

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
    username = _current_username(request)
    story = data.story_by_slug_for_author(slug, username)

    if request.method == 'POST' and story is not None:
        title = request.POST.get('title', '').strip()
        annotation = request.POST.get('annotation', '').strip()
        fmt = request.POST.get('format', '')
        audience = request.POST.get('audience', '')
        status = request.POST.get('status', '')
        cover = request.FILES.get('cover')
        tag_names = request.POST.get('tags', '').split(',')

        genre_primary = data.genre_by_slug(request.POST.get('genre_primary', ''))
        genre_secondary = data.genre_by_slug(request.POST.get('genre_secondary', ''))
        if genre_secondary and genre_primary and genre_secondary.pk == genre_primary.pk:
            # Второй жанр не выбирают тем же самым — тихо игнорируем, а не
            # ругаем: это не то, ради чего форму стоит возвращать с ошибкой.
            genre_secondary = None

        errors = []
        if not title:
            errors.append('Атауын жаз.')
        if genre_primary is None:
            errors.append('Негізгі жанрды таңда.')
        if fmt not in data.STORY_FORMATS:
            errors.append('Форматты таңда.')
        if audience and audience not in data.AUDIENCE_ORDER:
            errors.append('Жас белгісі дұрыс емес.')
        if fmt == 'single' and story.chapter_set.count() > 1:
            # Бір бөлімді пішін бір ғана бөлімге лайықталған (Story.text_chapter,
            # docs/12 §12.2) — бірнеше жазылған бөлімі бар жұмысты ауыстыру
            # деректі бұзады, сондықтан бұл ауысу рұқсат етілмейді.
            errors.append(
                'Бірнеше бөлімі жазылған жұмысты бір бөлімді пішінге ауыстыруға болмайды.')
        if cover:
            # Тікелей `story.cover = cover; story.save()` (қасиеттің
            # `validators=[RASTER_ONLY]`-ін іске қоспайды — ол тек
            # ModelForm арқылы толық `clean()`-де жұмыс істейді), сондықтан
            # SVG осында айқын тексеріледі (BR-46, `avatar`-мен бірдей).
            try:
                RASTER_ONLY(cover)
            except ValidationError as exc:
                errors.extend(exc.messages)

        # `status`-радио шаблонда тек ашық сериалға ғана шығады (BR-10a,
        # BR-11) — POST соны айналып өтсе де, рұқсат етілмеген мән қабылданбайды.
        allowed_status = (('OnProcess', 'Completed')
                          if story.is_public and story.is_serial else ())
        if status and status not in allowed_status:
            status = ''

        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            data.update_story_settings(
                story, title=title, annotation=annotation, format=fmt,
                genre_primary=genre_primary, genre_secondary=genre_secondary,
                audience=audience, status=status, cover=cover,
                tag_names=tag_names,
            )
            messages.success(request, 'Өзгертулер сақталды.')
        return redirect('core:story_settings', slug=slug)

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
    username = _current_username(request)
    story = data.story_by_slug_for_author(slug, username)

    if request.method == 'POST' and story is not None:
        title = request.POST.get('title', '').strip()
        body = request.POST.get('body', '')
        if not title or not body.strip():
            messages.error(request, 'Атауын және мәтінін жаз.')
        else:
            saved = data.save_chapter(story, chapter, title=title, body=body)
            data.save_chapter_poll(saved, request.POST.get('poll_question', ''),
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


def delete_story(request, slug):
    """Опасная зона (FR-WRITE-06). GET безопасен — ничего не удаляет и
    просто возвращает в кабинет: удаление происходит только POST'ом из
    `delete_confirm_modal.html`."""
    username = _current_username(request)
    story = data.story_by_slug_for_author(slug, username)
    if request.method == 'POST' and story is not None:
        title = story.title
        story.delete()
        messages.success(request, f'«{title}» өшірілді.')
        return redirect('core:my_stories')
    return redirect('core:manage_story', slug=slug)
