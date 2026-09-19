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

from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Min
from django.utils import timezone

from ..domain.moderation import QUEUE_SLOW_DAYS, paragraph_diff
from ..domain.reports import REPORT_REASONS
from ..models import (
    Chapter,
    ChapterRevision,
    ModerationClaim,
    Report,
    Story,
)


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
    stories = list(rows)
    threshold = timezone.now() - timedelta(days=QUEUE_SLOW_DAYS)
    for story in stories:
        story.waiting_slow = (story.waiting_since is not None
                              and story.waiting_since <= threshold)
    return stories


def queue_size() -> int:
    """Сколько всего ждёт — число для шапки; ось на него не влияет."""
    return _queue_base().count()


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


def pending_revision_count(story) -> int:
    return ChapterRevision.objects.filter(
        chapter__story=story, state='pending').count()


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


def open_reports() -> list:
    """Открытые жалобы, дольше висящая первой — тот же принцип очереди,
    что у ревизий: обещание, что до неё дойдут."""
    return list(Report.objects
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
