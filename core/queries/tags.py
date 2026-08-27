"""Теги: витрины «Танымал» и «Осы аптада», автокомплит, блок-лист.

Две витрины существуют потому, что отвечают на разные вопросы (DEC-31):
накопленная популярность показывает опоры портала, недельный срез — о чём
пишут прямо сейчас. Если списки совпадут, вторая полоса вырождается в
копию первой и занимает место зря.

**Pending-тег публике не показывается** (BR-TAG-07) — ни в витринах, ни в
автокомплите: он ещё не прошёл модератора.
"""

from ..domain.slugs import slugify_kz
from ..models import BlockedTagPattern, Tag


def all_tags() -> list:
    return list(Tag.objects.all())


def tag_by_slug(slug: str):
    return Tag.objects.filter(slug=slug).first()


def tags_of(story) -> list:
    """Теги работы — включая pending.

    Фильтрация по видимости делается на стороне показа
    (`components/tag_list.html` по `viewer_is_author`): автор обязан
    видеть собственный тег, пока тот ждёт модератора.
    """
    return list(story.tags.all()) if story else []


def popular_tags(limit: int = 10) -> list:
    """Опоры портала — accepted по накопленному использованию."""
    return list(Tag.objects.filter(status='accepted')
                .order_by('-usage_count', 'name')[:limit])


def trending_tags(limit: int = 6) -> list:
    """О чём пишут на этой неделе.

    Теги без недельной активности пропускаются: иначе полоса вырождается
    в копию «Танымал тегтер».
    """
    return list(Tag.objects.filter(status='accepted', weekly_count__gt=0)
                .order_by('-weekly_count', 'name')[:limit])


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
        for t in Tag.objects.filter(status='accepted').order_by('-usage_count')
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
