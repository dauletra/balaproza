"""Мутации кабинета автора (Ф15, Этап 1): произведение, глава, опрос.

Валидация того, что вправе прийти с формы (обязательность поля, допустимый
жанр, разрешённый переход статуса), — на стороне view: сообщения об ошибке
адресны и знают контекст запроса. Здесь только применение уже проверенных
значений к модели — тот же водораздел, что у `core/domain` против
`core/queries` в целом, только для записи, а не для чтения.
"""

from django.db import transaction
from django.db.models import Case, Max, PositiveSmallIntegerField, Value, When
from django.utils import timezone

from ..domain.slugs import slugify_kz
from ..models import (
    Chapter, ChapterPoll, ChapterRevision, PollOption, Story, StoryComment,
)
from .author import (
    can_submit_for_review,
    chapter_needs_submission,
    missing_for_review,
)
from .tags import resolve_story_tags


def _unique_story_slug(title: str, *, exclude_pk=None) -> str:
    base = slugify_kz(title, fallback='shygarma')
    slug = base
    n = 2
    taken = Story.objects.exclude(pk=exclude_pk) if exclude_pk else Story.objects.all()
    while taken.filter(slug=slug).exists():
        slug = f'{base}-{n}'
        n += 1
    return slug


def create_story(author, *, title: str, format: str, genre_primary) -> Story:
    """Новый черновик (FR-WRITE-01). Статус всегда `NotPublished` — автор
    не выбирает его на создании (BR-10)."""
    return Story.objects.create(
        slug=_unique_story_slug(title), title=title, author=author,
        primary_genre=genre_primary, format=format, status='NotPublished',
    )


def update_story_settings(story, *, title: str, annotation: str, format: str,
                          genre_primary, genre_secondary, audience: str,
                          status: str, cover, remove_cover: bool = False,
                          tag_names) -> Story:
    """Сохранить баптаулар (FR-WRITE-04).

    `status` и `cover` — пусто значит «не меняем»: радио статуса рендерится
    только для публичного сериала (BR-10a), а файл обложки автор не
    выбирает при каждом сохранении настроек. `remove_cover` — третье
    состояние (BR-86): явно убрать обложку, не заменяя её другой. Новый
    файл важнее снятия — отмеченный чекбокс рядом с выбранным файлом
    значения не имеет.
    """
    if title != story.title and not story.is_public:
        # Слаг живёт названием, пока у работы нет читателя (M1, BR-87):
        # переименованная до публикации живёт по адресу первого черновика
        # иначе — постоянного адреса ещё ни у кого нет, менять нечего. После
        # первой опубликованной главы название и адрес расходятся насовсем:
        # ссылка на публичную работу не должна тихо ломаться от правки.
        story.slug = _unique_story_slug(title, exclude_pk=story.pk)
    story.title = title
    story.annotation = annotation
    story.format = format
    story.primary_genre = genre_primary
    story.secondary_genre = genre_secondary
    story.audience = audience
    # Радио «Мәртебесі» больше не пишет статус — статус выводится из глав
    # (BR-79). Оно отвечает на единственный вопрос, который в нём и был:
    # дописана работа или продолжается. Пусто значит «не меняем» — радио
    # рендерится только публичному сериалу (BR-10a).
    if status:
        story.completed_by_author = status == 'Completed'
    if cover:
        story.cover = cover
    elif remove_cover:
        story.cover = ''
    story.save()
    story.tags.set(resolve_story_tags(tag_names))
    story.refresh_status()
    return story


def chapter_by_id(story, chapter_id):
    """Глава этой работы по `pk` — стабильный адрес кабинета (BR-83).

    Фильтр идёт через `story.chapter_set`, а не голый `Chapter.objects`:
    чужой `pk` той же дорогой не находится (IDOR) — так же, как
    `story_by_slug_for_author` режет по автору выше по цепочке.
    """
    if chapter_id is None:
        return None
    chapter = (story.chapter_set.filter(pk=chapter_id)
              .select_related('poll', 'published_revision').first())
    if chapter is not None:
        chapter.as_author = True
    return chapter


