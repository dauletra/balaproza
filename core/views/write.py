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
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .. import data
from ..forms import (
    POLL_OPTIONS_MAX,
    POLL_OPTIONS_MIN,
    ChapterAutosaveForm,
    ChapterForm,
    NewStoryForm,
    StorySettingsForm,
)
from ..links import attention_links, checklist_links
from .common import _current_user, _found_or_404, _page_state


def _settings_initial(story) -> dict:
    """Чем заполнена форма баптаулар на первом показе.

    Жанры, формат, статус и отметка кладутся **строками-ключами**, а не
    объектами: у связанного поля `value()` вернул бы `Genre`, и шаблон,
    сравнивающий `g.slug == form.genre_primary.value`, тихо перестал бы
    находить выбранное после первой же ошибки формы. Ключ один и тот же
    и на первом показе, и на возврате с ошибкой.
    """
    return {
        'title':           story.title,
        'annotation':      story.annotation,
        'format':          story.format,
        'genre_primary':   story.primary_genre.slug,
        'genre_secondary': (story.secondary_genre.slug
                            if story.secondary_genre else ''),
        'audience':        story.audience,
        # Радио отвечает за «дописано / продолжается», а не за статус:
        # статус выводится из глав (BR-79).
        'status':          'Completed' if story.completed_by_author else 'OnProcess',
        'tags':            ','.join(t.name for t in data.tags_of(story)),
    }


def _poll_option_slots(form) -> list:
    """Поля вариантов опроса: столько, сколько уже набрано, но не меньше
    двух (BR-POLL-02) и не больше четырёх.

    Считается здесь, а не в шаблоне: дополнить список пустыми строками
    средствами шаблонных тегов можно только некрасиво, а само число —
    правило, а не вёрстка.
    """
    values = [v or '' for v in (form['poll_option'].value() or [])]
    values = values[:POLL_OPTIONS_MAX]
    return values + [''] * max(0, POLL_OPTIONS_MIN - len(values))


def _chapter_initial(story, current, poll) -> dict:
    """Чем заполнен редактор главы на первом показе.

    У одночастной работы заголовок не спрашивают по существу — читатель
    его не увидит, — поэтому новой она приходит с готовым «Толық мәтін».
    """
    single_default = 'Толық мәтін' if story is not None and story.is_single else ''
    return {
        'title':         current.title if current is not None else single_default,
        'body':          current.body if current is not None else '',
        'poll_question': poll.question if poll else '',
        'poll_option':   [r.text for r in poll.results] if poll else [],
    }


def _active_chapter_id(request, story):
    """Какая глава открыта в редакторе рабочего места (11.1b): явно —
    `?chapter=<id>`, если она правда принадлежит этой работе (иначе
    параметр — чужой мусор, и его молча игнорируют, а не 404 на всю
    страницу — в отличие от `/chapter/<id>/edit/`, где id — часть
    адреса, а не подсказка); иначе — последняя по порядку написанная;
    иначе — новая (`None`, `is_new=True`), потому что писать больше
    нечего.
    """
    raw = request.GET.get('chapter', '')
    if raw.isdigit() and data.chapter_by_id(story, int(raw)) is not None:
        return int(raw)
    last = story.chapter_set.order_by('position', 'id').last()
    return last.pk if last is not None else None


def _chapter_pane_context(story, slug, chapter, can_submit, missing, *,
                          form=None, current=...) -> dict:
    """Контекст встроенного редактора главы (BR-83) — общий для
    `manage_story` (глава выбрана `?chapter=`, 11.1b) и `chapter_edit`/
    `chapter_new` (глава — часть адреса).

    `can_submit`/`missing` приходят готовыми, а не считаются здесь: это
    ровно то же `can_submit_for_review`/`missing_for_review` от того же
    `story`, что уже посчитала вызывающая сторона для чек-листа —
    второй счёт удвоил бы разбор `publish_checklist` без всякой пользы.

    `current=...` (Ellipsis-заглушка, не `None` — тот законное значение
    «главы нет») — посчитать самой; `chapter_editor` передаёт уже
    посчитанный, тем же запросом, что и её собственная проверка 404, —
    иначе тот же `chapter_by_id` спрашивал бы базу дважды за один показ.

    `form=None` — GET, форма строится начальными значениями главы;
    отклонённый POST передаёт уже провалидированную форму с ошибками.
    """
    if current is ...:
        current = data.chapter_by_id(story, chapter) if story and chapter else None
    poll = getattr(current, 'poll', None)
    if form is None:
        form = ChapterForm(initial=_chapter_initial(story, current, poll))
    return {
        'chapter':   chapter,
        'current':   current,
        'is_new':    chapter is None,
        'form':      form,
        # FR-STORY-13: опрос главы, если автор его уже создал
        'poll':      poll,
        'poll_option_slots': _poll_option_slots(form),
        # BR-78. Адрес зависит от того, есть ли у главы номер: у новой его
        # присвоит первый же ответ сервера.
        'autosave_url': (
            reverse('core:chapter_autosave',
                    kwargs={'slug': slug, 'chapter': chapter}) if chapter
            else reverse('core:chapter_autosave_new', kwargs={'slug': slug})),
        # Пишется рабочая копия, читателю невидимая (BR-79), — поэтому
        # автосохранение доступно и публичной работе тоже.
        'autosave_enabled': story is not None,
        # V14 (AUDIT-WRITE-FLOW): «Модерацияға жіберу» стояла активной и
        # на первой главе новой работы, где аннотации и жас белгісі ещё
        # нет и быть не может, — гарантированный отказ после нажатия.
        # Тот же вопрос, что уже отвечает publish_panel.html.
        'can_submit': can_submit,
        'missing':    missing,
    }


