"""Счётчики-кэши над `Story`/`User`/`ChapterReaction`/`PollOption`: одна
точка, где событие в таблице-источнике сдвигает агрегат.

Сигналы `post_save`/`post_delete`, а не ручной `F()` внутри доменных функций
(`add_comment`, `toggle_chapter_reaction`, …) — потому что ручной вызов
работает только для того пути, который его вызвал. Массовое удаление в
админке и каскад от удаления пользователя идут в обход доменной функции и
раньше оставляли счётчик висеть на старом значении.

Django переводит `QuerySet.delete()` на поштучный проход и шлёт `post_delete`
на каждый объект, как только на модель подписан хоть один обработчик этого
сигнала (`Collector.can_fast_delete`) — это и держит счётчик синхронным при
массовом удалении из админки и при каскаде, без специального кода под
каждый случай отдельно.

Слепая зона одна и остаётся всегда: `bulk_create`/`bulk_update` сигналов не
шлют вовсе — задокументированное поведение Django. Настоящих вызовов такого
рода в проекте сейчас нет; страховка на этот случай — периодическая сверка
(`recount_engagement`), а не этот модуль.
"""

from django.db.models import Count, F, IntegerField, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import (
    Chapter,
    ChapterReaction,
    ChapterReactionVote,
    CommentLike,
    Follow,
    PollOption,
    PollVote,
    Story,
    StoryComment,
    StoryView,
    User,
)


def bump(model, pk, **deltas) -> None:
    """Атомарный сдвиг `F(field) + delta` одним UPDATE — без чтения перед
    записью, поэтому гонка двух одновременных событий не теряет одно из них.
    `pk=None` — событие без цели (например, реакция на уже удалённой главе)
    — тихий no-op."""
    if pk is None:
        return
    model.objects.filter(pk=pk).update(
        **{field: F(field) + delta for field, delta in deltas.items()})


def bump_reaction_count(chapter_id: int, kind: str, delta: int) -> None:
    """+delta счётчику одной реакции главы — заводит строку, если реакции
    такого вида на этой главе ещё не голосовали ни разу (ряд из пяти кнопок
    полон и без неё).

    Общая точка для сигнала «голос создан/удалён» и для смены вида реакции
    в `toggle_chapter_reaction`: там голос не создаётся и не удаляется, а
    меняется на месте (`vote.save(update_fields=['kind'])`), и сигналу не
    за что зацепиться — тот случай остаётся явным вызовом на стороне
    домена.

    `delta < 0` не заводит строку через `get_or_create`: при каскадном
    удалении главы (`Story` → `Chapter` → `CASCADE`) её `ChapterReaction`
    может исчезнуть раньше, чем Django дойдёт до `post_delete` голосов на
    той же главе — `get_or_create` в этот момент воскресил бы агрегат под
    уже потухающий `chapter_id`, и Postgres уронил бы отложенную проверку
    внешнего ключа в момент коммита (найдено удалением аккаунта с
    чужой реакцией на главе). Голому `filter().update()` нечего резать,
    если строки уже нет, — молчаливый no-op и есть правильный ответ.
    """
    if delta > 0:
        row, created = ChapterReaction.objects.get_or_create(
            chapter_id=chapter_id, kind=kind, defaults={'count': delta})
        if not created:
            ChapterReaction.objects.filter(pk=row.pk).update(count=F('count') + delta)
    else:
        ChapterReaction.objects.filter(chapter_id=chapter_id, kind=kind).update(
            count=F('count') + delta)


def _story_id_of_chapter(chapter_id: int):
    """`ChapterReactionVote` не хранит `story_id` напрямую — только через
    главу. Отдельным запросом, а не `instance.chapter.story_id`: так в базу
    едет один узкий `SELECT story_id`, а не вся строка главы."""
    return (Chapter.objects.filter(pk=chapter_id)
            .values_list('story_id', flat=True).first())


# ── StoryComment → Story.comments ───────────────────────────────────────
#
# Считается **видимое читателю**. Задержанный блок-листом комментарий
# (D2) не видит никто, включая автора работы, — а счётчик его прибавлял,
# потому что сигнал смотрел на создание строки и не смотрел на `held`.
# Карточка каталога обещала «5 пікір», на странице их было четыре.
#
# Отсюда три двери вместо одной: строка создана, строка удалена и —
# отдельно — задержанное пропущено модератором. Последнее сигналом не
# ловится: `publish_held_comment` снимает флаг через `update()`, а он
# `post_save` не шлёт. Это и к лучшему: снятие флага бывает ровно одно и
# живёт в одной функции.
@receiver(post_save, sender=StoryComment)
def _comment_created(sender, instance, created, **kwargs):
    if created and not instance.held:
        bump(Story, instance.story_id, comments=1)


@receiver(post_delete, sender=StoryComment)
def _comment_deleted(sender, instance, **kwargs):
    # Удалённый задержанный в счётчике и не был: вычесть его значило бы
    # увести число ниже правды.
    if not instance.held:
        bump(Story, instance.story_id, comments=-1)


# ── ChapterReactionVote → Story.likes и ChapterReaction.count ───────────
@receiver(post_save, sender=ChapterReactionVote)
def _reaction_vote_created(sender, instance, created, **kwargs):
    if not created:
        return
    bump(Story, _story_id_of_chapter(instance.chapter_id), likes=1)
    bump_reaction_count(instance.chapter_id, instance.kind, 1)