def _next_chapter_slot(story) -> int:
    last = story.chapter_set.aggregate(Max('number'))['number__max']
    return (last or 0) + 1


def _touch_story(story) -> None:
    """Написание главы — правка работы (S4, AUDIT-WRITE-FLOW): без этого
    автор, писавший часами через автосохранение, не поднимался в списке
    кабинета «что трогал последним» (`latest_edited()` смотрит на
    `Story.updated_at`, а `Chapter.save()` его не трогает).

    Здесь, а не в `Chapter.save()`: там же создают демо-корпус (сид бэкдейтит
    `updated_at` отдельным `update()` сразу после `_seed_stories` — см. её
    docstring) и фабрики тестов, и тронуть его на каждую главу означало бы
    молча стирать нарочно выставленную давность.
    """
    Story.objects.filter(pk=story.pk).update(updated_at=timezone.now())


def _resolve_chapter_id(story, chapter_id):
    """Куда на самом деле пишет `chapter_id is None` (BR-85).

    У `single` глава ровно одна: прямой POST на `/chapter/new/` в обход
    интерфейса не должен заводить вторую — он дописывает существующую.
    `chapter_editor` уже отводит такой запрос редиректом; здесь та же
    защита на случай прямого POST/автосохранения мимо страницы.
    """
    if chapter_id is not None or not story.is_single:
        return chapter_id
    existing = story.chapter_set.first()
    return existing.pk if existing is not None else None


@transaction.atomic
def save_chapter(story, chapter_id, *, title: str, body: str,
                 poll_question: str = '', poll_options=()) -> Chapter:
    """Сохранить главу вместе с её опросом — новую (`chapter_id=None` берёт
    следующий номер) или существующую, по `pk` (BR-83).

    Одна дверь и одна транзакция, потому что для автора это одно действие:
    он нажал «сохранить». Порознь они означали бы состояние «глава есть,
    опроса нет», в которое можно попасть падением между двумя записями, —
    и автор увидел бы «Жоба сақталды» про наполовину сохранённое.

    Что вправе прийти (вопрос без двух вариантов, слишком длинный текст),
    решено раньше — в `ChapterForm`. Здесь только применение.
    """
    chapter_id = _resolve_chapter_id(story, chapter_id)
    if chapter_id is None:
        number = _next_chapter_slot(story)
        chapter = Chapter.objects.create(
            story=story, number=number, position=number, title=title, body=body)
    else:
        chapter = story.chapter_set.get(pk=chapter_id)
        chapter.title = title
        chapter.body = body
        chapter.save()
    _save_poll(chapter, poll_question, poll_options)
    _touch_story(story)
    return chapter


def autosave_chapter(story, chapter_id, *, title: str, body: str) -> Chapter | None:
    """Автосохранение черновика главы (BR-78).

    Отдельная дверь от `save_chapter`, потому что у автосохранения другие
    обязанности. Оно не трогает опрос — тот автор правит осознанно, и
    затирать его каждые три секунды содержимым полей, которых на экране
    может не быть, нельзя. И оно не требует законченности: пустой
    заголовок посреди набора — состояние, а не ошибка.

    `None` — если `chapter_id` не находится в этой работе (BR-83): чужой
    или устаревший id не заводит главу заново, вызывающая сторона отвечает
    404, а не тихо создаёт дубль.

    **Несменившееся не пишется.** Предела частоты у автосохранения нет и
    по времени быть не должно: автор, пишущий быстро, упирался бы в него
    ровно тогда, когда страховка нужнее всего. Предел тут по смыслу —
    запись, ничего не меняющая, не запись вовсе. Она стоила `UPDATE` по
    тексту главы, второго по `updated_at` работы и сдвигала «когда
    трогали» у работы, которую не трогали.

    Редактор шлёт автосохранение по таймеру после ввода, но адрес
    открытый: прямой POST повторял бы одно и то же тело сколько угодно
    раз.
    """
    chapter_id = _resolve_chapter_id(story, chapter_id)
    if chapter_id is None:
        number = _next_chapter_slot(story)
        chapter = Chapter.objects.create(
            story=story, number=number, position=number, title=title, body=body)
        _touch_story(story)
        return chapter
    chapter = story.chapter_set.filter(pk=chapter_id).first()
    if chapter is None:
        return None
    # Сравнение по тому же нормализованному виду, в каком тело ляжет в
    # базу (`Chapter.save`): браузер шлёт CRLF, и без нормализации
    # «ничего не изменилось» никогда не совпадало бы само с собой.
    normalized = body.replace('\r\n', '\n').replace('\r', '\n')
    if (chapter.title, chapter.body) == (title, normalized):
        return chapter
    chapter.title = title
    chapter.body = body
    chapter.save()
    _touch_story(story)
    return chapter


