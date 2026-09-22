"""Страница произведения: главы, отклик, комментарии, подборки.

**Ряд реакций всегда полный** (BR-REACT-01): нулевые не выбрасываются —
пять кнопок обязаны выглядеть одинаково у первой главы и у сотой.

**Общие комментарии видны под каждой главой**: у отзыва на всё
произведение «правильной» главы нет.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone

from ..counters import bump_reaction_count
from ..domain.story import COMMENTS_PAGE, REACTIONS, RECENT_VIEWS_DAYS
from ..managers import chapter_count_subquery
from ..models import (
    BookOfWeek,
    Chapter,
    ChapterReactionVote,
    Collection,
    CollectionItem,
    CommentLike,
    PollVote,
    Story,
    StoryComment,
    StoryView,
)
from .catalog import all_stories
from .notifications import notify_comment, notify_reaction


def chapters_of(story_slug: str, *, as_author: bool = False) -> list:
    """Главы работы: оглавление, «N бөлімнен» и текущая — из одной выборки.

    Читателю отдаются **только опубликованные** (BR-79): у главы, чья
    ревизия ещё не одобрена, для него нет ни текста, ни строки в
    оглавлении. Автору и модератору — все, включая ту, что пишется: это
    их предпросмотр (BR-76).

    Возвращается список, а не выдача, потому что на каждой строке ставится
    метка зрителя: без неё `Chapter.shown_body` показал бы читателю рабочую
    копию. Метка по умолчанию читательская — промах прячет текст, а не
    открывает лишнее.

    Опрос приезжает `select_related`'ом: он есть у одной главы из двадцати,
    но своим запросом обходился бы дороже, чем join по пустому полю
    (BR-POLL-01); тем же join'ом приезжает и опубликованная ревизия.
    """
    rows = (Chapter.objects.filter(story__slug=story_slug)
            .select_related('poll', 'published_revision')
            .prefetch_related('reactions'))
    if as_author:
        # Кабинет показывает состояние каждой главы («тексеруде»,
        # «өзгертілген»), а оно живёт в ревизиях: без prefetch это запрос
        # на главу.
        rows = rows.prefetch_related('revisions')
    else:
        rows = rows.filter(published_revision__isnull=False)
    chapters = list(rows)
    for chapter in chapters:
        chapter.as_author = as_author
    return chapters


def _attach_my_reaction(chapter, viewer):
    """Ставит `chapter._my_reaction` — голос текущего читателя (BR-REACT-02/03).

    Гость не голосует, и запроса за него нет, но метка ставится и ему:
    её отсутствие означает «главу забыли пропустить через эту дверь», а не
    «голоса нет» (`managers.viewer_choice`).
    """
    if chapter is None:
        return chapter
    if viewer is None:
        chapter._my_reaction = ''
        return chapter
    vote = ChapterReactionVote.objects.filter(chapter=chapter,
                                             user=viewer).first()
    chapter._my_reaction = vote.kind if vote else ''
    return chapter


def chapter_of(story_slug: str, number: int, viewer=None, *,
               as_author: bool = False):
    """Одна глава по номеру. `as_author` — та же развилка, что у
    `chapters_of`: читателю неопубликованной главы не существует."""
    rows = (Chapter.objects.filter(story__slug=story_slug, number=number)
            .select_related('published_revision')
            .prefetch_related('reactions'))
    if not as_author:
        rows = rows.filter(published_revision__isnull=False)
    chapter = rows.first()
    if chapter is not None:
        chapter.as_author = as_author
    return _attach_my_reaction(chapter, viewer)


def chapter_among(chapters, number: int, viewer=None):
    """Текущая глава из уже выбранного списка глав.

    Страница произведения берёт все главы — оглавление и «N бөлімнен»
    считают по ним, — и реакции к ним приезжают тем же `prefetch`.
    Спрашивать текущую отдельным запросом значит выбрать её и её реакции
    второй раз; в `chapter_of` это законно, там списка нет.
    """
    chapter = next((c for c in chapters if c.number == number), None)
    return _attach_my_reaction(chapter, viewer)


def reactions_of(chapter, viewer=None) -> list:
    """Полный ряд из пяти реакций в каноническом порядке; `mine` — что нажал
    текущий читатель (BR-REACT-02/03). У главы из `chapter_of(..., viewer)`
    метка уже стоит, второй запрос не нужен."""
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


def toggle_chapter_reaction(chapter, user, kind: str) -> str:
    """Ставит, снимает или меняет реакцию на главе (BR-REACT-02/03).

    Одна активная реакция на пользователя и главу: повтор того же `kind`
    снимает её, другой — заменяет. `Story.likes` и `ChapterReaction.count`
    для создания/удаления голоса сдвигает сигнал (`core/counters.py`) —
    здесь остаётся только смена вида на месте (`vote.kind = kind`), под
    которую сигналу зацепиться не за что: строка голоса не создаётся и не
    удаляется. `Story.likes` — агрегат по числу голосов, а не реакций
    (BR-14a), поэтому смена вида его не трогает. Возвращает новый slug
    реакции, '' — если снята.

    Уведомление автору уходит на **поставленную** реакцию, не на снятую:
    «тебя больше не отмечают» событием не является. Смена вида — тоже
    отклик, и она его шлёт; повторной строки в ленте от этого не будет,
    её держит окно молчания в `notify_reaction`.
    """
    with transaction.atomic():
        vote = (ChapterReactionVote.objects.select_for_update()
                .filter(chapter=chapter, user=user).first())
        if vote is None:
            ChapterReactionVote.objects.create(chapter=chapter, user=user, kind=kind)
            notify_reaction(chapter, user)
            return kind
        if vote.kind == kind:
            vote.delete()
            return ''
        old_kind = vote.kind
        vote.kind = kind
        vote.save(update_fields=['kind'])
        bump_reaction_count(chapter.pk, old_kind, -1)
        bump_reaction_count(chapter.pk, kind, 1)
        notify_reaction(chapter, user)
        return kind


def _attach_my_vote(poll, viewer):
    """Ставит `poll._my_vote` — голос текущего читателя (одна ставка на
    опрос, не меняется). Гостю метка ставится пустой, по той же причине,
    что и у реакции."""
    if poll is None:
        return poll
    if viewer is None:
        poll._my_vote = ''
        return poll
    vote = PollVote.objects.filter(poll=poll, user=viewer).first()
    poll._my_vote = vote.option.slug if vote else ''
    return poll


def poll_of(story_slug: str, chapter_number: int, viewer=None):
    """Опрос главы или None: опрос необязателен (BR-POLL-01)."""
    chapter = (Chapter.objects
               .filter(story__slug=story_slug, number=chapter_number)
               .select_related('poll').first())
    return poll_for(chapter, viewer)


def poll_for(chapter, viewer=None):
    """Опрос уже выбранной главы. Пара к `chapter_among`: страница держит
    главу вместе с её опросом (`chapters_of` берёт его `select_related`),
    и спрашивать ту же строку второй раз незачем."""
    poll = getattr(chapter, 'poll', None) if chapter else None
    return _attach_my_vote(poll, viewer)


def cast_poll_vote(poll, user, option_slug: str) -> bool:
    """Ставит голос — один на опрос, не на вариант, не меняется.
    Закрытый опрос (BR-POLL-05) и повторный голос — no-op.
    Возвращает True, если голос принят."""
    if poll.closed:
        return False
    option = poll.option_set.filter(slug=option_slug).first()
    if option is None:
        return False
    with transaction.atomic():
        _vote, created = PollVote.objects.get_or_create(
            user=user, poll=poll, defaults={'option': option})
        return created


def _comments(story_slug: str):
    # Задержанного не видит никто, включая автора работы (D2): показать
    # его одному значит объяснять, почему второй его не видит.
    return (StoryComment.objects
            .filter(story__slug=story_slug, parent__isnull=True, held=False)
            .select_related('author', 'story', 'story__author')
            .prefetch_related(Prefetch(
                'reply_set',
                queryset=StoryComment.objects.filter(held=False)
                .select_related('author'))))


def _attach_liked(comments: list, viewer) -> list:
    """Проставляет `.liked` на каждый комментарий и его ответы (BR-31).

    `replies` — `cached_property` именно ради этого: второй вызов в шаблоне
    обязан вернуть те же объекты, на которых уже стоит метка.
    """
    pairs = [(c, c.replies) for c in comments]
    liked_ids = set()
    if viewer is not None:
        ids = {c.pk for c, _ in pairs} | {r.pk for _, reps in pairs for r in reps}
        liked_ids = set(CommentLike.objects.filter(
            user=viewer, comment_id__in=ids).values_list('comment_id', flat=True))
    for c, reps in pairs:
        c.liked = c.pk in liked_ids
        for r in reps:
            r.liked = r.pk in liked_ids
    return comments


def comments_of(story_slug: str, viewer=None) -> list:
    """Все верхнеуровневые комментарии произведения; ответы висят на них."""
    return _attach_liked(list(_comments(story_slug)), viewer)


def _chapter_window(story_slug: str, chapter_number: int):
    """Разговор под главой: её реплики плюс общие — те, у которых главы
    нет вовсе. Одна выборка на показ, счёт и резолв страницы, чтобы
    правило «что относится к этой главе» не разошлось между ними."""
    from django.db.models import Q

    return _comments(story_slug).filter(
        Q(chapter_number__isnull=True) | Q(chapter_number=chapter_number))


def comments_of_chapter(story_slug: str, chapter_number: int, viewer=None, *,
                        offset: int = 0, limit: int = COMMENTS_PAGE) -> list:
    """Окно разговора под главой (BR-30).

    Окно, а не весь список: у популярной работы обсуждение растёт без
    потолка, и росло оно в телефоне у читателя — вместе с ответами на
    каждую реплику и запросом «что из этого я лайкал».

    Предел стоит **умолчанием**, а не просьбой вызывающей стороны:
    забытый параметр должен давать двадцать реплик, а не всё, что есть.
    """
    rows = _chapter_window(story_slug, chapter_number)[offset:offset + limit]
    return _attach_liked(list(rows), viewer)


def comment_count_of_chapter(story_slug: str, chapter_number: int) -> int:
    """Сколько всего реплик в разговоре под главой.

    `COUNT`, а не длина окна: число в заголовке — про весь разговор, и
    «20» над первой страницей из трёх было бы неправдой. Считаются
    верхнеуровневые, как и раньше: ответы висят при своих репликах.
    """
    return _chapter_window(story_slug, chapter_number).count()


def comment_page_of(story_slug: str, chapter_number: int, comment,
                    *, limit: int = COMMENTS_PAGE) -> int:
    """На какой странице разговора окажется этот комментарий.

    Нужен после отправки: с окном новая реплика уезжает на последнюю
    страницу, и возврат на первую означал бы, что человек написал и не
    увидел написанного. Ответ ищется по **родителю** — сам он живёт при
    нём, своей позиции в списке у него нет.

    Порядок разговора — по `pk` возрастанием (`StoryComment.Meta`),
    поэтому позиция это «сколько реплик не позже этой».
    """
    root_id = comment.parent_id or comment.pk
    position = _chapter_window(story_slug, chapter_number).filter(
        pk__lte=root_id).count()
    # Целочисленное деление вверх: двадцатая реплика — ещё первая
    # страница, двадцать первая — уже вторая.
    return max(1, -(-position // limit))


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


def record_story_view(story, viewer=None) -> None:
    """Засчитать одно чтение работы: строка в журнал, оба счётчика на
    `Story` двигает сигнал (`core/counters.py`) на её создании.

    Строка нужна для убыли: без дат окно в четырнадцать дней (DEC-36) не
    убывало, и «Қазір танымал» со временем сходилась с «Ең көп оқылған»
    (DEC-55). Считать по журналу на каждой странице каталога дорого,
    поэтому колонки остаются — но `recent_views` теперь пересчитывается
    вниз (`recount_recent_views`), а не только растёт.

    Объект в памяти двигается отдельной строкой, а не подхватывает сигнал:
    иначе страница показала бы цифру, отставшую на этот самый заход, пока
    сигнал не долетел до базы и обратно."""
    StoryView.objects.create(story=story, viewer=viewer)
    story.views += 1
    story.recent_views += 1


def recount_recent_views() -> tuple[int, int]:
    """Пересчитать окно по журналу и вычистить то, что из него вышло.

    Отдаёт «сколько работ тронуто, сколько строк удалено». Пересчёт, а не
    сдвиг на единицу: колонка самоисправляется, как `Story.likes` и
    `User.followers` — приём `toggle_comment_like`.

    Вычистка идёт **после** пересчёта и по той же границе: строка старше
    окна ни на что уже не влияет, и держать её значило бы растить таблицу
    вместе со всем трафиком портала.

    Накопленный `Story.views` не трогается: журнал за пределами окна
    пуст, и пересчёт по нему обнулил бы историю работы.
    """
    edge = timezone.now() - timedelta(days=RECENT_VIEWS_DAYS)
    fresh = StoryView.objects.filter(created_at__gte=edge, story=OuterRef('pk'))
    touched = Story.objects.update(
        recent_views=Coalesce(
            Subquery(fresh.values('story').annotate(n=Count('id')).values('n')[:1]),
            0,
        )
    )
    removed, _ = StoryView.objects.filter(created_at__lt=edge).delete()
    return touched, removed


def add_comment(story, author, *, text: str, chapter_number=None, parent=None) -> StoryComment:
    """Новый комментарий или ответ (BR-30/BR-33). Валидность `parent`
    (свой ли уровень, та ли работа) проверяет вызывающая сторона —
    `top_level_comment_of` уже это гарантирует к моменту вызова.
    `Story.comments` двигает сигнал на создании строки.

    Уведомление — не сигналом (`notify_comment` объясняет, почему):
    адресатов у одного комментария бывает двое, и кто они, знает не
    строка, а само действие.

    Попавший в блок-лист **задерживается** (D2): читателю его нет,
    решение принимает модератор, и уведомление автору работы уходит
    тогда же — до решения сообщать не о чем.
    """
    from .moderation import comment_is_blocked

    held = comment_is_blocked(text)
    with transaction.atomic():
        comment = StoryComment.objects.create(
            story=story, author=author, chapter_number=chapter_number,
            parent=parent, text=text, held=held)
        if not held:
            notify_comment(comment)
        return comment


def delete_comment(comment) -> None:
    """Удаляет комментарий вместе с его ответами (каскад, BR-30 — уровень
    один, ответам своих ответов нет). `Story.comments` подстраивается сам:
    сигнал (`core/counters.py`) срабатывает на каждую удалённую строку,
    включая ответы, разнесённые тем же каскадом — отдельно считать `removed`
    больше не нужно."""
    comment.delete()


def toggle_comment_like(comment, user) -> bool:
    """Лайк комментария — toggle (BR-31): повторный клик снимает.
    `StoryComment.likes` пересчитывает сигнал (`core/counters.py`) —
    полным `count()`, а не сдвигом: у демо-комментария декоративное число
    без единой настоящей строки, и первый живой лайк обязан ответить
    правдой, а не суммой с придуманной историей. Здесь — то же самое на
    уже загруженном объекте, чтобы не отставала текущая страница.
    Возвращает новое состояние (True — лайкнул)."""
    like, created = CommentLike.objects.get_or_create(user=user, comment=comment)
    if not created:
        like.delete()
    comment.likes = comment.like_set.count()
    return created


def collections_of(story):
    """Подборки, в которых лежит работа — обратный вход со страницы.
    Порядок редакционный: жинақ и есть редакционное высказывание."""
    return Collection.objects.filter(item_set__story=story).distinct()


def sitemap_collections():
    """Жинақтар для карты сайта — без состава: краулеру нужен адрес, а
    `all_collections()` тянет обложки трёх работ на каждую подборку."""
    return Collection.objects.only('slug').order_by('position', 'pk')


def all_collections():
    """Жинақтар с составом — ровно под то, что рисует карточка.

    Карточка подборки показывает три обложки, а `cover_placeholder` берёт
    у работы название, файл и оттенок жанра. Автор и теги ей не нужны:
    двумя именами связей в `prefetch_related` они приезжали двумя
    отдельными запросами, а полный `all_stories()` добавил бы третий за
    теги. Состав одной подборки, наоборот, рисуется полными карточками —
    там `collection_by_slug` и берёт `all_stories()`.

    **Пустая подборка сюда не попадает.** Она существует как заготовка
    редакции, а для читателя это тупик: карточка обещает подборку,
    называет «0 шығарма» и открывает пустую страницу. На первый день
    портала это ровно та цифра, которой там быть не должно, — то же
    правило, по которому не рендерятся пустые ряды главной.

    Прямая ссылка на пустую подборку при этом работает
    (`collection_by_slug`): редакция собирает её постепенно и смотрит на
    то, что уже набрала.
    """
    return Collection.objects.filter(
        Exists(CollectionItem.objects.filter(collection=OuterRef('pk')))
    ).prefetch_related(
        Prefetch('item_set__story',
                 queryset=Story.objects.select_related('primary_genre')))


def collection_by_slug(slug: str):
    """Одна подборка — со всем, что рисует карточка работы. Без prefetch
    страница спрашивает автора, жанр, теги и объём на каждую работу
    состава: семьдесят шесть запросов на десять карточек."""
    return (Collection.objects
            .prefetch_related(Prefetch('item_set__story',
                                       queryset=all_stories()))
            .filter(slug=slug).first())


def book_of_week():
    """Выбор редакции на эту неделю (FR-HOME-03) или None.

    Последняя запись, а не флаг у произведения: неделя проходит, и выбор
    становится историей, а флаг пришлось бы снимать руками. Число частей
    едет той же строкой — блок главной рисуется дважды.
    """
    pick = (BookOfWeek.objects.select_related('story', 'story__author',
                                              'story__primary_genre')
            .annotate(story_chapters=chapter_count_subquery('story', published_only=True))
            .order_by('-published_on').first())
    if pick is not None:
        pick.story.chapter_count = pick.story_chapters
    return pick