def _workspace_context(story, slug) -> dict:
    """Общее для `manage_story` и `chapter_editor` (11.1b): список глав
    и готовность к отправке — то, что видит `publish_panel.html`
    независимо от того, какая глава сейчас открыта в редакторе рядом.

    `missing` выводится из уже посчитанного `checklist`, а не отдельным
    `missing_for_review(story)`: оба зовут один и тот же
    `publish_checklist` (`has_chapters`, `tags.exists()`), и слитые в
    одну страницу `manage_story`/`chapter_editor` считали бы его дважды
    на одном показе без единой причины.
    """
    checklist = checklist_links(story)
    return {
        # Кабинет показывает все главы, включая неопубликованные (BR-79).
        'chapters': data.chapters_of(slug, as_author=True),
        # FR-WRITE-09: чек-лист как следующий шаг, а не как опись.
        'checklist': checklist,
        'missing': [i['key'] for i in checklist if i['required'] and not i['ok']],
        # Работа уже в очереди — отдельный ответ, не «нельзя отправить»
        # (BR-79): кнопки нет по разным причинам, и автору важно, по какой.
        # Момент, а не флаг: «сколько уже ждёт» — второй его вопрос.
        'pending_since': data.pending_review_since(story),
        # Замечание модератора висит на рабочем экране до повторной
        # отправки (BR-80): помнить его наизусть, пока правишь, — не работа
        # автора.
        'moderation_note': data.moderation_note(story),
    }


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
    """Создание черновика (FR-WRITE-01).

    Неудачная отправка **возвращает форму**, а не редиректит (BR-77): у
    редиректа нет тела, и введённое пропадало вместе с ним. Успех остаётся
    Post/Redirect/Get — от повторной отправки защищаться всё ещё надо.
    """
    author = _current_user(request)
    form = (NewStoryForm(request.POST, author=author) if request.method == 'POST'
           else NewStoryForm())

    if request.method == 'POST' and request.user.is_authenticated and form.is_valid():
        story = data.create_story(
            author=request.user,
            title=form.cleaned_data['title'],
            format=form.cleaned_data['format'],
            genre_primary=form.cleaned_data['genre_primary'])
        messages.success(request, 'Шығарма құрылды — енді мәтін.')
        return redirect('core:chapter_new', slug=story.slug)

    return render(request, 'pages/write/new_story.html', {
        'form': form,
        # Форма — три поля (FR-WRITE-01). Название говорит, что увидит
        # читатель: тег к ненаписанному рассказу не выбирается, аннотация
        # к нему не пишется, а «Аяқталды» у нуля бөлім — невозможное
        # состояние (BR-10). Оба поля просятся при отправке на модерацию
        # (FR-WRITE-09), не при создании черновика.
        'genres': data.all_genres(),
    })


