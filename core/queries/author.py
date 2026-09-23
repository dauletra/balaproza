"""Кабинет автора, профиль и библиотека читателя.

Разделение, которое здесь легко потерять, — **кто зритель**. Кабинет
показывает всё своё, включая черновики; публичный профиль — только
публичное. Поэтому счётчики профиля считаются здесь и по
одному правилу публичности: два числа под одним словом, посчитанные в
разных местах, однажды разъедутся.

Хелперы принимают пользователя, а не ник: снимок его работ живёт на самом
объекте (`User.authored` и соседние), и страница, спрашивающая восемь раз,
платит один. Гость — `None`, и ответ ему пустой, а не падение.
"""

from django.db.models import Count, Prefetch

from ..domain.library import LIBRARY_KINDS
from ..domain.story import PUBLISH_CHECKLIST, checklist_label
from ..managers import chapter_count_subquery
from ..models import (
    Chapter,
    LibraryEntry,
    ModerationDecision,
    Notification,
    Story,
)
from .catalog import all_stories


def my_stories_of(user):
    """Все работы автора — любого статуса, в порядке «что трогал последним».
    Гость отдаёт пустую выдачу, а не `[]`: у вызывающей стороны один тип на
    оба случая, и `.count()` по гостю не падает."""
    return all_stories().by_author(user).latest_edited()


def public_stories_of(user, viewer=None):
    """Работы, которые видит посторонний. `viewer` — кто смотрит,
    для меток на карточке; `None` значит «гость»."""
    return my_stories_of(user).public().for_viewer(viewer)


def top_stories_of(user, limit: int = 3) -> list:
    """Самые читаемые публичные работы — для рейла чужого профиля.

    По накопленному `views`, а не по окну в 14 дней: рейл отвечает «с чего
    начать знакомство с автором», а не «что у него сейчас в моде».
    """
    if user is None:
        return []
    return sorted(user.public_works, key=lambda s: s.views, reverse=True)[:limit]


def writer_attention(user) -> list:
    """Что ждёт автора — короткая строка над списком.

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
    # Возвращённое — первое, что требует действия автора: работа
    # ждёт не модератора, а его.
    _one('returned', [s for s in mine if s.status == 'NeedsWork'])

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
    """Готовность работы к модерации.

    Отдаёт `key` / `ok` / `required` / `target` и подписи `label` / `hint`
    из домена — одни и те же и для панели, и для сообщения об
    отказе. Ссылки собирает view: URL-ы в слой данных не спускаются.
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
    items = []
    for key, target, required in PUBLISH_CHECKLIST:
        label, hint = checklist_label(key, is_single=story.is_single)
        items.append({'key': key, 'ok': done[key], 'required': required,
                      'target': target, 'label': label, 'hint': hint})
    return items


def missing_for_review(story) -> list:
    """Обязательные пункты, которые ещё не закрыты."""
    return [i['key'] for i in publish_checklist(story)
            if i['required'] and not i['ok']]


def missing_labels(story) -> list:
    """То же, но словами — для сообщения, которое называет причину.

    Одна дверь с чек-листом панели: раньше сообщение перечисляло пункты на
    память, и всякий раз, когда не хватало не того, о чём оно говорило,
    оно просто врало.
    """
    return [i['label'] for i in publish_checklist(story)
            if i['required'] and not i['ok']]


def chapter_needs_submission(chapter) -> bool:
    """Есть ли у главы что подавать модератору.

    Сравнение идёт с тем, что уже **на проверке**, если такая ревизия есть,
    и с опубликованным, если её нет. Иначе повторное нажатие заводило бы
    одинаковые заявки, а правка после отправки — терялась.
    """
    pending = chapter.pending_revision
    if pending is not None:
        return (chapter.title, chapter.body) != (pending.title, pending.body)
    return chapter.has_unpublished_changes


def pending_review_since(story):
    """Когда работа встала в очередь модератора — или `None`.

    Момент, а не «да/нет»: автор спрашивает не только «идёт ли проверка»,
    но и «сколько уже», и до этого страница управления не отвечала ни на
    один из двух вопросов. Подпись собирает фильтр `ago`.
    """
    from ..models import ChapterRevision

    if story is None:
        return None
    first = (ChapterRevision.objects
             .filter(chapter__story=story, state='pending')
             .order_by('submitted_at').values_list('submitted_at', flat=True)
             .first())
    return first


def moderation_note(story):
    """Последнее решение модератора — **пока оно ещё про сейчас**.

    Замечание живёт до повторной отправки: как только автор подал текст
    заново, оно относится к прошлой версии и с экрана уходит. Одобрение
    замечанием не является.

    До этого следа не оставалось вовсе: работа возвращалась в черновики,
    чек-лист снова горел зелёным, кнопка отправки была активна, а
    единственный экземпляр причины лежал в ленте уведомлений — автор
    должен был помнить её наизусть, пока правит.

    Берётся из журнала решений (`ModerationDecision`), а не из ленты:
    лента чистится через месяц, и замечание к работе, которую автор
    отложил, исчезало раньше, чем он к ней возвращался.

    Замечание — **последнее** решение, если оно возврат, а не последний
    возврат вообще: иначе одобренная после исправления работа носила бы
    старое «Толықтыру қажет» до следующей подачи. Правило то же, что у
    статуса (`Story.refresh_status`).
    """
    if story is None:
        return None
    note = (ModerationDecision.objects.filter(story=story)
            .order_by('-decided_at', '-pk').first())
    if note is None or note.outcome == 'approved' or pending_review_since(story):
        return None
    return note


