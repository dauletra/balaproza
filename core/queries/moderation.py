"""Очередь модератора и всё, что нужно для решения (FR-MOD-*, BR-82) — и
рядом её вторая, не связанная по устройству очередь: жалобы читателей на
уже опубликованное (BR-33).

Очередь ревизий — это **работы с поданными ревизиями**, а не работы в
статусе: статус с BR-79 выводится и у публичного сериала остаётся
публичным, пока его новая глава ждёт проверки. Спрашивать статус значило
бы прятать от модератора ровно то, что ему прислали. Порядок один и не
настраивается: дольше всех ждущий — первым. Это не предпочтение, а
обещание автору, что его очередь дойдёт.

Очередь жалоб не про ревизии вовсе — про то, что уже видно читателю; её
решение (`resolve_report`) не проходит через `Story.apply_moderation`,
у которой без поданной ревизии нет входа, а через `Story.take_down`.
"""

from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import BooleanField, Count, ExpressionWrapper, Min, Q
from django.utils import timezone

from ..domain.moderation import (
    QUEUE_SLOW_DAYS,
    REVIEW_PROMISE_HOURS,
    paragraph_diff,
)
from ..domain.reports import REPORT_REASONS
from ..domain.catalog import PUBLIC_STATUSES
from ..models import (
    BlockedTagPattern,
    Chapter,
    ChapterRevision,
    ModerationClaim,
    ModerationDecision,
    PortalDay,
    Report,
    Story,
    StoryComment,
    StoryView,
    User,
)
from ..counters import comment_published
from .notifications import notify_comment


def _queue_base():
    """Работы, у которых есть что решать, со сроком ожидания на строке."""
    return (Story.objects
            .filter(chapter__revisions__state='pending')
            .select_related('author', 'primary_genre', 'claim__moderator')
            .annotate(waiting_since=Min('chapter__revisions__submitted_at'),
                      pending_chapters=Count('chapter__revisions',
                                             distinct=True))
            .order_by('waiting_since', 'pk'))


def moderation_queue(*, kind: str = '', moderator=None) -> list:
    """Очередь по выбранной оси (FR-MOD-01).

    Оси не про сортировку, а про «что я сейчас беру»: `waiting` — то, что
    держим дольше нормы, `repeat` — уже возвращавшееся (его читают, сверяя
    со своим же замечанием), `first` — работы, у которых ещё нет ни одной
    опубликованной главы, то есть первая публикация автора.
    """
    rows = _queue_base()
    if kind == 'waiting':
        rows = rows.filter(waiting_since__lte=timezone.now()
                           - timedelta(days=QUEUE_SLOW_DAYS))
    elif kind == 'repeat':
        rows = rows.filter(moderation_decisions__isnull=False).distinct()
    elif kind == 'first':
        rows = rows.exclude(chapter__published_revision__isnull=False)
    elif kind == 'mine' and moderator is not None:
        rows = rows.filter(claim__moderator=moderator)

    # «Долго ждёт» — правило (`QUEUE_SLOW_DAYS`), а не вёрстка: шаблон,
    # считающий дни сам, стал бы вторым местом, где живёт норма срока.
    #
    # Аннотацией, а не проходом по списку: очередь отдаётся **выдачей**, и
    # страницу из неё нарезает пагинатор. Цикл в Python требовал бы
    # материализовать всю очередь — то есть ровно то, от чего пагинация и
    # спасает, и тяжелела бы она в тот день, когда с ней не справляются.
    threshold = timezone.now() - timedelta(days=QUEUE_SLOW_DAYS)
    return rows.annotate(waiting_slow=ExpressionWrapper(
        Q(waiting_since__lte=threshold), output_field=BooleanField()))


def queue_size(*, kind: str = '', moderator=None) -> int:
    """Сколько ждёт. Без оси — всего, с осью — в ней.

    Оба вопроса настоящие: «всего» показывает шапка раздела, «в этой оси»
    нужно пагинации, иначе вторая страница ведёт в пустоту.
    """
    return moderation_queue(kind=kind, moderator=moderator).count()


def overdue_count() -> int:
    """Сколько заявок пережило обещанный срок (D1).

    Платформа говорит автору «әдетте тәулік ішінде», и это обещание
    должно быть видно с той стороны, где его выполняют. Иначе о
    просрочке узнают из жалобы, то есть позже автора.
    """
    edge = timezone.now() - timedelta(hours=REVIEW_PROMISE_HOURS)
    return _queue_base().filter(
        chapter__revisions__state='pending',
        chapter__revisions__submitted_at__lt=edge).distinct().count()