def manage_story(request, slug):
    # Гостю — «кір» (auth_gate, как у my_stories/new_story), не найденному
    # и чужому слагу (уже вошедшему) — 404 (M6/M8 в AUDIT-WRITE-FLOW):
    # раньше оба случая рисовали одну и ту же карточку «табылмады» с кодом
    # 200, и POST на чужой слаг тихо проваливался в неё же.
    user = _current_user(request)
    story = (_found_or_404(data.story_by_slug_for_author(slug, user), f'story {slug!r}')
            if user is not None else None)

    if request.method == 'POST' and story is not None:
        # Действий два — отправить и отозвать (BR-80), и различает их поле
        # формы, а не отдельный маршрут: страница уже своя, обе кнопки
        # стоят в одной панели и относятся к одному и тому же.
        if request.POST.get('action') == 'withdraw':
            if data.withdraw_story_from_review(story):
                messages.success(request, 'Өтінім кері қайтарылды.')
            return redirect('core:manage_story', slug=slug)
        try:
            data.submit_story_for_review(story)
            messages.success(request, 'Шығарма модерацияға жіберілді.')
        except ValueError:
            # Причина называется словами и берётся из чек-листа (BR-81), а
            # не перечисляется на память: прежняя строка говорила «толтыр
            # міндетті тармақтарды» и не называла, какие именно.
            messages.error(
                request,
                'Әлі дайын емес: ' + ', '.join(data.missing_labels(story)) + '.')
        return redirect('core:manage_story', slug=slug)

    context = {'slug': slug, 'story': story}
    if story is not None:
        # 11.1b: рабочее место показывает список глав и редактор
        # выбранной главы на одном экране — `chapter_editor.html` как
        # отдельная страница исчез, `manage_story.html` и `chapter_edit`/
        # `chapter_new` рендерят одно и то же тело
        # (`partials/write/workspace_body.html`).
        context.update(_workspace_context(story, slug))
        can_submit = data.can_submit_for_review(story, context['missing'])
        context.update(_chapter_pane_context(
            story, slug, _active_chapter_id(request, story),
            can_submit, context['missing']))
    return render(request, 'pages/write/manage_story.html', context)


def story_settings(request, slug):
    """Баптаулар (FR-WRITE-04).

    Ошибка возвращает заполненную форму (BR-77). Здесь это стоило дороже
    всего: одна отвергнутая обложка уносила и аннотацию, и отметку, и
    теги — всё, что человек только что набрал. Файл вернуть нельзя,
    браузер его не отдаёт; остальное возвращается целиком.
    """
    user = _current_user(request)
    story = (_found_or_404(data.story_by_slug_for_author(slug, user), f'story {slug!r}')
            if user is not None else None)
    form = None

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
                remove_cover=form.cleaned_data['remove_cover'],
                tag_names=form.tag_names,
            )
            messages.success(request, 'Өзгертулер сақталды.')
            # `story.slug`, а не URL-параметр: переименование до публикации
            # (M1, BR-87) могло сдвинуть адрес прямо в этом запросе.
            return redirect('core:story_settings', slug=story.slug)
    elif story is not None:
        form = StorySettingsForm(story=story, initial=_settings_initial(story))

    return render(request, 'pages/write/story_settings.html', {
        'slug':   slug,
        'story':  story,
        'form':   form,
        'genres': data.all_genres(),
        # BR-10b: отметка выбирается автором, а не достаётся дефолтом.
        'story_audiences': data.STORY_AUDIENCES,
        # docs/ui.md: данные для tag_input + текущие теги стори для edit-режима
        'accepted_tags':    data.accepted_tags_json(),
        'blocked_patterns': data.blocked_tag_patterns_list(),
        # Чипы тегов: сохранённые — на первом показе, набранные — на
        # возврате с ошибкой. Второе не пишется в базу: pending-тег пережил
        # бы работу, которая так и не сохранилась.
        'initial_tags': (data.preview_story_tags(form.tag_names)
                         if form is not None and form.is_bound
                         else data.tags_of(story) if story else []),
    })


