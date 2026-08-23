"""Конкурсы: списки, правила, подача, конкурсная биография.

Два правила этого раздела легко потерять и трудно заметить.

**«Можно подать» и «конкурс не завершён» — разные вопросы** (DEC-45).
Кнопку «Қатысу» и доступ к форме решает `is_accepting`, знак работы
«Байқауға қатысады» — `not is_finished`. Смешанные в одном слове
«активен», они однажды и разошлись.

**Форма ничего не отклоняет** (BR-24). У кандидатов бывают заметки — про
объём, про занятость другим конкурсом, — но решение принимает человек.
Прежняя версия гасила радио и кнопку, то есть отказывала от имени
конкурса до всякого жюри.
"""

from django.utils import timezone

from ..domain.contests import (
    CONTEST_RESULT_LABELS,
    PUBLIC_CONTEST_RESULTS,
    SUBMISSION_NOTES,
)
from ..domain.formatting import spaced_number
from ..models import Contest, Submission
from .author import public_stories_of

# Порядок открытых конкурсов — по тому, что читатель может сделать:
# сначала куда можно подать прямо сейчас, потом что откроется, потом что
# уже судят. Алфавит и порядок заведения такой вопрос не решают.
_OPEN_ORDER = ('accepting', 'upcoming', 'judging')


def _base():
    return Contest.objects.prefetch_related(
        'award_set', 'stage_set', 'jury_set', 'condition_set',
        'grant_set__award', 'grant_set__story__author')


def all_contests() -> list:
    return list(_base())


def contest_by_slug(slug: str):
    return _base().filter(slug=slug).first()


# Фазы, выраженные для базы. Тот же календарь, что у `Contest.phase`, и
# расходиться им нельзя: свойство отвечает на странице, эти условия — в
# выдаче, и разное «идёт ли приём» в двух местах читатель увидит сразу.
def _accepting_q():
    today = timezone.localdate()
    return {'opens_on__lte': today, 'closes_on__gte': today}


def open_contests() -> list:
    """Незавершённые — в порядке того, что с ними можно сделать."""
    return sorted(_base().filter(results_on__gt=timezone.localdate()),
                  key=lambda c: _OPEN_ORDER.index(c.phase))


def accepting_contests() -> list:
    return list(_base().filter(**_accepting_q()))


def finished_contests() -> list:
    return list(_base().filter(results_on__lte=timezone.localdate()))


def hero_contest():
    """Конкурс для баннера главной — тот, чей приём закрывается раньше всех.

    Два решения в одном. Первое: именно `is_accepting`, а не «не
    завершён», — баннер зовёт участвовать, и вести на конкурс с закрытым
    приёмом значит не выполнить обещание страницы. Второе: из нескольких
    открытых выбирается ближайший по дедлайну, потому что это и есть
    ответ на «куда бежать». В стабе выбор решался порядком объявления в
    списке — то есть случайностью, которую нельзя перенести в базу.

    Состав конкурса баннеру не нужен, поэтому без `prefetch`: иначе
    главная платит четыре запроса за номинации и жюри, которых не
    показывает.
    """
    return (Contest.objects.filter(**_accepting_q())
            .order_by('closes_on', 'pk').first())


def submissions_of(username: str) -> list:
    if not username:
        return []
    return list(Submission.objects.filter(author__username=username)
                .select_related('contest', 'story', 'story__author'))


def has_submission(username: str, contest_slug: str) -> bool:
    """BR-23: один автор — одна работа на конкретный конкурс."""
    return bool(username) and Submission.objects.filter(
        author__username=username, contest__slug=contest_slug).exists()


def busy_contest_of(username: str, story_slug: str, *, besides: str = ''):
    """Незавершённый конкурс, который уже держит эту работу (BR-23a).

    Одна работа не идёт в двух конкурсах сразу: жюри читают параллельно, и
    одним текстом нельзя выиграть дважды. Завершённый не мешает — работа
    своё отучаствовала.
    """
    rows = (Submission.objects
            .filter(author__username=username, story__slug=story_slug,
                    contest__results_on__gt=timezone.localdate())
            .exclude(contest__slug=besides)
            .select_related('contest'))
    row = rows.first()
    return row.contest if row else None


