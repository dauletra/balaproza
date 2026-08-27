"""Главная — редакционная витрина (FR-HOME-*)."""

from django.shortcuts import render

from .. import data
from .common import _current_user, _page_state

# HOME
def home(request):
    """Главная — редакционная витрина. Гость vs возвращающийся (FR-HOME-01)."""
    user = _current_user(request)
    is_signed_in = user is not None
    my_stories = user.authored if user else []
    active_work = next((s for s in my_stories if s.status == 'OnProcess'),
                       my_stories[0] if my_stories else None)
    progress = data.reading_progress_of(user)

    # Design-system demo override for the four authenticated hero states.
    hero_state_demo = request.GET.get('hero_state')
    if is_signed_in and hero_state_demo in {'empty', 'reading', 'writing', 'full'}:
        if hero_state_demo == 'empty':
            progress = None
            active_work = None
        elif hero_state_demo == 'reading':
            active_work = None
        elif hero_state_demo == 'writing':
            progress = None

    if not is_signed_in:
        hero_focus = 'guest'
    elif active_work:
        hero_focus = 'writing'
    elif progress:
        hero_focus = 'reading'
    else:
        hero_focus = 'empty'

    # Не литерал 'Published': после DEC-37 опубликованный сериал носит
    # OnProcess или Completed, и по литералу с главной пропали бы все десять.
    published = list(data.public_stories())

    # Жанры на главной — полоса-вывеска, а не навигация (DEC-31): 12 цветных слов
    # объясняют, что это литературный портал, и ведут на /genres/<slug>/.
    # Скроллер произведений активного жанра убран вместе с ?genre= — его работу
    # делают жинақтар и тематические ряды.

    return render(request, 'pages/home.html', {
        'has_right_rail':  True,
        'page_state':      _page_state(request),
        'progress':        progress,
        'active_work':     active_work,
        'hero_focus':      hero_focus,
        'hero_contest':    data.hero_contest(),
        'home_contests':   data.home_contests(),
        'collections':     data.all_collections(),
        'genres':          data.all_genres(),
        'book_of_week':    data.book_of_week(),
        'new_authors':     data.new_authors(4),
        'top_stories':     sorted(published, key=lambda s: s.views, reverse=True)[:5],
        'short_stories':   [s for s in published if s.is_single and s.read_minutes <= 15][:5],
        # Ряд называется «Жалғасып жатқан шығармалар» — значит именно те,
        # что продолжаются, а не все сериалы подряд.
        'serial_stories':  [s for s in published
                            if s.is_serial and s.status == 'OnProcess'][:5],
        'portal_stats':    data.portal_stats(),
        'popular_tags':    data.popular_tags(8),
        'trending_tags':   data.trending_tags(6),
    })
