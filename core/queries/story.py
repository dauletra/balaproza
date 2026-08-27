"""Страница произведения: главы, отклик, комментарии, подборки.

Здесь два правила, которые легко потерять при переезде на модели.

**Ряд реакций всегда полный** (BR-REACT-01). Нулевые не выбрасываются:
пять кнопок обязаны выглядеть одинаково у первой главы и у сотой, иначе
читатель каждый раз ищет нужную заново.

**Общие комментарии видны под каждой главой.** У отзыва на всё
произведение «правильной» главы нет, и прятать его до конца книги значит
прятать навсегда.
"""

from django.db import transaction
from django.db.models import F

from ..domain.story import REACTIONS
from ..models import (
    BookOfWeek,
    Chapter,
    ChapterReaction,
    ChapterReactionVote,
    Collection,
    CommentLike,
    PollOption,
    PollVote,
    Story,
    StoryComment,
)
from .catalog import chapter_count_subquery


def chapters_of(story_slug: str) -> list:
    return list(Chapter.objects.filter(story__slug=story_slug)
                .prefetch_related('reactions'))


def _attach_my_reaction(chapter, viewer: str):
    """Аннотирует `chapter._my_reaction` голосом текущего читателя
    (BR-REACT-02/03). Гость (`viewer=''`) не голосует — запроса нет."""
    if chapter is not None and viewer:
        vote = ChapterReactionVote.objects.filter(
            chapter=chapter, user__username=viewer).first()
        chapter._my_reaction = vote.kind if vote else ''
    return chapter


def chapter_of(story_slug: str, number: int, viewer: str = ''):
    chapter = (Chapter.objects.filter(story__slug=story_slug, number=number)
              .prefetch_related('reactions').first())
    return _attach_my_reaction(chapter, viewer)


def reactions_of(chapter, viewer: str = '') -> list:
    """Полный ряд из пяти реакций в каноническом порядке.

    `mine` — что нажал текущий читатель (BR-REACT-02/03). Если `chapter`
    уже пришёл аннотированным из `chapter_of(..., viewer)`, второй запрос
    не нужен — читаем `Chapter.my_reaction`; иначе спрашиваем сами.
    """
    if chapter is None:
        return [{'reaction': r, 'count': 0, 'mine': False} for r in REACTIONS]
    counts = chapter.reaction_counts
    if not hasattr(chapter, '_my_reaction'):
        _attach_my_reaction(chapter, viewer)
    mine = chapter.my_reaction
    return [
        {'reaction': r, 'count': counts.get(r.slug, 0), 'mine': mine == r.slug}
        for r in REACTIONS
    ]


def _bump_reaction_count(chapter, kind: str, delta: int) -> None:
    """+1/-1 к счётчику одной реакции главы — заводит строку, если её ещё
    не было (ряд реакций полный, но не каждая кнопка нажата хоть раз)."""
    row, created = ChapterReaction.objects.get_or_create(
        chapter=chapter, kind=kind, defaults={'count': max(delta, 0)})
    if not created:
        ChapterReaction.objects.filter(pk=row.pk).update(count=F('count') + delta)


def toggle_chapter_reaction(chapter, user, kind: str) -> str:
    """Ставит, снимает или меняет реакцию на главе (BR-REACT-02/03).

    Одна активная реакция на пользователя и главу (`ChapterReactionVote`,
    unique по user+chapter): повтор того же `kind` снимает её, другой —
    заменяет. `Story.likes` — агрегат по числу голосов, а не по сумме
    реакций (BR-14a): смена вида реакции его не трогает, только появление
    и снятие голоса. Возвращает новый slug реакции, '' — если снята.
    """
    with transaction.atomic():
        vote = (ChapterReactionVote.objects.select_for_update()
                .filter(chapter=chapter, user=user).first())
        if vote is None:
            ChapterReactionVote.objects.create(chapter=chapter, user=user, kind=kind)
            _bump_reaction_count(chapter, kind, 1)
            Story.objects.filter(pk=chapter.story_id).update(likes=F('likes') + 1)
            return kind
        if vote.kind == kind:
            vote.delete()
            _bump_reaction_count(chapter, kind, -1)
            Story.objects.filter(pk=chapter.story_id).update(likes=F('likes') - 1)
            return ''
        old_kind = vote.kind
        vote.kind = kind
        vote.save(update_fields=['kind'])
        _bump_reaction_count(chapter, old_kind, -1)
        _bump_reaction_count(chapter, kind, 1)
        return kind


def _attach_my_vote(poll, viewer: str):
    """Аннотирует `poll._my_vote` голосом текущего читателя (docs/20 §20.2:
    одна ставка на опрос, не меняется). Гость (`viewer=''`) не голосует."""
    if poll is not None and viewer:
        vote = PollVote.objects.filter(poll=poll, user__username=viewer).first()
        poll._my_vote = vote.option.slug if vote else ''
    return poll


def poll_of(story_slug: str, chapter_number: int, viewer: str = ''):
    """Опрос главы или None: опрос необязателен (BR-POLL-01)."""
    chapter = (Chapter.objects
               .filter(story__slug=story_slug, number=chapter_number)
               .select_related('poll').first())
    poll = getattr(chapter, 'poll', None) if chapter else None
    return _attach_my_vote(poll, viewer)


