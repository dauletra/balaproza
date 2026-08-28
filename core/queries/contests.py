"""Конкурсы: списки, правила, подача, конкурсная биография.

«Можно подать» и «конкурс не завершён» — разные вопросы (DEC-45): кнопку
«Қатысу» решает `is_accepting`, знак «Байқауға қатысады» — `not
is_finished`. Одним словом «активен» они не называются.

Форма ничего не отклоняет (BR-24): у кандидатов бывают заметки, но решение
принимает человек.
"""

from django.db.models import Prefetch, prefetch_related_objects
from django.utils import timezone

from ..domain.catalog import PUBLIC_STATUSES
from ..domain.contests import (
    CONTEST_RESULT_LABELS,
    PUBLIC_CONTEST_RESULTS,
    SUBMISSION_NOTES,
    eligibility_line,
)
from ..domain.formatting import spaced_number
from ..models import Contest, Submission
from .catalog import all_stories

# Порядок открытых конкурсов — по тому, что читатель может сделать:
# сначала куда можно подать прямо сейчас, потом что откроется, потом что
# уже судят. Алфавит и порядок заведения такой вопрос не решают.
_OPEN_ORDER = ('accepting', 'upcoming', 'judging')


def all_contests():
    return Contest.objects.for_card()


def contest_by_slug(slug: str):
    return Contest.objects.full().filter(slug=slug).first()


def contest_participants(contest) -> list:
    """Работы конкурса, доступные читателю (BR-74a): accepted + победители.

    Победа не отдельный статус заявки — она читается через `contest.grants`.
    Ждёт конкурс из `contest_by_slug`: иначе `contest.grants` тянет
    присуждения отдельным запросом.
    """
    grants_by_story = {g.story_id: g for g in contest.grants}
    # Работа приезжает выборкой карточки, а не `select_related`: список
    # рисует её карточкой, а `select_related` аннотировать связанный объект
    # не умеет — время чтения стоило бы `COUNT` на каждого допущенного.
    subs = (Submission.objects
            .filter(contest=contest, status='accepted',
                    story__status__in=PUBLIC_STATUSES)
            .prefetch_related(Prefetch('story', queryset=all_stories()))
            .order_by('story__title'))
    out = []
    for sub in subs:
        grant = grants_by_story.get(sub.story_id)
        out.append({'story': sub.story,
                    'result': 'winner' if grant else 'accepted',
                    'label': grant.award.title if grant
                             else CONTEST_RESULT_LABELS['accepted']})
    return out


def open_contests() -> list:
    """Незавершённые — в порядке того, что с ними можно сделать. Список, а не
    queryset: порядок задан последовательностью фаз, а фаза выводится из
    трёх дат (DEC-45), и `ORDER BY` её не выражает."""
    return sorted(Contest.objects.for_card().unfinished(),
                  key=lambda c: _OPEN_ORDER.index(c.phase))


def accepting_contests():
    return Contest.objects.for_card().accepting()


def finished_contests():
    return Contest.objects.for_card().finished()


def home_contests(limit: int = 4) -> list:
    """Конкурсы для секции «Байқаулар» на главной: порядок `open_contests`,
    хвост добирают недавно завершённые — иначе секция пустеет в межсезонье.
    """
    return (open_contests() + list(finished_contests()))[:limit]


def hero_contest():
    """Конкурс для баннера главной — тот, чей приём закрывается раньше всех.

    Именно `is_accepting`, а не «не завершён»: баннер зовёт участвовать, и
    вести на конкурс с закрытым приёмом значит не выполнить обещание
    страницы. Без `prefetch`: состав баннеру не нужен.
    """
    return Contest.objects.accepting().order_by('closes_on', 'pk').first()


def submissions_of(user):
    """Заявки автора, без присуждений: они нужны одной `contest_history`, и
    она добирает их сама."""
    if user is None:
        return Submission.objects.none()
    return (Submission.objects.filter(author=user)
            .select_related('contest', 'story', 'story__author'))


def has_submission(user, contest_slug: str) -> bool:
    """BR-23: один автор — одна работа на конкретный конкурс."""
    return user is not None and Submission.objects.filter(
        author=user, contest__slug=contest_slug).exists()