# ── Задержанные комментарии (D2) ─────────────────────────────────────────
#
# Сплошной премодерации комментариев нет: их на порядок больше, чем глав,
# и ответ через сутки перестаёт быть разговором. Задерживается то, что
# попало в блок-лист, — остальное публикуется сразу и живёт по жалобам.
# Правила говорят об этом ровно так же, без обещания «проверяем всё».

def comment_is_blocked(text: str) -> bool:
    """Есть ли в тексте образец из блок-листа.

    Подстрокой и в нижнем регистре: «спам» обязан ловить и «спамить», и
    «СПАМ». Точное совпадение здесь бесполезно — комментарий это не одно
    слово.

    Фильтрация в Python, а не запросом на каждый образец: список
    небольшой (десятки строк), а `WHERE %s LIKE '%%' || pattern || '%%'`
    по нему всё равно был бы полным проходом.
    """
    lowered = (text or '').lower()
    if not lowered:
        return False
    patterns = BlockedTagPattern.objects.filter(
        scope__in=('comment', 'both')).values_list('pattern', flat=True)
    return any(p in lowered for p in patterns)


def held_comments():
    """Задержанные комментарии, дольше ждущий первым — тот же принцип
    очереди, что у ревизий и жалоб. Выдачей, а не списком: страницу
    нарезает пагинатор."""
    return (StoryComment.objects.filter(held=True)
            .select_related('author', 'story')
            .order_by('created_at'))


def held_comments_count() -> int:
    """Число для бейджа в шапке очереди. `COUNT`, а не `len()` по списку:
    бейджу нужна цифра, а список притащил бы тексты всех задержанных
    комментариев на страницу, где их не показывают."""
    return StoryComment.objects.filter(held=True).count()


def held_comment_by_id(pk):
    return StoryComment.objects.filter(pk=pk, held=True).select_related(
        'story').first()


def publish_held_comment(comment) -> None:
    """Пропустить задержанный комментарий к читателю.

    Уведомление автору работы уходит **здесь**, а не при создании: до
    решения комментария для читателя не существует, и сообщать было не о
    чем. По той же причине здесь же прибавляется `Story.comments`:
    счётчик считает видимое, и до этой минуты комментария в нём не было.
    Сигналом это не ловится — флаг снимается `update()`, а он `post_save`
    не шлёт.
    """
    StoryComment.objects.filter(pk=comment.pk).update(held=False)
    comment.held = False
    comment_published(comment)
    notify_comment(comment)


def story_for_moderation(slug: str):
    """Работа для карточки решения — любого статуса, с автором и жанром."""
    return (Story.objects.filter(slug=slug)
            .select_related('author', 'primary_genre', 'secondary_genre',
                            'claim__moderator')
            .first())


def submitted_chapters(story) -> list:
    """Поданные главы с текстом и сравнением (FR-MOD-02/03).

    На каждой — сама ревизия, опубликованная до неё и разбор различий.
    Повторная подача без сравнения означала бы перечитывать работу
    целиком после каждой правки; первая публикация сравнения не имеет —
    сравнивать не с чем, и `diff` у неё пуст.
    """
    rows = (Chapter.objects
            .filter(story=story, revisions__state='pending')
            .select_related('published_revision')
            .prefetch_related('revisions')
            .order_by('number').distinct())

    out = []
    for chapter in rows:
        pending = chapter.pending_revision
        if pending is None:
            continue
        published = chapter.published_revision
        out.append({
            'chapter':   chapter,
            'revision':  pending,
            'published': published,
            'diff': (paragraph_diff(published.body, pending.body)
                     if published is not None else []),
        })
    return out


def decision_history(story) -> list:
    """Прошлые решения по работе — и модератору, и автору (FR-MOD-05).

    Без них повторная подача читается вслепую: неизвестно, что уже
    просили исправить, и один и тот же текст возвращается по второму
    кругу с другой формулировкой.
    """
    if story is None:
        return []
    return list(story.moderation_decisions.select_related('moderator'))


def claim_story(story, moderator):
    """«Взял в работу»: метка на себя, чужую не перебиваем (BR-82)."""
    claim, _ = ModerationClaim.objects.get_or_create(
        story=story, defaults={'moderator': moderator})
    return claim


def release_story(story, moderator) -> int:
    """Снять свою метку. Чужую снять нельзя: это её и обесценило бы."""
    return ModerationClaim.objects.filter(
        story=story, moderator=moderator).delete()[0]


# ───────────────────── Жалобы (BR-33, FR-STORY-09) ─────────────────────────

