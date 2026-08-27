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

from django.db.models import Count, prefetch_related_objects
from django.utils import timezone

from ..domain.catalog import PUBLIC_STATUSES
from ..domain.contests import (
    CONTEST_RESULT_LABELS,
    PUBLIC_CONTEST_RESULTS,
    SUBMISSION_NOTES,
)
from ..domain.formatting import spaced_number
from ..models import Contest, Submission
from .author import author_facts

# Порядок открытых конкурсов — по тому, что читатель может сделать:
# сначала куда можно подать прямо сейчас, потом что откроется, потом что
# уже судят. Алфавит и порядок заведения такой вопрос не решают.
_OPEN_ORDER = ('accepting', 'upcoming', 'judging')


def _counted(qs):
    """Число заявок аннотацией — его подхватывает `Contest.submissions`.

    Без неё каждая карточка списка спрашивала своё `COUNT`: десять
    запросов на десять конкурсов, и растут они вместе с разделом.
    """
    return qs.annotate(submission_count=Count('submission_set'))


def _list_base():
    """Конкурс для списка карточек.

    Номинации, этапы, жюри и условия карточка не показывает — она
    называет фазу, приз и победителей. Тянуть состав списком значит
    платить четыре запроса за то, чего на экране нет; победители нужны,
    поэтому присуждения остаются.
    """
    return _counted(Contest.objects.prefetch_related('grant_set__story'))


def _base():
    """Конкурс со всем составом — для его собственной страницы."""
    return _counted(Contest.objects.prefetch_related(
        'award_set', 'stage_set', 'jury_set', 'condition_set',
        'grant_set__award', 'grant_set__story__author'))


def all_contests() -> list:
    return list(_list_base())


def contest_by_slug(slug: str):
    return _base().filter(slug=slug).first()


def contest_participants(contest) -> list:
    """Работы конкурса, доступные читателю (BR-74a): accepted + победители.

    Победа не отдельный статус заявки — она читается через `contest.grants`
    (тот же приём, что в `contest_history`), поэтому фильтр по
    status='accepted' уже покрывает весь `PUBLIC_CONTEST_RESULTS`.

    Принимает конкурс, полученный через `contest_by_slug` (`_base()`):
    иначе `contest.grants` тянет присуждения отдельным запросом на каждый
    вызов.
    """
    grants_by_story = {g.story_id: g for g in contest.grants}
    subs = (Submission.objects
            .filter(contest=contest, status='accepted',
                    story__status__in=PUBLIC_STATUSES)
            .select_related('story', 'story__author', 'story__primary_genre')
            .order_by('story__title'))
    out = []
    for sub in subs:
        grant = grants_by_story.get(sub.story_id)
        out.append({'story': sub.story,
                    'result': 'winner' if grant else 'accepted',
                    'label': grant.award.title if grant
                             else CONTEST_RESULT_LABELS['accepted']})
    return out


# Фазы, выраженные для базы. Тот же календарь, что у `Contest.phase`, и
# расходиться им нельзя: свойство отвечает на странице, эти условия — в
# выдаче, и разное «идёт ли приём» в двух местах читатель увидит сразу.
def _accepting_q():
    today = timezone.localdate()
    return {'opens_on__lte': today, 'closes_on__gte': today}


def open_contests() -> list:
    """Незавершённые — в порядке того, что с ними можно сделать."""
    return sorted(_list_base().filter(results_on__gt=timezone.localdate()),
                  key=lambda c: _OPEN_ORDER.index(c.phase))


def accepting_contests() -> list:
    return list(_list_base().filter(**_accepting_q()))


def finished_contests() -> list:
    return list(_list_base().filter(results_on__lte=timezone.localdate()))


def home_contests(limit: int = 4) -> list:
    """Конкурсы для секции «Байқаулар» на главной.

    Тот же порядок, что у `open_contests` (DEC-45: сначала куда можно
    подать/что уже судят), хвост добирают недавно завершённые — иначе
    секция пустеет в межсезонье, когда нет ни одного открытого конкурса.
    """
    return (open_contests() + finished_contests())[:limit]


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
    """Заявки автора.

    Присуждений здесь нет намеренно: они нужны одной `contest_history`, и
    она добирает их сама. Список заявок в кабинете спрашивает только «можно
    ли отозвать», и платить за чужой вопрос ему незачем.
    """
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