def busy_contest_of(user, story_slug: str, *, besides: str = ''):
    """Незавершённый конкурс, который уже держит эту работу (BR-23a).

    Одна работа не идёт в двух сразу: жюри читают параллельно, и одним
    текстом нельзя выиграть дважды. Завершённый не мешает.
    """
    if user is None:
        return None
    rows = (Submission.objects
            .filter(author=user, story__slug=story_slug,
                    contest__results_on__gt=timezone.localdate())
            .exclude(contest__slug=besides)
            .select_related('contest'))
    row = rows.first()
    return row.contest if row else None


def can_withdraw(user, contest) -> bool:
    """Можно ли отозвать заявку (BR-23b): пока идёт приём и жюри не вынесло
    решения. Без отзыва «одна работа на конкурс» означало бы: ошибся
    работой — и всё. Готовый конкурс наравне со слагом, потому что список
    заявок спрашивает это построчно, а слаг тянул бы весь состав."""
    if isinstance(contest, str):
        # Без `contest_by_slug`: здесь нужны три даты, а не состав.
        contest = Contest.objects.filter(slug=contest).first()
    if user is None or not contest or not contest.is_accepting:
        return False
    return Submission.objects.filter(author=user, contest=contest,
                                     status='reviewing').exists()


def common_rules(contest) -> list:
    """Правила, действующие на любом конкурсе (BR-48a); в условия отдельного
    конкурса они не переписываются.

    `per_work` — проверяется ли правило у конкретной работы: «Бір автор —
    бір өтінім» относится к автору, а не к тексту, и его держит сама форма.
    Возраста здесь нет и быть не может — его ставит конкурс (BR-48).
    """
    lo, hi = spaced_number(contest.min_chars), spaced_number(contest.max_chars)
    return [
        {'key': 'volume', 'per_work': True,
         'label': f'Көлемі {lo}-{hi} таңба',
         'hint': 'Бөлімдердегі таңба саны бойынша есептеледі.'},
        {'key': 'language', 'per_work': True,
         'label': 'Тіл — қазақша немесе орысша, байқау шектеуі мүмкін',
         'hint': 'Платформа екі тілді қолдайды; нақты байқау біреуін таңдай алады.'},
        {'key': 'original', 'per_work': True,
         'label': 'Шығарма бұрын басқа платформада жарияланбаған',
         'hint': 'Тек өз мәтінің, бұрын жарияланбаған.'},
        {'key': 'ai_decl', 'per_work': True,
         'label': 'AI-көмек туралы жауап',
         'hint': 'AI-көмек қолданылды ма? — өтінім бергенде анық белгілеу қажет.'},
        {'key': 'one_entry', 'per_work': False,
         'label': 'Бір автор — бір өтінім',
         'hint': 'Берілген өтінімді қайтарып алып, басқасын жіберуге болады.'},
    ]


def _total_chars(story) -> int:
    """Объём по главам: на конкурс идёт текст, который прочтёт жюри, а не
    обещание его дописать. Число приезжает аннотацией выдачи — без неё
    страница подачи шла бы за главами на каждого кандидата."""
    annotated = getattr(story, 'effective_chars', None)
    if annotated is not None:
        return annotated
    return sum(c.char_count for c in story.chapter_set.all())


def submission_checklist(story, contest, *, chars: int = None) -> list:
    """Соответствие работы требованиям конкурса (BR-22).

    Общая часть — из `common_rules`; возрастной пункт добавляется, только
    когда конкурс ставит вилку (BR-48). «Объём» — единственная авто-проверка,
    и `chars` передаётся готовым: страница уже посчитала его для каждого
    кандидата.
    """
    total = _total_chars(story) if chars is None else chars
    have = spaced_number(total)
    lo, hi = spaced_number(contest.min_chars), spaced_number(contest.max_chars)
    if total < contest.min_chars:
        vol_passed, vol_hint = False, f'Көлемі тым аз — {have} таңба (мин. {lo})'
    elif total > contest.max_chars:
        vol_passed, vol_hint = False, f'Көлемі тым үлкен — {have} таңба (макс. {hi})'
    else:
        vol_passed, vol_hint = True, f'{have} таңба — нормада'

    state = {
        'volume':  {'passed': vol_passed, 'hint': vol_hint, 'auto': True},
        'ai_decl': {'passed': False, 'auto': False, 'required': True},
    }
    items = [
        {**rule, **state.get(rule['key'], {'passed': True, 'auto': False})}
        for rule in common_rules(contest) if rule['per_work']
    ]
    eligibility = eligibility_line(contest.min_age, contest.max_age)
    if eligibility:
        items.append({'key': 'eligibility', 'per_work': False,
                      'label': f'Қатысушы: {eligibility}',
                      'hint': 'Өтінім бергенде растайсың.',
                      'passed': True, 'auto': False})
    return items