def create_report(reporter, *, story=None, comment=None, reason: str,
                  note: str = ''):
    """Жалоба или `None`, если её не завести.

    Сервер не верит клиенту: форма не предлагает жалобу на своё (кнопка
    скрыта в шаблоне), но проверка здесь — не косметика, а вторая линия,
    как и у остальных действий по слагу (BR-76). Ровно одна цель, причина
    из закрытого словаря, себе не жалуются.
    """
    if reason not in REPORT_REASONS:
        return None
    if bool(story) == bool(comment):
        return None
    owner_id = story.author_id if story else comment.author_id
    if owner_id == reporter.pk:
        return None
    # Вторая жалоба на то же, пока первая не рассмотрена, — no-op, а не
    # ошибка: человек нажал дважды или вернулся и не помнит. Ограничение
    # держит и база (`one_open_report_per_*`), здесь — чтобы вместо
    # пятисотки был тихий отказ, как у остальных проверок рядом.
    if Report.objects.filter(reporter=reporter, story=story, comment=comment,
                             resolved_at__isnull=True).exists():
        return None
    return Report.objects.create(
        reporter=reporter, story=story, comment=comment,
        reason=reason, note=note.strip()[:500])


def open_reports():
    """Открытые жалобы, дольше висящая первой — тот же принцип очереди,
    что у ревизий: обещание, что до неё дойдут.

    Выдачей, а не списком: страницу нарезает пагинатор, и до базы
    доезжает ровно она.
    """
    return (Report.objects
            .filter(resolved_at__isnull=True)
            .select_related('reporter', 'story__author',
                            'comment__story', 'comment__author')
            .order_by('created_at'))


def open_reports_count() -> int:
    return Report.objects.filter(resolved_at__isnull=True).count()


def report_by_id(pk):
    return (Report.objects
            .select_related('reporter', 'story__author',
                            'comment__story', 'comment__author')
            .filter(pk=pk).first())


def resolve_report(report, moderator, *, action: str, reason: str = '') -> None:
    """Решение по жалобе: «бұзушылық жоқ» или снятие контента.

    Снятие — не второй `apply_moderation`: у истории решается не поданная
    ревизия, а уже опубликованное (`Story.take_down`, BR-33); у комментария
    ревизий не бывает вовсе, и «снять» значит удалить — тем же действием,
    каким уже работает собственное «Жою» автора комментария.
    """
    if action not in ('dismiss', 'uphold'):
        raise ValueError(f'Белгісіз әрекет: {action!r}')
    with transaction.atomic():
        if action == 'uphold':
            if report.story_id:
                report.story.take_down(reason)
            elif report.comment_id:
                report.comment.delete()
                # `.delete()` не обнуляет ссылку в уже загруженном `report` —
                # Django 6 отказывается сохранять запись с «неживым» связанным
                # объектом в кэше, даже если поле не в `update_fields`.
                report.comment = None
        report.outcome = 'upheld' if action == 'uphold' else 'dismissed'
        report.resolved_at = timezone.now()
        report.resolved_by = moderator
        report.save(update_fields=['outcome', 'resolved_at', 'resolved_by'])


# ── Сводка портала (D6) ──────────────────────────────────────────────────
#
# Без неё первые месяцы — угадывание: нельзя ответить, доходит ли человек
# до конца анкеты, доходит ли черновик до публикации, возвращается ли
# читатель. Считается **своей базой**, без стороннего счётчика: на детской
# площадке чужой скрипт это абзац в политике конфиденциальности и данные,
# ушедшие наружу, а все нужные числа и так лежат в своих таблицах.
#
# Здесь же, в разделе модерации, а не отдельной админкой: смотрит их тот
# же человек, что и очередь, и сводка без очереди рядом отвечает на
# «сколько», не отвечая на «что с этим делать».