def can_submit_for_review(story, missing=...) -> bool:
    """Можно ли отправить работу на модерацию.

    Условий два, и оба про текст, а не про статус: чек-лист закрыт
    и есть что подавать. Прежняя проверка `status == 'NotPublished'`
    запрещала подачу публичному сериалу — то есть дописанная глава
    публиковалась в обход модерации (C1), а кнопки, которой её можно было
    бы отправить, не существовало.

    `missing=...` (Ellipsis-заглушка, не `None` — тот законный ответ
    «ничего не осталось») — посчитать самой; страница управления (11.1b,
    рабочее место) уже зовёт `missing_for_review` для чек-листа и
    передаёт готовое, чтобы `publish_checklist` не считался на одном
    показе трижды (чек-лист, `missing_for_review`, и эта проверка).
    """
    if story is None:
        return False
    if missing is ...:
        missing = missing_for_review(story)
    if missing:
        return False
    # Ревизии приезжают одним `prefetch`: `pending_revision` внутри цикла —
    # запрос на главу, то есть N+1 на каждом показе страницы управления.
    chapters = story.chapter_set.select_related(
        'published_revision').prefetch_related('revisions')
    return any(chapter_needs_submission(c) for c in chapters)


def writer_stats(user) -> dict:
    """Сводка кабинета. Разбивка по статусам обязана давать в сумме `total`:
    не сходящаяся с целым — то же враньё, что хранимый счётчик.
    """
    mine = user.authored if user is not None else []
    return {
        'total':         len(mine),
        'published':     sum(1 for s in mine
                             if s.status in ('Published', 'Completed')),
        'on_moderation': sum(1 for s in mine if s.status == 'OnModeration'),
        'ongoing':       sum(1 for s in mine if s.status == 'OnProcess'),
        'draft':         sum(1 for s in mine if s.status == 'NotPublished'),
        # Шестой статус обязан быть и здесь: разбивка, не дающая в
        # сумме `total`, — то же враньё, что хранимый счётчик.
        'needs_work':    sum(1 for s in mine if s.status == 'NeedsWork'),
        'views':         sum(s.views for s in mine),
        'likes':         sum(s.likes for s in mine),
        'comments':      sum(s.comments for s in mine),
        'followers':     user.followers if user else 0,
    }


def public_stats(user) -> dict:
    """Четыре числа публичного профиля. `works` совпадает с
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
        # Отдельным счётом: полки страница больше не читает целиком, и
        # `len()` по ним означал бы тянуть всю библиотеку ради одного
        # числа — ровно то, от чего окно и заводилось.
        'finished':    library_counts(user)['done'],
    })
    return stats


def library_counts(user) -> dict:
    """Сколько записей на каждой полке — одним запросом.

    `GROUP BY`, а не три `COUNT` и не длина загруженного списка: числа
    стоят над вкладками и нужны все три сразу, а страница показывает одну
    полку и только её страницу. До появления окна их брали `len()` по
    выборке, прочитанной целиком, — это и было тем, что росло.
    """
    if user is None:
        return {kind: 0 for kind in LIBRARY_KINDS}
    rows = (LibraryEntry.objects.filter(user=user)
            .values('kind').annotate(n=Count('pk')))
    counted = {row['kind']: row['n'] for row in rows}
    return {kind: counted.get(kind, 0) for kind in LIBRARY_KINDS}


def library_of(user, kind: str = '', *, offset: int = 0, limit=None) -> list:
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
               .annotate(story_chapters=chapter_count_subquery('story', published_only=True),
                         # На какой главе читатель — из записи о прогрессе,
                         # а не своей колонкой.
                         progress_chapter=progress_chapter_subquery()))
    if kind in LIBRARY_KINDS:
        entries = entries.filter(kind=kind)
    # Срез до материализации: `chapter_count` садится на объект циклом
    # ниже, и без окна этот цикл прошёл бы по всей библиотеке ради
    # двадцати строк на экране.
    if limit is not None:
        entries = entries[offset:offset + limit]
    rows = list(entries)
    for entry in rows:
        entry.story.chapter_count = entry.story_chapters
    return rows


def in_library(user, story_slug: str) -> bool:
    """Лежит ли работа в библиотеке — для кнопки «Сақтау»."""
    return user is not None and LibraryEntry.objects.filter(
        user=user, story__slug=story_slug).exists()


def export_portfolio(user) -> list:
    """Всё написанное автором — формой, из которой собирается выгрузка.

    Плоскими словарями, а не моделями: документ строит `domain/export`, а
    домен моделей не знает. Заодно это делает саму сборку проверяемой без
    базы.

    Берутся **рабочие копии** глав (`title`/`body`), а не опубликованные
    ревизии: автор забирает то, что написал, включая
    неодобренное. Видимость при этом называется — `published_revision_id`
    отвечает на «видит ли это читатель», и в файле это пометка у главы.

    Порядок: работы — как в кабинете, главы — как у автора на экране.
    Один запрос на работы и один на все их главы: без `prefetch_related`
    портфель из пятнадцати работ стоил бы шестнадцати.
    """
    if user is None:
        return []
    works = (Story.objects.filter(author=user)
             .prefetch_related(Prefetch(
                 'chapter_set',
                 queryset=Chapter.objects.order_by('position', 'number')))
             .latest_edited())
    return [
        {
            'title': story.title,
            'annotation': story.annotation,
            'chapters': [
                {
                    'number': chapter.number,
                    'title': chapter.title,
                    'body': chapter.body,
                    'published': chapter.published_revision_id is not None,
                }
                for chapter in story.chapter_set.all()
            ],
        }
        for story in works
    ]


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
            .annotate(chapter_count=chapter_count_subquery(published_only=True),
                      written_chapter_count=chapter_count_subquery())
            .first())