def _remap_comment_chapter_numbers(story, mapping: dict[int, int]) -> None:
    """Перевести `StoryComment.chapter_number` вслед за пересчётом номеров
    (BR-84). Комментарий швартуется к номеру, а не к `pk` главы, и без
    этого перестановка сдвигала бы комментарии на чужой текст: правка
    первой главы главой номер два делает старый комментарий про вторую
    выглядящим так, будто он про то, что раньше было третьей.

    Один `UPDATE` через `CASE` — не построчный цикл: SQL считает `CASE` по
    значению до изменения, так что перестановка номеров (1↔2 и подобные)
    не задевает сама себя, как задевал бы последовательный `filter().update()`
    на пересекающихся значениях.
    """
    mapping = {old: new for old, new in mapping.items() if old != new}
    if not mapping:
        return
    whens = [
        When(chapter_number=old,
            then=Value(new, output_field=PositiveSmallIntegerField(null=True)))
        for old, new in mapping.items()
    ]
    StoryComment.objects.filter(
        story=story, chapter_number__in=list(mapping.keys()),
    ).update(chapter_number=Case(*whens))


@transaction.atomic
def _renumber_chapters(story) -> None:
    """Пересчитать `number`/`position` контигом 1..N по текущему порядку
    (BR-84) — после удаления главы или перестановки соседних.

    Двухпроходный `bulk_update`: `unique(story, number)` не отложен
    (Postgres проверяет его посуше, а не в конце транзакции), и прямая
    перестановка двух номеров упёрлась бы в чужое ещё не освобождённое
    значение. Временный сдвиг в заведомо свободный диапазон (по номеру
    строки в списке, а не по `pk`: `number` — `PositiveSmallIntegerField`,
    и глобально растущий `pk` рано или поздно вышел бы за его границы)
    обходит это без снятия constraint.
    """
    chapters = list(story.chapter_set.order_by('position', 'id'))
    old_numbers = [chapter.number for chapter in chapters]
    for i, chapter in enumerate(chapters):
        chapter.number = 10_000 + i
    Chapter.objects.bulk_update(chapters, ['number'])
    for i, chapter in enumerate(chapters, start=1):
        chapter.number = i
        chapter.position = i
    Chapter.objects.bulk_update(chapters, ['number', 'position'])
    _remap_comment_chapter_numbers(story, dict(zip(
        old_numbers, (c.number for c in chapters))))


def delete_chapter(story, chapter_id) -> bool:
    """Удалить главу автора (BR-84) — безвозвратно, как и всю работу
    («Қауіпті аймақ» в `manage_story.html`). Оставшиеся смыкаются в контиг,
    статус работы пересчитывается — удаление последней главы, например,
    возвращает её в черновик.

    Комментарии удалённой главы не удаляются вслед за ней — текст, который
    они разбирали, ушёл, но не мнение о нём. Они становятся общими
    (`chapter_number=None`), той же категории, что и комментарий ко всему
    произведению, а не молча переезжают на главу, занявшую освободившийся
    номер (BR-84)."""
    chapter = story.chapter_set.filter(pk=chapter_id).first()
    if chapter is None:
        return False
    with transaction.atomic():
        deleted_number = chapter.number
        chapter.delete()
        StoryComment.objects.filter(
            story=story, chapter_number=deleted_number).update(
            chapter_number=None)
        _renumber_chapters(story)
    story.refresh_status()
    return True


