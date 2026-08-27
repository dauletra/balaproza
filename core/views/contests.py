"""Конкурсы: список, страница, подача, свои заявки (FR-CONT-*)."""

from django.contrib import messages
from django.shortcuts import redirect, render

from .. import data
from .common import _current_username, _page_state

# ───────────────────────── CONT — конкурсы ───────────────────────────────
def contest_list(request):
    return render(request, 'pages/contests/contest_list.html', {
        # DEC-17 требует состояний на всех data-зависимых страницах, и
        # раздел конкурсов был единственным, где их не было ни на одной.
        'page_state':        _page_state(request),
        # Секций по-прежнему две, но «идущий» больше не значит «принимает
        # заявки»: точную фазу называет бейдж на карточке (DEC-45).
        'active_contests':   data.open_contests(),
        'finished_contests': data.finished_contests(),
    })


# С какого числа работ в выборе появляется поиск по ним. Ниже порога поле
# только отнимает строку: список и так виден целиком. Выше — выбор
# превращается в прокрутку, и работа, которую автор ищет, может быть
# сороковой. Порог, а не «всегда»: у большинства авторов работ единицы.
PICKER_SEARCH_FROM = 8


def _contest_rail_has_content(contest, *, submitted: bool, hide_cta: bool) -> bool:
    """Есть ли что показать в правом рейле конкурса (DEC-25).

    Флаг ставится по наличию данных, а не безусловно: `partials/right_rail/
    contest.html` пуст у неизвестного слага и у завершённого конкурса, все
    этапы которого уже позади, — а пустая колонка в 300px не пустует, она
    сдвигает контент от центра. Ровно эту ошибку в кабинете закрывал
    `test_write.MyStoriesGuestHasNoEmptyRail`.
    """
    if not contest:
        return False
    if contest.current_stage or contest.next_stage:
        return True
    # Блок «моя заявка» живёт только у активного конкурса, а на самой
    # странице подачи от него остаётся лишь строка об уже поданной работе.
    return contest.is_accepting and (submitted or not hide_cta)


def contest_detail(request, slug):
    contest = data.contest_by_slug(slug)
    username = _current_username(request)
    submitted = data.has_submission(username, slug) if username else False
    return render(request, 'pages/contests/contest_detail.html', {
        'has_right_rail': _contest_rail_has_content(contest, submitted=submitted,
                                                    hide_cta=False),
        'page_state':     _page_state(request),
        'slug':           slug,
        'contest':        contest,
        # Общие правила приходят из одного реестра (BR-48a), а не
        # переписываются в `conditions` каждого конкурса.
        'common_rules':   data.common_rules(contest) if contest else [],
        # Присуждения, а не просто работы: строка победителя называет
        # номинацию, а её знает только грант (DEC-46).
        'grants':         contest.grants if contest else [],
        # Все допущенные работы, не только победители — «список
        # участников» после описания (BR-74a решает видимость).
        'participants':   data.contest_participants(contest) if contest else [],
        'already_submitted': submitted,
    })