def cast_poll_vote(poll, user, option_slug: str) -> bool:
    """Ставит голос — один на опрос, не на вариант, не меняется (docs/20
    §20.2). Закрытый опрос (BR-POLL-05) и повторный голос — no-op.
    Возвращает True, если голос принят."""
    if poll.closed:
        return False
    option = poll.option_set.filter(slug=option_slug).first()
    if option is None:
        return False
    with transaction.atomic():
        vote, created = PollVote.objects.get_or_create(
            user=user, poll=poll, defaults={'option': option})
        if created:
            PollOption.objects.filter(pk=option.pk).update(votes=F('votes') + 1)
        return created


def _comments(story_slug: str):
    return (StoryComment.objects
            .filter(story__slug=story_slug, parent__isnull=True)
            .select_related('author', 'story', 'story__author')
            .prefetch_related('reply_set__author'))


def _attach_liked(comments: list, viewer: str) -> list:
    """Проставляет `.liked` на каждый комментарий и его ответы (BR-31).

    `replies` — `cached_property` (Ф15 Этап 2) именно ради этого: второй
    вызов в шаблоне обязан вернуть ТЕ ЖЕ объекты, на которых уже стоит
    метка, а не заново уйти в базу и потерять её.
    """
    pairs = [(c, c.replies) for c in comments]
    liked_ids = set()
    if viewer:
        ids = {c.pk for c, _ in pairs} | {r.pk for _, reps in pairs for r in reps}
        liked_ids = set(CommentLike.objects.filter(
            user__username=viewer, comment_id__in=ids).values_list('comment_id', flat=True))
    for c, reps in pairs:
        c.liked = c.pk in liked_ids
        for r in reps:
            r.liked = r.pk in liked_ids
    return comments


def comments_of(story_slug: str, viewer: str = '') -> list:
    """Все верхнеуровневые комментарии произведения; ответы висят на них."""
    return _attach_liked(list(_comments(story_slug)), viewer)


def comments_of_chapter(story_slug: str, chapter_number: int, viewer: str = '') -> list:
    """Комментарии главы плюс общие — те, у которых главы нет вовсе."""
    from django.db.models import Q

    comments = list(_comments(story_slug).filter(
        Q(chapter_number__isnull=True) | Q(chapter_number=chapter_number)))
    return _attach_liked(comments, viewer)


def comment_of(story_slug: str, comment_id) -> StoryComment | None:
    """Любой комментарий этой работы (лайк ставят и не на свой) — или None."""
    try:
        comment_id = int(comment_id)
    except (TypeError, ValueError):
        return None
    return (StoryComment.objects.filter(pk=comment_id, story__slug=story_slug)
            .select_related('author', 'story').first())


def top_level_comment_of(story_slug: str, comment_id) -> StoryComment | None:
    """Комментарий этой работы, но только верхнего уровня (BR-30) — на
    ответ отвечать нельзя, `add_comment` полагается на эту проверку."""
    try:
        comment_id = int(comment_id)
    except (TypeError, ValueError):
        return None
    return StoryComment.objects.filter(
        pk=comment_id, story__slug=story_slug, parent__isnull=True).first()


def add_comment(story, author, *, text: str, chapter_number=None, parent=None) -> StoryComment:
    """Новый комментарий или ответ (BR-30/BR-33). Валидность `parent`
    (свой ли уровень, та ли работа) проверяет вызывающая сторона —
    `top_level_comment_of` уже это гарантирует к моменту вызова."""
    comment = StoryComment.objects.create(
        story=story, author=author, chapter_number=chapter_number,
        parent=parent, text=text)
    Story.objects.filter(pk=story.pk).update(comments=F('comments') + 1)
    return comment


def delete_comment(comment) -> None:
    """Удаляет комментарий вместе с его ответами (каскад, BR-30 — уровень
    один, ответам своих ответов нет) и синхронизирует `Story.comments`."""
    removed = 1 + len(comment.replies)
    story_id = comment.story_id
    comment.delete()
    Story.objects.filter(pk=story_id).update(comments=F('comments') - removed)


def toggle_comment_like(comment, user) -> bool:
    """Лайк комментария — toggle (BR-31): повторный клик снимает.
    Возвращает новое состояние (True — лайкнул)."""
    like, created = CommentLike.objects.get_or_create(user=user, comment=comment)
    if not created:
        like.delete()
    count = comment.like_set.count()
    StoryComment.objects.filter(pk=comment.pk).update(likes=count)
    comment.likes = count
    return created


def collections_of(story) -> list:
    """Подборки, в которых лежит работа — обратный вход со страницы.

    Порядок редакционный, а не по релевантности: жинақ и есть редакционное
    высказывание.
    """
    return list(Collection.objects.filter(item_set__story=story).distinct())


def all_collections() -> list:
    return list(Collection.objects.prefetch_related(
        'item_set__story__author', 'item_set__story__primary_genre'))


def collection_by_slug(slug: str):
    return Collection.objects.filter(slug=slug).first()


def book_of_week():
    """Выбор редакции на эту неделю (FR-HOME-03) или None.

    Берётся последняя запись, а не флаг у произведения: неделя проходит, и
    выбор становится историей, а флаг пришлось бы снимать руками.

    Число частей едет той же строкой (тот же приём, что в `library_of`):
    блок главной показывает «N бөлім», и без подсказки `Story.chapters`
    спрашивал бы базу — причём дважды, потому что блок рисуется и в
    первом фолде, и в ряду ниже.
    """
    pick = (BookOfWeek.objects.select_related('story', 'story__author',
                                              'story__primary_genre')
            .annotate(story_chapters=chapter_count_subquery('story'))
            .order_by('-published_on').first())
    if pick is not None:
        pick.story.chapter_count = pick.story_chapters
    return pick