def move_chapter(story, chapter_id, direction: str) -> bool:
    """Переставить главу с соседом (BR-84). No-op на границе списка и на
    неизвестном `direction` — кнопки вверх/вниз сами не рисуются на
    границах, но прямой POST не должен падать."""
    chapters = list(story.chapter_set.order_by('position', 'id'))
    index = next((i for i, c in enumerate(chapters) if c.pk == chapter_id), None)
    if index is None:
        return False
    offset = {'up': -1, 'down': 1}.get(direction)
    if offset is None:
        return False
    neighbor = index + offset
    if not 0 <= neighbor < len(chapters):
        return False
    with transaction.atomic():
        a, b = chapters[index], chapters[neighbor]
        a.position, b.position = b.position, a.position
        Chapter.objects.bulk_update([a, b], ['position'])
        _renumber_chapters(story)
    return True


def _save_poll(chapter, question: str, option_texts) -> None:
    """Опрос под главой (FR-STORY-13, BR-POLL-01/02).

    Пустой `question` — убрать опрос, если он был: автор передумал, и это
    законный исход, а не ошибка. Варианты не обновляются по одному — опрос
    маленький, и пересобрать его целиком проще и надёжнее частичного diff.
    """
    question = (question or '').strip()
    if not question:
        ChapterPoll.objects.filter(chapter=chapter).delete()
        return
    poll, _ = ChapterPoll.objects.update_or_create(
        chapter=chapter, defaults={'question': question})
    poll.option_set.all().delete()
    PollOption.objects.bulk_create([
        PollOption(poll=poll, slug=f'option-{i + 1}', text=text, position=i)
        for i, text in enumerate(option_texts)
    ])


@transaction.atomic
def withdraw_story_from_review(story) -> int:
    """Отозвать поданное с модерации (BR-80).

    Ревизия не удаляется, а возвращается в `draft`: это по-прежнему снимок
    текста, просто больше не заявка. Опубликованного отзыв не касается —
    читатель не должен замечать, что автор передумал.

    До этого кнопки не было вовсе: заметив опечатку через минуту после
    отправки, автор мог только ждать модератора, чтобы тот вернул работу.
    """
    count = ChapterRevision.objects.filter(
        chapter__story=story, state='pending').update(state='draft')
    story.refresh_status()
    return count


@transaction.atomic
def submit_story_for_review(story) -> int:
    """Отправить на модерацию **то, что изменилось** (FR-WRITE-09, BR-79).

    Раньше это был переход статуса: `NotPublished -> OnModeration`. С
    модерацией по главам подаётся текст — по ревизии на каждую главу, чья
    рабочая копия расходится с тем, что уже видит читатель. Отсюда и то,
    что публичный сериал теперь тоже подаёт: дописанная глава проходит
    проверку, а не публикуется сама.

    Правка главы, уже стоящей в очереди, не заводит вторую заявку —
    прежняя ревизия перестаёт быть поданной и остаётся в истории
    черновиком (V10 в AUDIT-WRITE-FLOW: до этого автор правил текст после
    отправки, и модератор читал не то, что ему отправляли).

    Возвращает число поданных глав.
    """
    if not can_submit_for_review(story):
        missing = ', '.join(missing_for_review(story))
        raise ValueError(f'«{story.title}» толық емес: {missing}.')

    now = timezone.now()
    submitted = 0
    for chapter in story.chapter_set.all():
        if not chapter_needs_submission(chapter):
            continue
        ChapterRevision.objects.filter(chapter=chapter, state='pending').update(
            state='draft')
        ChapterRevision.objects.create(
            chapter=chapter, title=chapter.title, body=chapter.body,
            state='pending', submitted_at=now)
        submitted += 1
    story.refresh_status()
    return submitted