def contest_submit(request, slug):
    contest = data.contest_by_slug(slug)
    username = _current_username(request)

    if request.method == 'POST' and username and contest:
        # Кандидаты — те же публичные работы автора, что и на GET (BR-10,
        # DEC-23): чужой или непубличный slug просто не найдётся здесь,
        # и отдельной проверки владения форме не нужно.
        candidates = {c['story'].slug: c['story']
                     for c in data.submission_candidates(username, contest)}
        story = candidates.get(request.POST.get('story_slug', ''))
        ai_declaration = request.POST.get('ai_used', '')
        age_confirmed = bool(request.POST.get('confirm_age'))
        rules_confirmed = bool(request.POST.get('confirm_rules'))

        errors = []
        if not contest.is_accepting:
            errors.append('Өтінім қабылдау аяқталды.')
        if story is None:
            errors.append('Шығарманы таңда.')
        if ai_declaration not in data.AI_DECLARATIONS:
            errors.append('AI-декларацияға жауап бер.')
        if contest.eligibility_line and not age_confirmed:
            errors.append('Жас талабына сай екеніңді раста.')
        if not rules_confirmed:
            errors.append('Байқау ережелерімен келісуді раста.')

        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            _, created = data.create_submission(
                request.user, contest, story, ai_declaration=ai_declaration,
                age_confirmed=age_confirmed, rules_confirmed=rules_confirmed)
            if created:
                messages.success(request, 'Өтінім жіберілді.')
            else:
                # Екінші рет басу немесе тікелей POST — BR-23 бір автордан
                # бір өтінім алдын ала тексерілсе де, жарыс жағдайынан.
                messages.error(request, 'Сен бұл байқауға өтінім бергенсің.')
        return redirect('core:contest_submit', slug=slug)

    submitted = data.has_submission(username, slug) if username else False
    # Конкурс и работы автора берутся по одному разу и раздаются дальше:
    # через слаг и `submission_candidates`, и `can_withdraw` тянули бы
    # состав конкурса заново — по шесть запросов на каждый вызов.
    facts = data.author_facts(username)
    candidates = (data.submission_candidates(username, contest, facts=facts)
                  if (username and contest) else [])

    # Выбранная по умолчанию — первая без заметок, иначе просто первая.
    # Отклонять форма ничего не отклоняет (BR-24), но начинать выбор с
    # работы, о которой есть что сказать, незачем.
    preview = next((c for c in candidates if not c['notes']),
                   candidates[0] if candidates else None)
    preview_story = preview['story'] if preview else None
    checklist = (
        data.submission_checklist(preview_story, contest, chars=preview['chars'])
        if preview and contest else []
    )
    # Чек-лист зависит от выбранной работы, а выбор меняется в браузере.
    # Раньше он считался один раз для превью и застывал: автор переключал
    # радио, а объём под ним оставался чужим. Пересчёт — на стороне
    # клиента, из этой таблицы (FR-CONT-04).
    volumes = {}
    for item in candidates:
        # Объём уже посчитан в `submission_candidates` — передаём его, а не
        # спрашиваем главы по второму разу на каждую работу автора.
        vol = next(c for c in data.submission_checklist(item['story'], contest,
                                                        chars=item['chars'])
                   if c['key'] == 'volume')
        volumes[item['story'].slug] = {
            'passed': vol['passed'],
            'hint':   vol['hint'],
            # Название нужно поиску по списку: фильтровать по DOM-тексту
            # значит зависеть от вёрстки метки.
            'title':  item['story'].title,
        }
    return render(request, 'pages/contests/contest_submit.html', {
        'has_right_rail':    _contest_rail_has_content(contest, submitted=submitted,
                                                       hide_cta=True),
        # Кнопка «Қатысу» в рейле вела бы на страницу, которая уже открыта.
        'hide_submit_cta':   True,
        'slug':              slug,
        'contest':           contest,
        'candidates':        candidates,
        'preview_story':     preview_story,
        'initial_slug':      preview_story.slug if preview_story else '',
        'volumes':           volumes,
        # Поиск по своим работам появляется, только когда список длинный:
        # у автора с тремя работами поле над ними — лишний элемент.
        'picker_search':     len(candidates) > PICKER_SEARCH_FROM,
        'checklist':         checklist,
        'can_withdraw':      data.can_withdraw(username, contest) if username else False,
        'already_submitted': submitted,
    })


def my_submissions(request):
    username = _current_username(request)
    # «Когда узнаю?» — первый вопрос после подачи, и до CONT-5 страница на
    # него не отвечала вовсе: статус «Қаралуда» стоял без единой даты.
    items = [
        {
            'sub':          sub,
            'contest':      sub.contest,
            # Готовый объект, а не слаг: через слаг ответ стоил полной
            # выборки конкурса со всем составом — на каждую строку.
            'can_withdraw': data.can_withdraw(username, sub.contest),
        }
        for sub in (data.submissions_of(username) if username else [])
    ]
    return render(request, 'pages/contests/my_submissions.html', {
        'page_state': _page_state(request),
        'items': items,
        # Модалка подключается только когда ей есть что подтверждать:
        # иначе на странице висел бы слушатель события, которое некому
        # послать.
        'any_withdrawable': any(i['can_withdraw'] for i in items),
    })


def contest_withdraw(request, slug):
    """Отзыв заявки (BR-23b). GET безопасен — ничего не отзывает: настоящий
    POST приходит из `withdraw_confirm_modal.html`. Условие (приём ещё
    идёт, жюри ещё не решило) проверяет `data.withdraw_submission` заново —
    `can_withdraw` на странице решает только, показать ли кнопку."""
    username = _current_username(request)
    contest = data.contest_by_slug(slug)
    if request.method == 'POST' and contest is not None and username:
        if data.withdraw_submission(username, contest):
            messages.success(request, 'Өтінім қайтарып алынды.')
        else:
            messages.error(request, 'Өтінімді қайтарып алу мүмкін болмады.')
    return redirect('core:my_submissions')
