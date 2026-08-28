"""Кабинет автора, профиль и библиотека читателя.

Разделение, которое здесь легко потерять, — **кто зритель**. Кабинет
показывает всё своё, включая черновики; публичный профиль — только
публичное (BR-10, BR-73). Поэтому счётчики профиля считаются здесь и по
одному правилу публичности: два числа под одним словом, посчитанные в
разных местах, однажды разъедутся.

Хелперы принимают пользователя, а не ник: снимок его работ живёт на самом
объекте (`User.authored` и соседние), и страница, спрашивающая восемь раз,
платит один. Гость — `None`, и ответ ему пустой, а не падение.
"""

from ..domain.library import LIBRARY_KINDS
from ..domain.story import PUBLISH_CHECKLIST
from ..managers import chapter_count_subquery
from ..models import LibraryEntry, Notification, Story
from .catalog import all_stories


def my_stories_of(user):
    """Все работы автора — любого статуса, в порядке «что трогал последним».
    Гость отдаёт пустую выдачу, а не `[]`: у вызывающей стороны один тип на
    оба случая, и `.count()` по гостю не падает."""
    return all_stories().by_author(user).latest_edited()


def public_stories_of(user):
    """Работы, которые видит посторонний (BR-73)."""
    return my_stories_of(user).public()


def top_stories_of(user, limit: int = 3) -> list:
    """Самые читаемые публичные работы — для рейла чужого профиля.

    По накопленному `views`, а не по окну в 14 дней: рейл отвечает «с чего
    начать знакомство с автором», а не «что у него сейчас в моде».
    """
    if user is None:
        return []
    return sorted(user.public_works, key=lambda s: s.views, reverse=True)[:limit]


def writer_attention(user) -> list:
    """Что ждёт автора — короткая строка над списком (FR-WRITE-08).

    Отдаёт `kind` / `count` / `slug`; тексты и ссылки собирает вызывающая
    сторона. `slug` заполнен только когда элемент один: вести «3 шығарма
    модерацияда» в одну из трёх было бы враньём.
    """
    if user is None:
        return []
    mine = user.authored
    items = []

    def _one(kind, stories):
        if stories:
            items.append({
                'kind':  kind,
                'count': len(stories),
                'slug':  stories[0].slug if len(stories) == 1 else '',
            })

    _one('moderation', [s for s in mine if s.status == 'OnModeration'])

    unread = Notification.objects.filter(user=user, kind='comment',
                                         read=False).count()
    if unread:
        items.append({'kind': 'comments', 'count': unread, 'slug': ''})

    # `has_chapters` приезжает аннотацией выдачи — прежний
    # `chapter_set.exists()` был запросом на каждую работу автора.
    _one('draft', [s for s in mine
                   if s.status == 'NotPublished' and not s.has_chapters])
    return items


def publish_checklist(story) -> list:
    """Готовность работы к модерации (FR-WRITE-09, BR-11).

    Отдаёт `key` / `ok` / `required` / `target`. Тексты — в шаблоне
    (docs/ui.md), ссылки — во view: URL-ы в слой данных не спускаются.
    """
    if story is None:
        return []
    done = {
        'text':       story.has_chapters,
        'annotation': bool(story.annotation),
        'audience':   bool(story.audience),
        'cover':      bool(story.cover),
        'tags':       story.tags.exists(),
    }
    return [
        {'key': key, 'ok': done[key], 'required': required, 'target': target}
        for key, target, required in PUBLISH_CHECKLIST
    ]


def missing_for_review(story) -> list:
    """Обязательные пункты, которые ещё не закрыты (BR-11)."""
    return [i['key'] for i in publish_checklist(story)
            if i['required'] and not i['ok']]


def can_submit_for_review(story) -> bool:
    """Можно ли отправить работу на модерацию. Только черновик: у работы на
    модерации кнопка означала бы повторную заявку, у публичной — откат в
    непубличное, чего автор ею не просит."""
    return (story is not None
            and story.status == 'NotPublished'
            and not missing_for_review(story))


def writer_stats(user) -> dict:
    """Сводка кабинета. Разбивка по статусам обязана давать в сумме `total`:
    не сходящаяся с целым — то же враньё, что хранимый счётчик (BR-ACH-07).
    """
    mine = user.authored if user is not None else []
    return {
        'total':         len(mine),
        'published':     sum(1 for s in mine
                             if s.status in ('Published', 'Completed')),
        'on_moderation': sum(1 for s in mine if s.status == 'OnModeration'),
        'ongoing':       sum(1 for s in mine if s.status == 'OnProcess'),
        'draft':         sum(1 for s in mine if s.status == 'NotPublished'),
        'views':         sum(s.views for s in mine),
        'likes':         sum(s.likes for s in mine),
        'comments':      sum(s.comments for s in mine),
        'followers':     user.followers if user else 0,
    }


def public_stats(user) -> dict:
    """Четыре числа публичного профиля (FR-PROF-01). `works` совпадает с
    `User.works` по построению — одно правило публичности."""
    pub = user.public_works if user is not None else []
    return {
        'works':     len(pub),
        'reads':     user.reads if user is not None else 0,
        'likes':     sum(s.likes for s in pub),
        'followers': user.followers if user is not None else 0,
    }


def reader_stats(user) -> dict:
    """Свой профиль: те же числа плюс приватное. Публичная часть — из
    `public_stats`: владелец не должен видеть другую арифметику."""
    stats = dict(public_stats(user))
    stats.update({
        'works_total': len(user.authored) if user is not None else 0,
        # Из общей выборки библиотеки, а не отдельным COUNT: полки на этой
        # же странице уже прочитаны целиком.
        'finished':    len(user.shelf('done')) if user is not None else 0,
    })
    return stats


def library_of(user, kind: str = '') -> list:
    """Полки читателя. Пустой `kind` — вся библиотека.

    Число частей приезжает той же строкой (`story_chapters`) и садится на
    произведение вручную: строка полки говорит «3 / 12 бөлім», а
    `select_related` аннотировать связанный объект не умеет.
    """
    if user is None:
        return []
    from .library import progress_chapter_subquery

    entries = (LibraryEntry.objects.filter(user=user)
               .select_related('story', 'story__author',
                               'story__primary_genre')
               .annotate(story_chapters=chapter_count_subquery('story'),
                         # На какой главе читатель — из записи о прогрессе,
                         # а не своей колонкой (DEC-52).
                         progress_chapter=progress_chapter_subquery()))
    if kind in LIBRARY_KINDS:
        entries = entries.filter(kind=kind)
    rows = list(entries)
    for entry in rows:
        entry.story.chapter_count = entry.story_chapters
    return rows


def in_library(user, story_slug: str) -> bool:
    """Лежит ли работа в библиотеке — для кнопки «Сақтау»."""
    return user is not None and LibraryEntry.objects.filter(
        user=user, story__slug=story_slug).exists()


def story_by_slug_for_author(slug: str, user):
    """Работа для кабинета: любой статус, но только своя, вместе с автором.

    Фильтр по автору — закрытая дверь (IDOR): без него любой вошедший
    открывал бы чужой черновик по прямому URL. Чужой и несуществующий слаг
    неотличимы снаружи — оба дают `None`, а не 403.
    """
    if user is None:
        return None
    return (Story.objects.filter(slug=slug, author=user)
            .select_related('author', 'primary_genre', 'secondary_genre')
            # Кабинет показывает «N бөлім» — без аннотации это отдельный
            # запрос за счётом глав (`Story.chapters`).
            .annotate(chapter_count=chapter_count_subquery())
            .first())