def can_withdraw(username: str, contest_slug: str) -> bool:
    """Можно ли отозвать заявку (BR-23b).

    Пока идёт приём и жюри не вынесло решения. Без отзыва «одна работа на
    конкурс» означало бы: ошибся работой — и всё.
    """
    contest = contest_by_slug(contest_slug)
    if not contest or not contest.is_accepting:
        return False
    return Submission.objects.filter(author__username=username,
                                     contest=contest,
                                     status='reviewing').exists()


def common_rules(contest) -> list:
    """Правила, действующие на любом конкурсе (BR-48a). Один источник.

    Раньше каждый конкурс переписывал их в свои условия руками, и копия
    разошлась тремя способами сразу: AI-декларация обязательна для всех
    (DEC-21), а названа была у одного из пяти; пороги объёма стояли
    литералом, хотя у каждого конкурса свои; в тексте для подростка
    попадались коды ТЗ.

    `per_work` — проверяется ли правило у конкретной работы. «Бір автор —
    бір өтінім» относится к автору, а не к тексту, и в чек-лист подачи не
    идёт: его держит сама форма.

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
    """Объём по написанному тексту.

    Именно по главам, без оценки по заявленным частям: на конкурс идёт
    текст, который прочтёт жюри, а не обещание его дописать.
    """
    return sum(c.char_count for c in story.chapter_set.all())


def submission_checklist(story, contest) -> list:
    """Соответствие работы требованиям конкурса (BR-22).

    Общая часть приходит из `common_rules`: второй рукописной копии тех же
    правил в проекте быть не должно. Возрастной пункт добавляется только
    когда конкурс ставит вилку (BR-48) — вечно «пройденная» строка ничего
    не сообщает.

    «Объём» — единственная авто-проверка, остальное требует ответа автора.
    """
    total = _total_chars(story)
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
    if contest.eligibility_line:
        items.append({'key': 'eligibility', 'per_work': False,
                      'label': f'Қатысушы: {contest.eligibility_line}',
                      'hint': 'Өтінім бергенде растайсың.',
                      'passed': True, 'auto': False})
    return items


def submission_candidates(username: str, contest_slug: str) -> list:
    """Работы автора как кандидаты и что о них стоит знать (BR-24).

    **Заметки, а не запреты.** Короткий текст бывает намеренно короткой
    формой, а работа, поданная в другой конкурс, — предметом разговора, а
    не поводом молча закрыть дверь. Заметок бывает несколько сразу.

    В список идут только публичные работы: черновик на конкурс не
    выставляется — его нельзя ни дать жюри, ни показать рядом с
    победителями (BR-10, DEC-23).
    """
    contest = contest_by_slug(contest_slug)
    if not contest:
        return []
    result = []
    for story in public_stories_of(username):
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
        busy = busy_contest_of(username, story.slug, besides=contest_slug)
        if busy:
            notes.append({'key': 'busy',
                          'text': f"{SUBMISSION_NOTES['busy']}: «{busy.name}»"})
        result.append({'story': story, 'chars': total, 'notes': notes})
    return result


def contest_history(username: str, *, is_self: bool = False) -> list:
    """Конкурсная биография автора (FR-PROF-07), свежие сверху.

    Правило приватности живёт здесь, а не в шаблоне (BR-74a): публично
    видно **участие без статуса**. Наверх поднимаются только победа и
    принятие; «қаралуда» и «қабылданбады» публично неотличимы, и отказ
    поэтому нельзя ни увидеть, ни вычислить сравнением с числом заявок.

    Комментарий жюри не покидает личный кабинет никогда. Работа названа
    только пока публична (BR-73): подача не должна раскрывать снятое с
    публикации произведение.
    """
    out = []
    for sub in submissions_of(username):
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