def can_withdraw(username: str, contest) -> bool:
    """Можно ли отозвать заявку (BR-23b).

    Пока идёт приём и жюри не вынесло решения. Без отзыва «одна работа на
    конкурс» означало бы: ошибся работой — и всё.

    Принимает и готовый конкурс, и слаг. Готовый — потому что список
    заявок спрашивает это по строке, а через слаг ответ стоил полной
    выборки конкурса **со всем составом**: номинации, этапы, жюри,
    условия и присуждения — шесть лишних запросов на каждую строку.
    Слаг остаётся ради вызовов, у которых объекта на руках нет.
    """
    if isinstance(contest, str):
        # Без `contest_by_slug`: здесь нужны три даты, а не состав.
        contest = Contest.objects.filter(slug=contest).first()
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
    текст, который прочтёт жюри, а не обещание его дописать. Поэтому
    берётся `written_chars`, а не `effective_chars`: второй дорисовывает
    ненаписанные части по заявленному числу глав.

    Число уже приезжает аннотацией выдачи (`_reading_effort`) — без неё
    страница подачи шла за главами на каждого кандидата, а список
    кандидатов это все публичные работы автора.
    """
    annotated = getattr(story, 'written_chars', None)
    if annotated is not None:
        return annotated
    return sum(c.char_count for c in story.chapter_set.all())


def submission_checklist(story, contest, *, chars: int = None) -> list:
    """Соответствие работы требованиям конкурса (BR-22).

    Общая часть приходит из `common_rules`: второй рукописной копии тех же
    правил в проекте быть не должно. Возрастной пункт добавляется только
    когда конкурс ставит вилку (BR-48) — вечно «пройденная» строка ничего
    не сообщает.

    «Объём» — единственная авто-проверка, остальное требует ответа автора.

    `chars` — уже посчитанный объём. Страница подачи считает его для
    каждого кандидата в `submission_candidates`, а потом просила чек-лист
    у каждого же — и объём шёл в базу за главами по второму разу.
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
    if contest.eligibility_line:
        items.append({'key': 'eligibility', 'per_work': False,
                      'label': f'Қатысушы: {contest.eligibility_line}',
                      'hint': 'Өтінім бергенде растайсың.',
                      'passed': True, 'auto': False})
    return items


def submission_candidates(username: str, contest_slug, *, facts=None) -> list:
    """Работы автора как кандидаты и что о них стоит знать (BR-24).

    **Заметки, а не запреты.** Короткий текст бывает намеренно короткой
    формой, а работа, поданная в другой конкурс, — предметом разговора, а
    не поводом молча закрыть дверь. Заметок бывает несколько сразу.

    В список идут только публичные работы: черновик на конкурс не
    выставляется — его нельзя ни дать жюри, ни показать рядом с
    победителями (BR-10, DEC-23).

    Принимает готовый конкурс наравне со слагом: страница подачи уже
    держит его на руках, и второй `contest_by_slug` тянул бы весь состав
    заново.
    """
    contest = (contest_slug if not isinstance(contest_slug, str)
               else contest_by_slug(contest_slug))
    if not contest:
        return []
    facts = facts or author_facts(username)
    result = []
    for story in facts.public_stories:
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
        busy = busy_contest_of(username, story.slug, besides=contest.slug)
        if busy:
            notes.append({'key': 'busy',
                          'text': f"{SUBMISSION_NOTES['busy']}: «{busy.name}»"})
        result.append({'story': story, 'chars': total, 'notes': notes})
    return result


def create_submission(user, contest, story, *, ai_declaration: str,
                      age_confirmed: bool, rules_confirmed: bool):
    """Новая заявка (BR-23, Ф15 Этап 5).

    `get_or_create` по (contest, author) вместо голого `create`: один
    автор — одна работа на конкретный конкурс — это ограничение базы
    (`UniqueConstraint`), и без `get_or_create` гонка двух кликов подряд
    падала бы 500 вместо тихого «уже подано». Возвращает `(submission,
    created)` — вызывающая сторона решает, что сказать автору.
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


def withdraw_submission(username: str, contest) -> bool:
    """Отзыв заявки (BR-23b, Ф15 Этап 5).

    Условие то же, что у `can_withdraw` — приём ещё идёт, жюри ещё не
    решило, — и проверяется здесь заново: `can_withdraw` решает, показать
    ли кнопку, а не охраняет сам POST.
    """
    if not can_withdraw(username, contest):
        return False
    deleted, _ = Submission.objects.filter(
        author__username=username, contest=contest, status='reviewing').delete()
    return bool(deleted)


def contest_history(username: str, *, is_self: bool = False,
                    facts=None) -> list:
    """Конкурсная биография автора (FR-PROF-07), свежие сверху.

    Правило приватности живёт здесь, а не в шаблоне (BR-74a): публично
    видно **участие без статуса**. Наверх поднимаются только победа и
    принятие; «қаралуда» и «қабылданбады» публично неотличимы, и отказ
    поэтому нельзя ни увидеть, ни вычислить сравнением с числом заявок.

    Комментарий жюри не покидает личный кабинет никогда. Работа названа
    только пока публична (BR-73): подача не должна раскрывать снятое с
    публикации произведение.
    """
    subs = (facts or author_facts(username)).submissions
    # Присуждения — одним запросом на все конкурсы сразу. Ниже цикл ищет
    # среди них работу этой заявки, и без prefetch каждая строка биографии
    # стоила запроса за присуждениями плюс запроса за номинацией на
    # каждое из них. Добирается здесь, а не в `submissions_of`: больше их
    # никто не читает.
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
