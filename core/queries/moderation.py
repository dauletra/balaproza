"""Очередь модератора и всё, что нужно для решения (FR-MOD-*, BR-82).

Очередь — это **работы с поданными ревизиями**, а не работы в статусе:
статус с BR-79 выводится и у публичного сериала остаётся публичным, пока
его новая глава ждёт проверки. Спрашивать статус значило бы прятать от
модератора ровно то, что ему прислали.

Порядок один и не настраивается: дольше всех ждущий — первым. Это не
предпочтение, а обещание автору, что его очередь дойдёт.
"""

from datetime import timedelta

from django.db.models import Count, Min
from django.utils import timezone

from ..domain.moderation import QUEUE_SLOW_DAYS, paragraph_diff
from ..models import Chapter, ChapterRevision, ModerationClaim, Story


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
