"""Теги: витрины «Танымал» и «Осы аптада», автокомплит, блок-лист.

Две витрины существуют потому, что отвечают на разные вопросы (DEC-31):
накопленная популярность показывает опоры портала, недельный срез — о чём
пишут прямо сейчас. Если списки совпадут, вторая полоса вырождается в
копию первой и занимает место зря.

**Pending-тег публике не показывается** (BR-TAG-07) — ни в витринах, ни в
автокомплите: он ещё не прошёл модератора.
"""

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from ..domain.catalog import PUBLIC_STATUSES
from ..domain.slugs import slugify_kz
from ..models import BlockedTagPattern, Tag

# Ширина недельного среза («Осы аптада», DEC-31). Живёт здесь, рядом с
# единственным запросом, который его применяет.
TRENDING_DAYS = 7


def with_counts(tags):
    """Оба счётчика тега аннотацией: накопленный и недельный.

    Колонок под ними больше нет (DEC-53). Считаются они по `StoryTag` —
    той самой таблице, ради даты в которой связка и перестала быть голым
    M2M: `weekly_count` без неё было нечем посчитать, и он лежал
    литералом, который не менялся никогда.

    Считаются только публичные работы — как у жанров: по счётчику
    читатель не должен догадываться, что у кого-то есть черновик с этим
    тегом.
    """
    public = Q(storytag__story__status__in=PUBLIC_STATUSES)
    since = timezone.now() - timedelta(days=TRENDING_DAYS)
    return tags.annotate(
        usage=Count('storytag', filter=public, distinct=True),
        weekly=Count('storytag',
                     filter=public & Q(storytag__created_at__gte=since),
                     distinct=True),
    )


def all_tags():
    return with_counts(Tag.objects.all())


def tag_by_slug(slug: str):
    return with_counts(Tag.objects.filter(slug=slug)).first()


def tags_of(story):
    """Теги работы — включая pending.

    Фильтрация по видимости делается на стороне показа
    (`components/tag_list.html` по `viewer_is_author`): автор обязан
    видеть собственный тег, пока тот ждёт модератора.
    """
    return story.tags.all() if story else Tag.objects.none()


def popular_tags(limit: int = 10):
    """Опоры портала — accepted по накопленному использованию."""
    return (with_counts(Tag.objects.filter(status='accepted'))
            .order_by('-usage', 'name')[:limit])


def trending_tags(limit: int = 6):
    """О чём пишут на этой неделе.

    Теги без недельной активности пропускаются: иначе полоса вырождается
    в копию «Танымал тегтер».
    """
    return (with_counts(Tag.objects.filter(status='accepted'))
            .filter(weekly__gt=0)
            .order_by('-weekly', 'name')[:limit])


def is_blocked(name: str) -> bool:
    """Проверка имени тега против блок-листа (BR-TAG-05).

    Сравнение в нижнем регистре: «Спам» обязан ловиться так же, как
    «спам». Нормализацию на входе делает сама модель.
    """
    return BlockedTagPattern.objects.filter(
        pattern=(name or '').strip().lower()).exists()


def accepted_tags_json() -> list:
    """Accepted-теги простыми словарями — для автокомплита в форме."""
    return [
        {'slug': t.slug, 'name': t.name, 'usage_count': t.usage_count}
        for t in with_counts(Tag.objects.filter(status='accepted')).order_by('-usage')
    ]


def blocked_tag_patterns_list() -> list:
    return sorted(BlockedTagPattern.objects.values_list('pattern', flat=True))


def _unique_tag_slug(name: str) -> str:
    base = slugify_kz(name, max_length=44, fallback='tag')
    slug = base
    n = 2
    while Tag.objects.filter(slug=slug).exists():
        slug = f'{base}-{n}'
        n += 1
    return slug


def resolve_story_tags(names) -> list:
    """Имена из `tag_input.html` (BR-TAG-01/02/03/06) -> список `Tag`.

    Существующий тег (любого статуса) переиспользуется по имени без учёта
    регистра — вторая строка с тем же именем и другим `pending`/`accepted`
    была бы дублем. Новый тег заводится `pending`: путь к `accepted`
    решает модератор, не форма.

    Лимит (10, BR-TAG-01) и блок-лист (BR-TAG-05) уже проверяет
    `tag_input.html` на клиенте — здесь та же пара правил серверной
    копией, на случай POST в обход JS.
    """
    result = []
    seen = set()
    for raw in names:
        if len(result) >= 10:
            break
        name = (raw or '').strip()
        if len(name) < 2 or len(name) > 30:
            continue
        key = name.lower()
        if key in seen or is_blocked(name):
            continue
        seen.add(key)
        existing = Tag.objects.filter(name__iexact=name).first()
        if existing:
            result.append(existing)
            continue
        result.append(Tag.objects.create(
            name=name, slug=_unique_tag_slug(name), status='pending'))
    return result