@receiver(post_delete, sender=ChapterReactionVote)
def _reaction_vote_deleted(sender, instance, **kwargs):
    bump(Story, _story_id_of_chapter(instance.chapter_id), likes=-1)
    bump_reaction_count(instance.chapter_id, instance.kind, -1)


# ── StoryView → Story.views/recent_views ────────────────────────────────
@receiver(post_save, sender=StoryView)
def _story_view_created(sender, instance, created, **kwargs):
    if created:
        bump(Story, instance.story_id, views=1, recent_views=1)


# ── Follow → User.followers ─────────────────────────────────────────────
@receiver(post_save, sender=Follow)
def _follow_created(sender, instance, created, **kwargs):
    if created:
        bump(User, instance.following_id, followers=1)


@receiver(post_delete, sender=Follow)
def _follow_deleted(sender, instance, **kwargs):
    bump(User, instance.following_id, followers=-1)


# ── CommentLike → StoryComment.likes ─────────────────────────────────────
def _recompute_comment_likes(comment_id) -> None:
    """Пересчёт, а не сдвиг — сознательно другой приём, чем у остальных
    счётчиков в этом файле: у демо-комментария декоративное «87 ұнату» без
    единой настоящей строки `CommentLike`, и первый живой лайк обязан
    ответить правдой (1), а не суммой с придуманной историей (88)."""
    if comment_id is None:
        return
    count = CommentLike.objects.filter(comment_id=comment_id).count()
    StoryComment.objects.filter(pk=comment_id).update(likes=count)


@receiver(post_save, sender=CommentLike)
def _comment_like_created(sender, instance, created, **kwargs):
    if created:
        _recompute_comment_likes(instance.comment_id)


@receiver(post_delete, sender=CommentLike)
def _comment_like_deleted(sender, instance, **kwargs):
    _recompute_comment_likes(instance.comment_id)


# ── PollVote → PollOption.votes ──────────────────────────────────────────
@receiver(post_save, sender=PollVote)
def _poll_vote_created(sender, instance, created, **kwargs):
    if created:
        bump(PollOption, instance.option_id, votes=1)


@receiver(post_delete, sender=PollVote)
def _poll_vote_deleted(sender, instance, **kwargs):
    bump(PollOption, instance.option_id, votes=-1)


def comment_published(comment) -> None:
    """Задержанный комментарий пропущен к читателю — теперь он считается.

    Зовётся из `publish_held_comment`, а не сигналом: флаг снимается
    `update()`, который `post_save` не шлёт. Держать это здесь, рядом с
    остальными счётчиками, а не там — чтобы правило «что считается»
    жило в одном файле.
    """
    bump(Story, comment.story_id, comments=1)


def _recount(target_model, field: str, source_model, group_by: str,
             count_field='pk', **only):
    """Один счётчик, пересчитанный от реальных строк одним `UPDATE`.
    Отдаёт число задетых строк — как `Story.objects.update(...)` в
    `recount_recent_views`, то есть «сколько строк пересчитано», а не
    «сколько из них реально изменилось»: второе стоило бы отдельного
    запроса до и после ради одной цифры в логе.

    `only` сужает то, что считается. Нужен он ровно одному счётчику —
    комментариям, — и появился потому, что сверка обязана считать по
    тому же правилу, что и сигнал: иначе она не чинит расхождение, а
    подтверждает его.
    """
    real = (source_model.objects.filter(**{group_by: OuterRef('pk')}, **only)
            .values(group_by).annotate(n=Count(count_field)).values('n')[:1])
    return target_model.objects.update(
        **{field: Coalesce(Subquery(real, output_field=IntegerField()), 0)})


def recount_engagement() -> dict[str, int]:
    """Полная сверка счётчиков-кэшей с рядами, из которых они выведены —
    страховка поверх сигналов: `bulk_create`/`bulk_update` их не шлют, и
    прямая правка в базе тоже идёт в обход. Отдаёт число пересчитанных
    строк по каждому счётчику — как `recount_recent_views`.

    `Story.likes` сверяется с `ChapterReaction.count` (агрегатом реакций
    главы), а не с числом строк `ChapterReactionVote`: у демо-корпуса есть
    decorative-база без обеспечивающих её голосов, и сверка по
    голосам обнулила бы её. Сама `ChapterReaction.count` от той же причины
    несверяема с нуля — у декоративной доли нет строк, из которых её
    восстановить; её защищает только сигнал на изменение голоса, без
    запасного пути реконсиляции.
    """
    likes_from_reactions = (
        ChapterReaction.objects.filter(chapter__story=OuterRef('pk'))
        .values('chapter__story').annotate(n=Sum('count')).values('n')[:1]
    )
    return {
        # Только видимые читателю — то же правило, что у сигнала выше.
        # Сверка по всем строкам подтверждала бы завышенное число, а не
        # чинила его: задержанного не видит никто.
        'story.comments': _recount(Story, 'comments', StoryComment, 'story',
                                   held=False),
        'story.likes': Story.objects.update(
            likes=Coalesce(Subquery(likes_from_reactions,
                                     output_field=IntegerField()), 0)),
        'user.followers': _recount(User, 'followers', Follow, 'following'),
        'comment.likes': _recount(StoryComment, 'likes', CommentLike, 'comment'),
        'polloption.votes': _recount(PollOption, 'votes', PollVote, 'option'),
    }