def chapter_editor(request, slug, chapter=None):
    """Редактор главы (FR-WRITE-05).

    Здесь возврат формы стоит дороже всего на портале: тело главы —
    единственное, что автор писал часами, и до этого любая ошибка (пустой
    заголовок, вопрос опроса без вариантов) уносила его целиком, а тост
    при этом требовал «жаз мәтінін» — ровно то, что только что стёрли.

    `chapter` в адресе — `pk`, а не номер (BR-83): кабинет не должен
    зависеть от значения, которое сдвигается при удалении или перестановке
    соседних глав.
    """
    user = _current_user(request)
    story = (_found_or_404(data.story_by_slug_for_author(slug, user), f'story {slug!r}')
            if user is not None else None)
    if (story is not None and chapter is None
            and story.is_single and story.chapter_set.exists()):
        # Прямой `/chapter/new/` на уже написанном `single` заводил бы
        # вторую главу в обход интерфейса (S6, BR-85) — интерфейс всегда
        # ведёт «Мәтінді өңдеу» в существующую.
        messages.info(request, 'Бір бөлімді жұмыста бір ғана мәтін болады.')
        return redirect('core:chapter_edit', slug=slug, chapter=story.text_chapter)

    current = data.chapter_by_id(story, chapter) if story and chapter else None
    if story is not None and chapter is not None and current is None:
        # Несуществующий или чужой `pk` — 404, а не пустой «новый» редактор:
        # тем и заводилась дыра в нумерации до этого (S5).
        raise Http404

    rejected_form = None
    if request.method == 'POST' and story is not None:
        form = ChapterForm(request.POST)
        if form.is_valid():
            saved = data.save_chapter(
                story, chapter,
                title=form.cleaned_data['title'],
                body=form.cleaned_data['body'],
                poll_question=form.cleaned_data['poll_question'],
                poll_options=form.poll_options)
            if request.POST.get('action') == 'submit_review':
                try:
                    data.submit_story_for_review(story)
                    messages.success(request, 'Сақталды және модерацияға жіберілді.')
                except ValueError:
                    # Прежняя строка называла «аннотация мен жас белгісі»
                    # на память — и врала, когда не хватало текста. Теперь
                    # подписи живут в домене (BR-81), и причина называется
                    # та, что есть на самом деле.
                    messages.error(
                        request,
                        'Сақталды. Модерацияға жіберу үшін мынау керек: '
                        + ', '.join(data.missing_labels(story)) + '.')
            else:
                messages.success(request, 'Жоба сақталды.')
            return redirect('core:chapter_edit', slug=slug, chapter=saved.pk)
        # Форма невалидна — рендерим страницу заново с ошибками, вместе с
        # остальным телом рабочего места (BR-77): редирект стёр бы набранное.
        rejected_form = form

    context = {'slug': slug, 'story': story}
    if story is not None:
        # 11.1b: то же тело, что у `manage_story` — см. её docstring.
        context.update(_workspace_context(story, slug))
        can_submit = data.can_submit_for_review(story, context['missing'])
        context.update(_chapter_pane_context(
            story, slug, chapter, can_submit, context['missing'],
            form=rejected_form, current=current))
    return render(request, 'pages/write/chapter_editor.html', context)


@require_POST
@login_required
def chapter_autosave(request, slug, chapter=None):
    """Автосохранение черновика главы (BR-78).

    Ограничения «только непубличная работа» здесь больше нет: с
    разделением ревизий (BR-79) автосохранение пишет в **рабочую копию**,
    которой читатель не видит вовсе. Оно и было введено только потому, что
    до разделения записанная глава немедленно уходила читателю.

    Ответ — JSON, а не редирект: у запроса нет страницы, на которую можно
    вернуться. `chapter` в ответе (`pk`, BR-83) обязателен: первый автосейв
    новой главы присваивает ей id, и редактор обязан переключиться на него,
    иначе следующий заход заведёт вторую главу.
    """
    story = data.story_by_slug_for_author(slug, request.user)
    if story is None:
        return JsonResponse({'ok': False, 'reason': 'not_found'}, status=404)
    if chapter is not None and data.chapter_by_id(story, chapter) is None:
        return JsonResponse({'ok': False, 'reason': 'not_found'}, status=404)

    form = ChapterAutosaveForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'reason': 'invalid'}, status=400)

    saved = data.autosave_chapter(story, chapter,
                                  title=form.cleaned_data['title'],
                                  body=form.cleaned_data['body'])
    return JsonResponse({
        'ok': True,
        'chapter': saved.pk,
        'url': reverse('core:chapter_edit',
                       kwargs={'slug': slug, 'chapter': saved.pk}),
        'autosave_url': reverse('core:chapter_autosave',
                                kwargs={'slug': slug, 'chapter': saved.pk}),
        'saved_at': timezone.localtime().strftime('%H:%M'),
    })


@require_POST
@login_required
def chapter_delete(request, slug, chapter):
    """Удалить главу (FR-WRITE-05, BR-84) — опасная зона, как и вся работа:
    POST только из `delete_confirm_modal.html`. Чужая работа не находится
    (IDOR, `story_by_slug_for_author`), чужой `pk` внутри своей — тоже
    (`delete_chapter` фильтрует через `story.chapter_set`)."""
    story = data.story_by_slug_for_author(slug, request.user)
    if story is not None and data.delete_chapter(story, chapter):
        messages.success(request, 'Бөлім өшірілді.')
    return redirect('core:manage_story', slug=slug)


@require_POST
@login_required
def chapter_move(request, slug, chapter):
    """Главу на место выше/ниже (FR-WRITE-05, BR-84). Без toast — новый
    порядок в списке кабинета виден и так."""
    story = data.story_by_slug_for_author(slug, request.user)
    if story is not None:
        data.move_chapter(story, chapter, request.POST.get('direction', ''))
    return redirect('core:manage_story', slug=slug)


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
