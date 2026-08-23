"""Теги: витрины «Танымал» и «Осы аптада», автокомплит, блок-лист.

Две витрины существуют потому, что отвечают на разные вопросы (DEC-31):
накопленная популярность показывает опоры портала, недельный срез — о чём
пишут прямо сейчас. Если списки совпадут, вторая полоса вырождается в
копию первой и занимает место зря.

**Pending-тег публике не показывается** (BR-TAG-07) — ни в витринах, ни в
автокомплите: он ещё не прошёл модератора.
"""

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
