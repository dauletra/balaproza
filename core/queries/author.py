"""Кабинет автора, профиль и библиотека читателя.

Разделение, которое здесь легко потерять, — **кто зритель**. Кабинет
показывает всё своё, включая черновики; публичный профиль — только
публичное (BR-10, BR-73). Один раз эти две выдачи уже склеили, и на
`/u/<username>/` висели черновик и работа на модерации обычными
кликабельными карточками.

Поэтому счётчики профиля считаются здесь и по одному правилу
публичности: два числа под одним словом, посчитанные в разных местах,
однажды разъедутся — так и случилось с хранимым `Author.works`.
"""

from django.db.models import F

from ..domain.catalog import PUBLIC_STATUSES
from ..domain.library import LIBRARY_KINDS
from ..domain.story import PUBLISH_CHECKLIST
from ..models import LibraryEntry, Notification, Story, User
from .catalog import all_stories


def my_stories_of(username: str) -> list:
    """Все работы автора — любого статуса, свежие сверху.

    Порядок — «что я трогал последним»: до него список шёл в порядке
    вставки, то есть случайно. `nulls_last` обязателен: Postgres при
    `DESC` ставит `NULL` **первыми**, и работы без даты правки уехали бы
    наверх вместо конца.
    """
    if not username:
        return []
    return list(all_stories().filter(author__username=username)
                .order_by(F('updated_at').desc(nulls_last=True), 'pk'))


def public_stories_of(username: str) -> list:
    """Работы, которые видит посторонний (BR-73).

    Публичность — по `PUBLIC_STATUSES`, а не по литералу `'Published'`:
    после DEC-37 публичный сериал носит `Completed` или `OnProcess`, и
    сравнение со строкой молча выкинуло бы из профиля все сериалы.
    """
    return [s for s in my_stories_of(username) if s.status in PUBLIC_STATUSES]


def top_stories_of(username: str, limit: int = 3) -> list:
    """Самые читаемые публичные работы — для рейла чужого профиля.

    По накопленному `views`, а не по окну в 14 дней: рейл отвечает «с чего
    начать знакомство с автором», а не «что у него сейчас в моде». Автор
    с одной старой сильной работой иначе остался бы без ответа.
    """
    return sorted(public_stories_of(username),
                  key=lambda s: s.views, reverse=True)[:limit]


def writer_attention(username: str) -> list:
    """Что ждёт автора — короткая строка над списком (FR-WRITE-08).

    Отдаёт `kind` / `count` / `slug`; тексты и ссылки собирает вызывающая
    сторона. `slug` заполнен только когда элемент один: вести «3 шығарма
    модерацияда» в одну из трёх было бы враньём.
    """
    mine = my_stories_of(username)
    items = []

    def _one(kind, stories):
        if stories:
            items.append({
                'kind':  kind,
                'count': len(stories),
                'slug':  stories[0].slug if len(stories) == 1 else '',
            })

    _one('moderation', [s for s in mine if s.status == 'OnModeration'])

    unread = Notification.objects.filter(user__username=username,
                                         kind='comment', read=False).count()
    if unread:
        items.append({'kind': 'comments', 'count': unread, 'slug': ''})

    _one('draft', [s for s in mine
                   if s.status == 'NotPublished' and not s.chapter_set.exists()])
    return items


def publish_checklist(story) -> list:
    """Готовность работы к модерации (FR-WRITE-09, BR-11).

    Отдаёт `key` / `ok` / `required` / `target`. Тексты — в шаблоне
    (docs/16), ссылки — во view: URL-ы в слой данных не спускаются.
    """
    if story is None:
        return []
    done = {
        'text':       story.chapter_set.exists(),
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
    """Можно ли отправить работу на модерацию.

    «Готова» и «уже ушла» — разные вопросы. Отправлять можно только
    черновик: у работы на модерации кнопка означала бы повторную заявку,
    у публичной — откат в непубличное, чего автор ею не просит.
    """
    return (story is not None
            and story.status == 'NotPublished'
            and not missing_for_review(story))


def writer_stats(username: str) -> dict:
    """Сводка кабинета. Разбивка по статусам обязана давать в сумме
    `total`: разбивка, не сходящаяся с целым, — то же враньё, что и
    хранимый счётчик."""
    mine = my_stories_of(username)
    user = User.objects.filter(username=username).first()
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


def public_stats(username: str) -> dict:
    """Четыре числа публичного профиля (FR-PROF-01).

    `works` совпадает с `User.works` по построению: одно правило
    публичности, посчитанное один раз.
    """
    pub = public_stories_of(username)
    user = User.objects.filter(username=username).first()
    return {
        'works':     len(pub),
        'reads':     sum(s.views for s in pub),
        'likes':     sum(s.likes for s in pub),
        'followers': user.followers if user else 0,
    }


def reader_stats(username: str) -> dict:
    """Свой профиль: те же числа плюс приватное.

    Публичная часть берётся из `public_stats` — владелец не должен видеть
    другую арифметику, чем читатель.
    """
    stats = dict(public_stats(username))
    stats.update({
        'works_total': len(my_stories_of(username)),
        'finished':    LibraryEntry.objects.filter(user__username=username,
                                                   kind='done').count(),
    })
    return stats


def library_of(username: str, kind: str = '') -> list:
    """Полки читателя. Пустой `kind` — вся библиотека."""
    if not username:
        return []
    entries = (LibraryEntry.objects.filter(user__username=username)
               .select_related('story', 'story__author',
                               'story__primary_genre'))
    if kind in LIBRARY_KINDS:
        entries = entries.filter(kind=kind)
    return list(entries)


def in_library(username: str, story_slug: str) -> bool:
    """Лежит ли работа в библиотеке — для кнопки «Сақтау»."""
    return bool(username) and LibraryEntry.objects.filter(
        user__username=username, story__slug=story_slug).exists()


def story_by_slug_for_author(slug: str):
    """Работа для кабинета: любой статус, вместе с автором.

    Отдельно от каталожного резолва: тот режет по публичности, и свой
    черновик автор в кабинете не открыл бы.
    """
    return Story.objects.filter(slug=slug).select_related(
        'author', 'primary_genre', 'secondary_genre').first()
