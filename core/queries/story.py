"""Страница произведения: главы, отклик, комментарии, подборки.

Здесь два правила, которые легко потерять при переезде на модели.

**Ряд реакций всегда полный** (BR-REACT-01). Нулевые не выбрасываются:
пять кнопок обязаны выглядеть одинаково у первой главы и у сотой, иначе
читатель каждый раз ищет нужную заново.

**Общие комментарии видны под каждой главой.** У отзыва на всё
произведение «правильной» главы нет, и прятать его до конца книги значит
прятать навсегда.
"""

from ..domain.story import REACTIONS
from ..models import BookOfWeek, Chapter, Collection, StoryComment


def chapters_of(story_slug: str) -> list:
    return list(Chapter.objects.filter(story__slug=story_slug)
                .prefetch_related('reactions'))


def chapter_of(story_slug: str, number: int):
    return (Chapter.objects.filter(story__slug=story_slug, number=number)
            .prefetch_related('reactions').first())


def reactions_of(chapter) -> list:
    """Полный ряд из пяти реакций в каноническом порядке.

    `mine` — что нажал текущий читатель — пока всегда `False`: нажать
    реакцию негде до Ф15, и «моего» голоса не существует. Как только
    появится запись, здесь встанет запрос к таблице голосов; ряд, порядок
    и нули не изменятся.
    """
    counts = chapter.reaction_counts if chapter else {}
    return [
        {'reaction': r, 'count': counts.get(r.slug, 0), 'mine': False}
        for r in REACTIONS
    ]


def poll_of(story_slug: str, chapter_number: int):
    """Опрос главы или None: опрос необязателен (BR-POLL-01)."""
    chapter = (Chapter.objects
               .filter(story__slug=story_slug, number=chapter_number)
               .select_related('poll').first())
    poll = getattr(chapter, 'poll', None) if chapter else None
    return poll


def _comments(story_slug: str):
    return (StoryComment.objects
            .filter(story__slug=story_slug, parent__isnull=True)
            .select_related('author', 'story', 'story__author')
            .prefetch_related('reply_set__author'))


def comments_of(story_slug: str) -> list:
    """Все верхнеуровневые комментарии произведения; ответы висят на них."""
    return list(_comments(story_slug))


def comments_of_chapter(story_slug: str, chapter_number: int) -> list:
    """Комментарии главы плюс общие — те, у которых главы нет вовсе."""
    from django.db.models import Q

    return list(_comments(story_slug).filter(
        Q(chapter_number__isnull=True) | Q(chapter_number=chapter_number)))


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
    """
    return (BookOfWeek.objects.select_related('story', 'story__author',
                                              'story__primary_genre')
            .order_by('-published_on').first())
