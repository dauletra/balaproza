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
        'slow_days':   data.QUEUE_SLOW_DAYS,
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


@require_POST
@moderator_only
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


@require_POST
@moderator_only
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
