"""Раздел модерации (FR-MOD-*, DEC-71).

Раньше это были действия в списке админки. Решение они принимали, но
работу модератора не поддерживали: текст лежал инлайном глав — номерами,
повторная подача была неотличима от первой, очередь не приоритизировалась,
и двое, открывшие одну работу, узнавали друг о друге по результату.

Доступ — `is_staff`, и отказ здесь **404, а не 403** (BR-82): существование
раздела не подтверждается тому, кому он не открыт, ровно как и чужой
черновик (BR-76).
"""

from functools import wraps

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .. import data
from ..domain.moderation import QUEUE_FILTER_KEYS
from .common import _current_user


def moderator_only(view):
    """Раздел открыт `is_staff` и больше никому.

    404, а не 403: «нельзя» подтверждало бы, что раздел есть. Гость сюда
    тоже не редиректится на вход — ему нечего здесь ждать.

    Стоит **снаружи** `require_POST`, а не под ним: обратный порядок
    отвечал на GET посторонним 405 «метод не разрешён», то есть
    подтверждал существование адреса — ровно то, чего это правило и не
    должно допускать.
    """
    @wraps(view)
    def guarded(request, *args, **kwargs):
        user = _current_user(request)
        if user is None or not user.is_staff:
            raise Http404('Бөлім табылмады')
        return view(request, *args, **kwargs)
    return guarded


@moderator_only
def moderation_queue(request):
    """Очередь: что ждёт решения и с чего начать (FR-MOD-01)."""
    user = _current_user(request)
    kind = request.GET.get('kind', '')
    if kind not in QUEUE_FILTER_KEYS:
        kind = ''

    return render(request, 'pages/moderation/queue.html', {
        'stories':     data.moderation_queue(kind=kind, moderator=user),
        'kind':        kind,
        'filters':     data.QUEUE_FILTERS,
        'total':       data.queue_size(),
        'held_comments': data.held_comments_count(),
        'slow_days':   data.QUEUE_SLOW_DAYS,
        # Обещание «тәулік ішінде» стоит у автора на экране отправки, и
        # видно оно должно быть с той стороны, где его выполняют (D1).
        'overdue':     data.overdue_count(),
        'promise_hours': data.REVIEW_PROMISE_HOURS,
        'open_reports': data.open_reports_count(),
    })


@moderator_only
def moderation_detail(request, slug):
    """Карточка решения: текст, сравнение с опубликованным, история и три
    исхода (FR-MOD-02…05)."""
    story = data.story_for_moderation(slug)
    if story is None:
        raise Http404(f'Шығарма «{slug}» табылмады')

    submitted = data.submitted_chapters(story)
    # Сводка различий живёт на самом пункте: параллельный список пришлось
    # бы индексировать из шаблона, а такого фильтра в проекте нет и заводить
    # его ради одной страницы незачем.
    for item in submitted:
        item['summary'] = data.diff_summary(item['diff'])

    return render(request, 'pages/moderation/detail.html', {
        'story':      story,
        'submitted':  submitted,
        'history':    data.decision_history(story),
        'templates':  data.REASON_TEMPLATES,
        'claim':      getattr(story, 'claim', None),
        'viewer':     _current_user(request),
        # Работа могла быть отозвана автором, пока модератор читал: решать
        # нечего, и три кнопки об этом молчали бы (BR-79).
        'has_pending': bool(submitted),
    })


@moderator_only
@require_POST
def moderation_claim(request, slug):
    """Взять работу в работу или отпустить (BR-82)."""
    story = data.story_for_moderation(slug)
    if story is None:
        raise Http404(f'Шығарма «{slug}» табылмады')

    user = _current_user(request)
    if request.POST.get('action') == 'release':
        data.release_story(story, user)
    else:
        claim = data.claim_story(story, user)
        if claim.moderator_id != user.pk:
            messages.error(
                request,
                f'Бұл шығарманы {claim.moderator.public_name} алып қойған.')
    return redirect('core:moderation_detail', slug=slug)


