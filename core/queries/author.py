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

from functools import cached_property

from django.db.models import F

from ..domain.catalog import PUBLIC_STATUSES
from ..domain.library import LIBRARY_KINDS
from ..domain.story import PUBLISH_CHECKLIST
from ..models import LibraryEntry, Notification, Story, User
from .catalog import all_stories, chapter_count_subquery


class AuthorFacts:
    """Всё об одном авторе, посчитанное один раз за запрос.

    Заведено не ради стройности. Хелперы этого слоя возвращают `list`, а
    не `QuerySet`, — у списка нет кэша, и каждый вызов идёт в базу заново.
    Вызывающая сторона об этом не знала и звала их столько раз, сколько
    было удобно читать: свой профиль спрашивал `my_stories_of`
    **шестнадцать раз** за один рендер, и из этого складывались
    пятьдесят девять запросов на страницу.

    Поля ленивые: объект можно создать заранее и не заплатить за то, что
    странице не понадобилось. Заявки на конкурс нужны профилю и не нужны
    кабинету — и кабинет за них не платит.

    Живёт ровно один запрос: это снимок, а не кэш. Между запросами его не
    переиспользуют — иначе страница показывала бы вчерашние работы.
    """

    def __init__(self, username: str):
        self.username = username

    def __repr__(self):
        return f'AuthorFacts({self.username!r})'

    @cached_property
    def stories(self) -> list:
        """Все работы автора, любого статуса (кабинет)."""
        return my_stories_of(self.username)

    @cached_property
    def public_stories(self) -> list:
        """Работы, которые видит посторонний (BR-73).

        Режется из уже загруженного списка, а не спрашивается отдельно:
        правило публичности одно и то же, и второй запрос с тем же
        `WHERE` — это просто второй запрос.
        """
        return [s for s in self.stories if s.is_public]

    @cached_property
    def submissions(self) -> list:
        # Импорт внутри: `contests` читает `public_stories_of` отсюда, и на
        # верхнем уровне это был бы цикл. Тот же приём, что в `catalog.py`.
        from .contests import submissions_of

        return submissions_of(self.username)

    @cached_property
    def library(self) -> list:
        """Вся библиотека читателя — все три полки одной выборкой."""
        return library_of(self.username)

    @cached_property
    def user(self):
        """Сам пользователь или None. Нужен ради `followers` в сводках."""
        if not self.username:
            return None
        return User.objects.filter(username=self.username).first()

    def shelf(self, kind: str) -> list:
        """Одна полка. Из общего списка, а не запросом на вкладку: три
        вкладки библиотеки стоили трёх выборок ради трёх счётчиков."""
        return [e for e in self.library if e.kind == kind]

    @cached_property
    def reads(self) -> int:
        """Сколько раз прочитали автора — по публичным работам (BR-73)."""
        return sum(s.views for s in self.public_stories)


def author_facts(username: str) -> AuthorFacts:
    """Снимок автора для одного запроса. Ничего не читает до обращения."""
    return AuthorFacts(username)


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


def top_stories_of(username: str, limit: int = 3, *,
                   facts: AuthorFacts = None) -> list:
    """Самые читаемые публичные работы — для рейла чужого профиля.

    По накопленному `views`, а не по окну в 14 дней: рейл отвечает «с чего
    начать знакомство с автором», а не «что у него сейчас в моде». Автор
    с одной старой сильной работой иначе остался бы без ответа.
    """
    facts = facts or author_facts(username)
    return sorted(facts.public_stories,
                  key=lambda s: s.views, reverse=True)[:limit]


def writer_attention(username: str, *, facts: AuthorFacts = None) -> list:
    """Что ждёт автора — короткая строка над списком (FR-WRITE-08).

    Отдаёт `kind` / `count` / `slug`; тексты и ссылки собирает вызывающая
    сторона. `slug` заполнен только когда элемент один: вести «3 шығарма
    модерацияда» в одну из трёх было бы враньём.
    """
    mine = (facts or author_facts(username)).stories
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

    # `has_chapters` приезжает аннотацией выдачи — прежний
    # `chapter_set.exists()` был запросом на каждую работу автора.
    _one('draft', [s for s in mine
                   if s.status == 'NotPublished' and not s.has_chapters])
    return items