def portal_summary() -> dict:
    """Пять вопросов, на которые до этого ответа не было.

    Все пять — про **воронку**, а не про трафик: сколько людей дошло,
    сколько текстов дошло, сколько ждёт и как долго. Трафик считает
    веб-сервер, и он же единственный, кто его видит честно.
    """
    now = timezone.now()
    week = now - timedelta(days=7)

    signed_up = User.objects.count()
    onboarded = User.objects.filter(terms_accepted_at__isnull=False).count()
    wrote = User.objects.filter(stories__isnull=False).distinct().count()
    published = (User.objects
                 .filter(stories__status__in=PUBLIC_STATUSES)
                 .distinct().count())

    drafts = Story.objects.filter(status='NotPublished').count()
    public = Story.objects.filter(status__in=PUBLIC_STATUSES).count()

    decided_week = ModerationDecision.objects.filter(decided_at__gte=week)
    returned = decided_week.exclude(outcome='approved').count()

    oldest = (ChapterRevision.objects.filter(state='pending')
              .order_by('submitted_at').values_list('submitted_at', flat=True)
              .first())

    readers = reader_day(timezone.localdate() - timedelta(days=1))

    return {
        # Воронка автора: пришёл → дозаполнил → начал писать → опубликовал.
        # Разрыв между первыми двумя — цена анкеты; между вторым и
        # третьим — цена пустого экрана «начни писать».
        'signed_up': signed_up,
        'onboarded': onboarded,
        'wrote': wrote,
        'published': published,
        # Воронка текста.
        'drafts': drafts,
        'public': public,
        # Работа модерации за неделю и её качество: доля возвратов
        # говорит не о строгости, а о том, понятны ли авторам правила.
        'decided_week': decided_week.count(),
        'returned_week': returned,
        # Самое старое ожидание — то, по чему видно нарушенное обещание.
        'oldest_wait': oldest,
        'overdue': overdue_count(),
        # Читатель — за **вчера**, а не за сегодня: сегодняшние сутки
        # неполны всегда, и число из них читалось бы как падение.
        **readers,
        # Доля считается здесь, а не хранится строкой дня: у строки для
        # неё есть `PortalDay.returning_share`, и второй экземпляр того
        # же деления разошёлся бы с первым.
        'returning_share': (
            round(100 * readers['returning_readers'] / readers['readers'])
            if readers['readers'] else 0),
    }


# ── Читатель за сутки и снимок дня ───────────────────────────────────────
#
# Сводка выше отвечает «сколько сейчас». Чего она не умеет и не может
# уметь — сказать, растёт это или падает: в базе лежат только текущие
# числа, а вчерашние не восстанавливаются ничем (см. `PortalDay`).
#
# Возвращаемость читателя при этом уже лежит в базе и просто не
# спрашивалась: журнал `StoryView` несёт читателя и момент. Живёт он две
# недели — значит снять это число можно только вовремя, и в этом вся
# причина суточной команды.


def _day_bounds(day):
    """Границы календарных суток в часовом поясе портала.

    Явными моментами, а не `created_at__date`: тот перекладывает
    преобразование зоны на базу, то есть требует от неё свежей базы
    часовых поясов, и молча съезжает на час там, где её нет.
    """
    start = timezone.make_aware(datetime.combine(day, time.min))
    return start, start + timedelta(days=1)


def _reader_ids(day) -> set:
    """Кто читал в этот день. Только вошедшие: у гостя личности нет, и
    заводить её ради счётчика значило бы следить за ребёнком там, где
    политика обещает обратное."""
    start, end = _day_bounds(day)
    return set(StoryView.objects
               .filter(created_at__gte=start, created_at__lt=end,
                       viewer__isnull=False)
               .values_list('viewer_id', flat=True))


def reader_day(day) -> dict:
    """Сколько вошедших читало в этот день и сколько из них читало
    накануне.

    Два множества, а не запрос с подзапросом: журнал держит только окно в
    две недели, а читателей за сутки на детской площадке столько, что
    пересечение в Python дешевле второго прохода по индексу. Когда суток
    перестанет хватать — это место и станет первым, что перепишут.
    """
    today = _reader_ids(day)
    if not today:
        return {'readers': 0, 'returning_readers': 0}
    yesterday = _reader_ids(day - timedelta(days=1))
    return {'readers': len(today),
            'returning_readers': len(today & yesterday)}


def record_portal_day(day=None) -> PortalDay:
    """Заморозить сводку за сутки. По умолчанию — за вчера.

    Вчера, а не сегодня: сутки должны быть полными, иначе строка врёт про
    читателя тем сильнее, чем раньше отработал cron.

    Идемпотентна: повторный запуск за тот же день переписывает строку, а
    не заводит вторую. Пропуск дня наверстывается `--day`, но не глубже
    окна журнала — дальше читателя уже не посчитать.
    """
    day = day or timezone.localdate() - timedelta(days=1)
    numbers = portal_summary()
    row, _ = PortalDay.objects.update_or_create(
        day=day,
        defaults={
            **{k: numbers[k] for k in (
                'signed_up', 'onboarded', 'wrote', 'published',
                'drafts', 'public', 'decided_week', 'returned_week',
                'overdue')},
            **reader_day(day),
        },
    )
    return row


def portal_day_ago(days: int = 7):
    """Строка за столько-то дней назад или `None`, если её нет.

    `None` — нормальный ответ первую неделю работы команды, и страница
    обязана его выдержать: колонка «апта бұрын» просто не рисуется.
    Ближайшей строки вместо отсутствующей не подставляем — «неделю
    назад» должно значить неделю назад.
    """
    return PortalDay.objects.filter(
        day=timezone.localdate() - timedelta(days=days)).first()
