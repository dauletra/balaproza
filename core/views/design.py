"""Внутренние витрины дизайн-системы. Только при DEBUG."""

from django.conf import settings
from django.http import Http404
from django.shortcuts import render

from .. import data

# ───────────────────── DESIGN — внутренние страницы (только DEBUG) ────────
def design_components(request):
    """Каталог всех атомов во всех состояниях. Только при DEBUG."""
    if not settings.DEBUG:
        raise Http404
    accepted = [t for t in data.all_tags() if t.status == 'accepted']
    pending  = [t for t in data.all_tags() if t.status == 'pending']
    # Микс accepted + pending — иллюстрирует фильтрацию tag_list по viewer
    mixed = accepted[:3] + pending[:2]
    return render(request, 'pages/_design/components.html', {
        'genres':    data.all_genres(),
        'stories':   data.public_stories(),
        'authors':   data.all_authors(),
        # Стаб-набор покрывает все четыре фазы (DEC-45), поэтому showcase
        # бейджа — это просто перебор конкурсов, а не четыре ручных вызова
        # с выдуманными аргументами, которые разойдутся с компонентом.
        'contests':  data.all_contests(),
        # docs/ui.md — showcase тегов
        'showcase_tags_accepted': accepted[:8],
        'showcase_tags_pending':  pending,
        'showcase_tags_mixed':    mixed,
        # для интерактивного tag_input
        'accepted_tags':    data.accepted_tags_json(),
        'blocked_patterns': data.blocked_tag_patterns_list(),
    })


def design_states(request):
    """Каталог всех loading/error/empty состояний (DEC-17). Только при DEBUG."""
    if not settings.DEBUG:
        raise Http404
    return render(request, 'pages/_design/states.html', {
        'sample_story':   data.public_stories().first(),
        # По одному настоящему объекту каждого вида: витрина состояний
        # должна показывать то же, что живые страницы, иначе она
        # рассказывает про вёрстку, которой нет.
        'sample_entry':   data.library_of('aidana')[0],
        'sample_notif':   next(iter(sum(
            data.notifications_for_user('aidana').values(), [])), None),
        'sample_comment': data.comments_of('dalney-berega')[0],
    })


def design_tokens(request):
    if not settings.DEBUG:
        raise Http404
    icon_names = [
        # навигация
        'search', 'arrow-right', 'arrow-left', 'angle-left', 'angle-right',
        'chevron-left', 'chevron-right', 'x',
        # действия
        'home', 'bookmark', 'bookmark-filled', 'bell', 'user-circle', 'plus',
        'pen', 'cog', 'trash', 'upload', 'paper-plane', 'list', 'check',
        'adjustments', 'book', 'arrow-right-to-bracket',
        # метрики
        'thumbs-up', 'thumbs-up-filled', 'eye', 'message-caption',
        'heart', 'heart-filled',
        # меню
        'dots-horizontal', 'dots-vertical',
    ]
    return render(request, 'pages/_design/tokens.html', {'icon_names': icon_names})