def submission_candidates(user, contest_slug) -> list:
    """Работы автора как кандидаты и что о них стоит знать (BR-24).

    Заметки, а не запреты: короткий текст бывает намеренно короткой формой,
    а работа в другом конкурсе — предметом разговора. Только публичные:
    черновик нельзя ни дать жюри, ни показать рядом с победителями (BR-10).
    Готовый конкурс наравне со слагом — страница держит его на руках.
    """
    contest = (contest_slug if not isinstance(contest_slug, str)
               else contest_by_slug(contest_slug))
    if not contest or user is None:
        return []
    result = []
    for story in user.public_works:
        total = _total_chars(story)
        notes = []
        if total < contest.min_chars:
            notes.append({'key': 'too_short',
                          'text': f"{SUBMISSION_NOTES['too_short']} — "
                                  f"мин. {spaced_number(contest.min_chars)}"})
        elif total > contest.max_chars:
            notes.append({'key': 'too_long',
                          'text': f"{SUBMISSION_NOTES['too_long']} — "
                                  f"макс. {spaced_number(contest.max_chars)}"})
        busy = busy_contest_of(user, story.slug, besides=contest.slug)
        if busy:
            notes.append({'key': 'busy',
                          'text': f"{SUBMISSION_NOTES['busy']}: «{busy.name}»"})
        result.append({'story': story, 'chars': total, 'notes': notes})
    return result


def create_submission(user, contest, story, *, ai_declaration: str,
                      age_confirmed: bool, rules_confirmed: bool):
    """Новая заявка (BR-23). Возвращает `(submission, created)`.

    `get_or_create` по (contest, author), а не голый `create`: «один автор —
    одна работа» это `UniqueConstraint`, и гонка двух кликов подряд падала
    бы 500 вместо тихого «уже подано».
    """
    return Submission.objects.get_or_create(
        contest=contest, author=user,
        defaults={
            'story':           story,
            'submitted_on':    timezone.localdate(),
            'ai_declaration':  ai_declaration,
            'age_confirmed':   age_confirmed,
            'rules_confirmed': rules_confirmed,
        },
    )


def withdraw_submission(user, contest) -> bool:
    """Отзыв заявки (BR-23b). Условие проверяется здесь заново:
    `can_withdraw` решает, показать ли кнопку, а не охраняет сам POST."""
    if not can_withdraw(user, contest):
        return False
    deleted, _ = Submission.objects.filter(
        author=user, contest=contest, status='reviewing').delete()
    return bool(deleted)


def contest_history(user, *, is_self: bool = False) -> list:
    """Конкурсная биография автора (FR-PROF-07), свежие сверху.

    Правило приватности живёт здесь, а не в шаблоне (BR-74a): публично
    видно участие без статуса — «қаралуда» и «қабылданбады» неотличимы, и
    отказ нельзя ни увидеть, ни вычислить сравнением с числом заявок.
    Комментарий жюри не покидает кабинет; работа названа, пока публична.
    """
    if user is None:
        return []
    subs = user.own_submissions
    # Присуждения — одним запросом на все конкурсы: цикл ниже ищет среди них
    # работу заявки, и без prefetch каждая строка биографии стоила бы двух
    # запросов. Здесь, а не в `submissions_of`: больше их никто не читает.
    prefetch_related_objects(subs, 'contest__grant_set__award')

    out = []
    for sub in subs:
        contest, story = sub.contest, sub.story
        titles = [g.award.title for g in contest.grants
                  if g.story_id == story.pk and g.award]
        result = 'winner' if titles else sub.status
        if not is_self and result not in PUBLIC_CONTEST_RESULTS:
            result = ''
        label = ', '.join(titles) if result == 'winner' and titles \
            else CONTEST_RESULT_LABELS.get(result, '')
        out.append({
            'contest':      contest,
            'story':        story if (is_self or story.is_public) else None,
            'year':         contest.year,
            'result':       result,
            'result_label': label,
            'note':         sub.note if is_self else '',
        })
    return sorted(out, key=lambda i: (-i['year'], i['contest'].name))