def publish_checklist(story) -> list:
    """Готовность работы к модерации (FR-WRITE-09, BR-11).

    Отдаёт `key` / `ok` / `required` / `target`. Тексты — в шаблоне
    (docs/16), ссылки — во view: URL-ы в слой данных не спускаются.
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
    """Можно ли отправить работу на модерацию.

    «Готова» и «уже ушла» — разные вопросы. Отправлять можно только
    черновик: у работы на модерации кнопка означала бы повторную заявку,
    у публичной — откат в непубличное, чего автор ею не просит.
    """
    return (story is not None
            and story.status == 'NotPublished'
            and not missing_for_review(story))


def writer_stats(username: str, *, facts: AuthorFacts = None) -> dict:
    """Сводка кабинета. Разбивка по статусам обязана давать в сумме
    `total`: разбивка, не сходящаяся с целым, — то же враньё, что и
    хранимый счётчик.

    `facts` — уже собранный снимок автора. Страница профиля показывает
    рядом четыре сводки по одному и тому же списку работ, и без снимка
    каждая тянула его заново.
    """
    facts = facts or author_facts(username)
    mine = facts.stories
    user = facts.user
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


def public_stats(username: str, *, facts: AuthorFacts = None) -> dict:
    """Четыре числа публичного профиля (FR-PROF-01).

    `works` совпадает с `User.works` по построению: одно правило
    публичности, посчитанное один раз.
    """
    facts = facts or author_facts(username)
    pub = facts.public_stories
    user = facts.user
    return {
        'works':     len(pub),
        'reads':     facts.reads,
        'likes':     sum(s.likes for s in pub),
        'followers': user.followers if user else 0,
    }


def reader_stats(username: str, *, facts: AuthorFacts = None) -> dict:
    """Свой профиль: те же числа плюс приватное.

    Публичная часть берётся из `public_stats` — владелец не должен видеть
    другую арифметику, чем читатель.
    """
    facts = facts or author_facts(username)
    stats = dict(public_stats(username, facts=facts))
    stats.update({
        'works_total': len(facts.stories),
        # Из общей выборки библиотеки, а не отдельным COUNT: полки на этой
        # же странице уже прочитаны целиком.
        'finished':    len(facts.shelf('done')),
    })
    return stats


def library_of(username: str, kind: str = '') -> list:
    """Полки читателя. Пустой `kind` — вся библиотека.

    Число частей приезжает той же строкой (`story_chapters`) и садится на
    произведение вручную: строка полки говорит «3 / 12 бөлім», а
    `select_related` аннотировать связанный объект не умеет. Через
    `Prefetch` это стоило бы второго запроса, через `Story.chapters` без
    подсказки — по запросу на каждую строку полки.
    """
    if not username:
        return []
    from .library import progress_chapter_subquery

    entries = (LibraryEntry.objects.filter(user__username=username)
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


def in_library(username: str, story_slug: str) -> bool:
    """Лежит ли работа в библиотеке — для кнопки «Сақтау»."""
    return bool(username) and LibraryEntry.objects.filter(
        user__username=username, story__slug=story_slug).exists()


def story_by_slug_for_author(slug: str, username: str):
    """Работа для кабинета: любой статус, но только своя, вместе с автором.

    Отдельно от каталожного резолва: тот режет по публичности, и свой
    черновик автор в кабинете не открыл бы. Фильтр по `username` — не
    только удобство: без него любой вошедший открывал бы чужой черновик
    по прямому URL (Ф15, IDOR). Чужой и несуществующий slug неотличимы
    снаружи — оба дают `None` и одну и ту же карточку «не найдено», а не
    403: подтверждать постороннему, что slug вообще существует, незачем.
    """
    return (Story.objects.filter(slug=slug, author__username=username)
            .select_related('author', 'primary_genre', 'secondary_genre')
            # Кабинет показывает «N бөлім» — без аннотации это отдельный
            # запрос за счётом глав (`Story.chapters`).
            .annotate(chapter_count=chapter_count_subquery())
            .first())