@moderator_only
@require_POST
def moderation_decide(request, slug):
    """Решение по поданному тексту (BR-11, BR-79, BR-82).

    Причина отрицательного исхода обязательна — её проверяет и
    `apply_moderation`, но сообщение отсюда адресно и возвращает на ту же
    карточку, где набран текст.
    """
    story = data.story_for_moderation(slug)
    if story is None:
        raise Http404(f'Шығарма «{slug}» табылмады')

    outcome = request.POST.get('outcome', '')
    reason = (request.POST.get('reason') or '').strip()
    try:
        story.apply_moderation(outcome, reason, moderator=_current_user(request))
    except ValueError as error:
        messages.error(request, str(error))
        return redirect('core:moderation_detail', slug=slug)

    messages.success(
        request,
        f'«{story.title}»: {data.MODERATION_OUTCOME_LABELS[outcome]}. '
        f'Авторға хабарлама жіберілді.')
    return redirect('core:moderation_queue')


# ───────────────────── Сводка портала (D6) ───────────────────────────────

@moderator_only
def portal_summary(request):
    """Что происходит на портале — своей базой, без стороннего счётчика.

    В разделе модерации, а не отдельной админкой: смотрит их тот же
    человек, что и очередь, и сводка без очереди рядом отвечает на
    «сколько», не отвечая на «что с этим делать».

    Рядом с каждым числом — оно же неделю назад. Страница отвечала
    «сколько сейчас» и не умела ответить «растёт или падает»: в базе
    лежат только текущие числа, а вчерашние не восстанавливаются ничем —
    аккаунты удаляются полностью, работы сносятся, журнал оқылым живёт
    две недели. Сравнение поэтому приходит из суточных снимков
    (`snapshot_portal`), а не из пересчёта.

    `None` за ту неделю — нормальный ответ первые семь дней, и страница
    его выдерживает: колонка просто не рисуется.
    """
    return render(request, 'pages/moderation/summary.html', {
        'summary': data.portal_summary(),
        'week_ago': data.portal_day_ago(),
        'promise_hours': data.REVIEW_PROMISE_HOURS,
        # Подпись со сроком внутри собирается в домене, рядом с самим
        # сроком: в шаблоне она стала бы вторым местом, где он записан.
        'overdue_label': data.overdue_label(),
    })


# ───────────────────── Задержанные пікірлер (D2) ──────────────────────────

@moderator_only
def held_comments_queue(request):
    """Пікірлер, блок-тізімге іліккен: жарияланбай, шешім күтіп тұр.

    Отдельной страницей, а не вкладкой очереди работ: решается здесь
    другое — не текст автора, а одна реплика, и решений два вместо трёх.
    """
    return render(request, 'pages/moderation/comments.html', {
        'comments': data.held_comments(),
    })


@moderator_only
@require_POST
def held_comment_decide(request, pk):
    """Пропустить к читателю или удалить. Третьего нет: задержанный
    комментарий нельзя «вернуть на доработку» — правки у комментариев не
    бывает."""
    comment = data.held_comment_by_id(pk)
    if comment is None:
        raise Http404('Пікір табылмады')

    if request.POST.get('action') == 'publish':
        data.publish_held_comment(comment)
        messages.success(request, 'Пікір жарияланды.')
    else:
        data.delete_comment(comment)
        messages.success(request, 'Пікір өшірілді.')
    return redirect('core:moderation_comments')


# ───────────────────── Жалобы (BR-33, FR-STORY-09) ────────────────────────

@moderator_only
def reports_queue(request):
    """Ашық шағымдар, ең ұзақ тұрғаны бірінші — ревизия кезегіндегідей."""
    return render(request, 'pages/moderation/reports.html', {
        'reports': data.open_reports(),
    })


@moderator_only
@require_POST
def report_resolve(request, pk):
    """Шешім: «бұзушылық жоқ» немесе контентті алып тастау (BR-33).

    Алып тастауға себеп міндетті — `Story.take_down`/`resolve_report`
    соны талап етеді; бос қалса, `ValueError` осында ұсталады, дәл
    `moderation_decide`-дегідей.
    """
    report = data.report_by_id(pk)
    if report is None:
        raise Http404('Шағым табылмады')

    try:
        data.resolve_report(
            report, _current_user(request),
            action=request.POST.get('action', ''),
            reason=(request.POST.get('reason') or '').strip())
    except ValueError as error:
        messages.error(request, str(error))
        return redirect('core:moderation_reports')

    messages.success(request, 'Шағым қаралды.')
    return redirect('core:moderation_reports')
