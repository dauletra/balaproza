"""Свой и чужой профиль, подписчики и подписки (FR-PROF-*).

Разделение, которое здесь легко потерять, — **кто зритель**: посторонний
видит только публичное (BR-73). Правило живёт в слое данных, но выбор
между двумя выдачами делается здесь.
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from .. import data
from ..models import RASTER_ONLY
from .common import _current_username

# ───────────────────────── PROF — профиль ────────────────────────────────
_PROF_TABS_ME    = ("works", "library", "stats", "about")


_PROF_TABS_OTHER = ("works", "about")


def _resolve_prof_tab(request, allowed) -> str:
    tab = request.GET.get('tab', 'works')
    return tab if tab in allowed else 'works'


def _prof_items(facts, allowed: tuple, is_self: bool) -> list:
    """Сегменты PROF (label + count).

    Счётчик работ считается по публичным работам **для обоих** — DEC-44.
    Пока владелец видел здесь ещё и черновики, у сегмента было две
    арифметики, и «Шығармалар 5» открывало список из трёх у постороннего.
    Одно правило, посчитанное один раз, разойтись не может.
    """
    works_n = len(facts.public_stories)
    lib_n   = len(facts.library) if is_self else 0
    labels = {
        "works":   ("Шығармалар", works_n),
        "library": ("Кітапхана",  lib_n),
        # Счётчика у «Статистика» нет: число рядом обещало бы количество
        # чего-то, а вкладка — про состояние, а не про список.
        "stats":   ("Статистика", 0),
        "about":   ("Туралы",     0),
    }
    return [{'slug': k, 'label': labels[k][0], 'count': labels[k][1]} for k in allowed]


def profile_me(request):
    """Свой профиль (FR-PROF-01/03). Реальное переключение секций через ?tab=."""
    username = _current_username(request)
    author = data.author_by_username(username)
    tab = _resolve_prof_tab(request, _PROF_TABS_ME)
    # Один снимок автора на весь рендер. Страница спрашивает его работы
    # из восьми мест — сегменты, две сводки, пять наград, ступени,
    # конкурсная биография, — и пока каждое ходило в базу само, свой
    # профиль стоил пятидесяти девяти запросов.
    facts = data.author_facts(username)
    # Рейл профиля состоит из одного блока «Жазылулар»: без него
    # partials/right_rail/profile.html не рендерит ничего, и гость получал
    # пустую колонку в 300px, которая просто сдвигала гейт от центра.
    following = data.following_of(username) if username else []
    catalog = data.award_catalog(username, facts=facts) if username else []
    ladder = data.read_ladder(username, facts=facts) if username else []
    return render(request, 'pages/profile/profile_me.html', {
        'has_right_rail':  bool(author and following),
        'profile_user':    author,
        'username':        username,
        'is_self':         True,
        'tab':             tab,
        'prof_items':      _prof_items(facts, _PROF_TABS_ME, True) if username else [],
        # DEC-44: профиль — публичный вид на автора, а не второй кабинет.
        # `?tab=works` показывал `my_stories_of` строками `my_story_row` —
        # то есть ровно список из `/my-stories/` минус полоса внимания.
        # Теперь здесь то же, что видит читатель; черновики и модерация
        # живут только в кабинете, а их количество автор видит во вкладке
        # «Статистика» под пометкой «Тек саған көрінеді» (FR-PROF-08).
        'works':           facts.public_stories if username else [],
        'hidden_n':        (len(facts.stories)
                            - len(facts.public_stories)) if username else 0,
        'my_stories_href': reverse('core:my_stories'),
        'lib_reading':     facts.shelf('reading') if username else [],
        'lib_saved':       facts.shelf('saved') if username else [],
        'stats':           data.reader_stats(username, facts=facts) if username else None,
        'achievements':    data.achievements_of(username, facts=facts) if username else [],
        'contest_awards':  data.contest_awards_of(username) if username else [],
        'contests_n':      len(facts.submissions) if username else 0,
        'contest_history': data.contest_history(username, is_self=True,
                                                facts=facts) if username else [],
        # FR-PROF-08 — своя статистика. Ничего из этого посторонний не видит.
        'writer':          data.writer_stats(username, facts=facts) if username else None,
        'award_catalog':   catalog,
        'awards_earned':   sum(1 for a in catalog if a['earned']),
        'read_ladder':     ladder,
        'reads_total':     data.reads_total(username, facts=facts) if username else 0,
        'next_tier':       next((s for s in ladder if s['is_next']), None),
        'following':       following,
        'new_story_href':  reverse('core:new_story'),
        'catalog_href':    reverse('core:catalog'),
    })


def profile_me_edit(request):
    """Редактирование своего профиля (FR-PROF-01, Ф15 Этап 6)."""
    username = _current_username(request)
    author = data.author_by_username(username)

    if request.method == 'POST' and author is not None:
        pen_name = request.POST.get('pen_name', '').strip()
        name = request.POST.get('name', '').strip()
        bio = request.POST.get('bio', '').strip()
        gender = request.POST.get('gender', '')
        age_raw = request.POST.get('age', '').strip()
        avatar = request.FILES.get('avatar')

        errors = []
        if not pen_name:
            errors.append('Авторлық атыңды жаз.')
        elif len(pen_name) > 60:
            errors.append('Авторлық атың тым ұзын — 60 таңбадан аспасын.')
        if not name:
            errors.append('Ресми атыңды жаз.')
        elif len(name) > 120:
            errors.append('Ресми атың тым ұзын — 120 таңбадан аспасын.')
        if len(bio) > 200:
            errors.append('Өзің туралы мәтін тым ұзын — 200 таңбадан аспасын.')
        if gender and gender not in data.GENDERS:
            errors.append('Жынысын дұрыс таңда.')
        age = None
        if age_raw:
            if not age_raw.isdigit() or not (1 <= int(age_raw) <= 120):
                errors.append('Жасын дұрыс жаз.')
            else:
                age = int(age_raw)
        if avatar:
            try:
                RASTER_ONLY(avatar)
            except ValidationError as exc:
                errors.extend(exc.messages)

        if errors:
            for err in errors:
                messages.error(request, err)
            return redirect('core:profile_me_edit')

        data.update_profile(request.user, pen_name=pen_name, name=name,
                            bio=bio, age=age, gender=gender, avatar=avatar)
        messages.success(request, 'Өзгертулер сақталды.')
        return redirect('core:profile_me')

    return render(request, 'pages/profile/profile_me_edit.html', {
        'profile_user': author,
        'username':     username,
    })


def profile_other(request, username):
    """Чужой профиль (FR-PROF-02/04). Кнопка «Жазылу» — если гость, ведёт на login.

    Несуществующий автор — 404, а не страница-заглушка с кодом 200: в проекте
    есть брендированная `404.html`, а прежняя заглушка позволяла поисковику
    проиндексировать любой выдуманный `@username`.

    Данные — только публичные (`public_stories_of` / `public_stats`).
    """
    author = data.author_by_username(username)
    if not author:
        raise Http404(f'Автор @{username} табылмады')
    me = _current_username(request)
    tab = _resolve_prof_tab(request, _PROF_TABS_OTHER)
    # Тот же снимок, что и в своём профиле: работы автора спрашивают
    # сегменты, тело вкладки, рейл, сводка и три награды.
    facts = data.author_facts(username)
    works = facts.public_stories
    # Рейл чужого профиля — «Ең көп оқылғаны», а не «на кого он подписан»
    # (FR-PROF-09). Список чужих подписок читателю ничего не сообщает, а
    # занимал единственный блок рейла.
    #
    # Порог в четыре работы — против дубля: на вкладке «Шығармалар» тело
    # показывает те же самые работы целиком, и топ-3 из трёх был бы точной
    # копией соседней колонки (то же, за что убирали числа —
    # test_desktop_layout.ProfileStatsNotDuplicated). На «Туралы» работ в
    # теле нет вовсе, поэтому там блок полезен с первой.
    rail_top = (
        data.top_stories_of(username, facts=facts)
        if tab == 'about' or len(works) >= 4 else []
    )
    return render(request, 'pages/profile/profile_other.html', {
        'has_right_rail': bool(rail_top),
        'profile_user':  author,
        'username':      username,
        'is_self':       False,
        'tab':           tab,
        'prof_items':    _prof_items(facts, _PROF_TABS_OTHER, False),
        'works':         works,
        'rail_top':      rail_top,
        'stats':         data.public_stats(username, facts=facts),
        # Знаки одинаковы для владельца и для постороннего: достижение
        # публично по определению (FR-PROF-06). Число конкурсов — участие
        # без статуса, поэтому совпадает с длиной публичного списка и не
        # выдаёт вычитанием, что какая-то заявка отклонена (BR-74a).
        'achievements':  data.achievements_of(username, facts=facts),
        'contest_awards': data.contest_awards_of(username),
        'contests_n':    len(facts.submissions),
        # is_self=False режет результат и комментарий жюри (BR-74a)
        'contest_history': data.contest_history(username, facts=facts),
        'is_followed':   data.is_following(me, username) if me else False,
    })


# kind → подпись, список, счётчик. Счётчик отдельной функцией, а не
# `len()` от списка: сегментов на странице два, а открыт один, и второму
# нужно только число.
_PEOPLE_KINDS = {
    'followers': ('Жазылушылар', data.followers_of, data.followers_count_of),
    'following': ('Жазылулар',   data.following_of, data.following_count_of),
}


def profile_people(request, username, kind):
    """Подписчики и подписки автора (FR-PROF-10).

    Оба списка публичны — BR-75. Число подписчиков и так стоит плиткой в
    профиле, а подписки показывал рейл; закрывать список, число из которого
    объявлено, значило бы закрывать не данные, а возможность их прочесть.

    Один view на два набора: страницы отличаются тем, кого показывают, и
    ничем больше. Неизвестный `kind` и неизвестный автор — 404.
    """
    author = data.author_by_username(username)
    if not author or kind not in _PEOPLE_KINDS:
        raise Http404(f'@{username}: {kind} табылмады')

    title, fetch, _ = _PEOPLE_KINDS[kind]
    me = _current_username(request)
    people = fetch(username)
    return render(request, 'pages/profile/profile_people.html', {
        'profile_user': author,
        'username':     username,
        'kind':         kind,
        'title':        title,
        'people':       people,
        'is_self':      me == username,
        # Сегменты ведут между двумя списками одного автора. `?tab=` здесь
        # не годится — список это путь, а не состояние страницы, — поэтому
        # каждый сегмент несёт готовый `href`.
        #
        # Открытый список уже на руках, и его длина берётся отсюда. Раньше
        # цикл звал обе выборки заново, то есть страница делала ту, что
        # показывает, дважды.
        'people_items': [
            {
                'slug':  k,
                'label': lbl,
                'count': len(people) if k == kind else count_of(username),
                'href':  reverse('core:profile_people',
                                 kwargs={'username': username, 'kind': k}),
            }
            for k, (lbl, _list_of, count_of) in _PEOPLE_KINDS.items()
        ],
        'catalog_href': reverse('core:catalog'),
    })
