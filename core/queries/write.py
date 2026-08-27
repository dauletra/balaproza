"""Мутации кабинета автора (Ф15, Этап 1): произведение, глава, опрос.

Валидация того, что вправе прийти с формы (обязательность поля, допустимый
жанр, разрешённый переход статуса), — на стороне view: сообщения об ошибке
адресны и знают контекст запроса. Здесь только применение уже проверенных
значений к модели — тот же водораздел, что у `core/domain` против
`core/queries` в целом, только для записи, а не для чтения.
"""

from django.db.models import Max

from ..domain.slugs import slugify_kz
from ..models import Chapter, ChapterPoll, PollOption, Story
from .author import can_submit_for_review, missing_for_review
from .tags import resolve_story_tags


def _unique_story_slug(title: str) -> str:
    base = slugify_kz(title, fallback='shygarma')
    slug = base
    n = 2
    while Story.objects.filter(slug=slug).exists():
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
                          status: str, cover, tag_names) -> Story:
    """Сохранить баптаулар (FR-WRITE-04).

    `status` и `cover` — пусто значит «не меняем»: радио статуса рендерится
    только для публичного сериала (BR-10a), а файл обложки автор не
    выбирает при каждом сохранении настроек.
    """
    story.title = title
    story.annotation = annotation
    story.format = format
    story.primary_genre = genre_primary
    story.secondary_genre = genre_secondary
    story.audience = audience
    if status:
        story.status = status
    if cover:
        story.cover = cover
    story.save()
    story.tags.set(resolve_story_tags(tag_names))
    return story


def save_chapter(story, number, *, title: str, body: str) -> Chapter:
    """Сохранить главу — новую (`number=None` присваивает следующий
    номер) или уже существующую (`update_or_create` по номеру)."""
    if number is None:
        last = story.chapter_set.aggregate(Max('number'))['number__max']
        number = (last or 0) + 1
    chapter, _ = Chapter.objects.update_or_create(
        story=story, number=number, defaults={'title': title, 'body': body})
    return chapter


def save_chapter_poll(chapter, question: str, option_texts) -> None:
    """Опрос под главой (FR-STORY-13, BR-POLL-01/02).

    Пустой `question` — убрать опрос, если он был (автор передумал).
    Меньше двух непустых вариантов — тоже не опрос (BR-POLL-02): без
    выбора вопрос не имеет смысла, и лучше промолчать, чем сохранить
    сломанным. Варианты не обновляются по одному — опрос маленький
    (до 4), и пересобрать его целиком проще и надёжнее частичного diff.
    """
    question = (question or '').strip()
    if not question:
        ChapterPoll.objects.filter(chapter=chapter).delete()
        return
    options = [t.strip() for t in option_texts if t and t.strip()][:4]
    if len(options) < 2:
        return
    poll, _ = ChapterPoll.objects.update_or_create(
        chapter=chapter, defaults={'question': question[:120]})
    poll.option_set.all().delete()
    PollOption.objects.bulk_create([
        PollOption(poll=poll, slug=f'option-{i + 1}', text=text[:80], position=i)
        for i, text in enumerate(options)
    ])


def submit_story_for_review(story) -> None:
    """Черновик -> модерация (FR-WRITE-09). Автор совершает этот переход
    сам, поэтому он отдельно от `Story.apply_moderation` — тот, наоборот,
    решение модератора и требует `status == 'OnModeration'` на входе.
    Спутывать нельзя: переходы смотрят в разные стороны.
    """
    if not can_submit_for_review(story):
        missing = ', '.join(missing_for_review(story))
        raise ValueError(f'«{story.title}» толық емес: {missing}.')
    story.status = 'OnModeration'
    story.save(update_fields=['status', 'updated_at'])
