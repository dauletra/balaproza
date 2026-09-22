"""Теги: витрины «Танымал» и «Осы аптада», автокомплит, блок-лист.

Витрины отвечают на разные вопросы: накопленная популярность
показывает опоры портала, недельный срез — о чём пишут прямо сейчас.
Совпав, вторая полоса вырождается в копию первой.

**Pending-тег публике не показывается** — ни в витринах, ни в
автокомплите: он ещё не прошёл модератора.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import Lower
from django.utils import timezone

from ..domain.catalog import PUBLIC_STATUSES
from ..domain.slugs import slugify_kz
from ..models import BlockedTagPattern, StoryTag, Tag
from .notifications import notify_tag_rejected

# Ширина недельного среза («Осы аптада»). Живёт здесь, рядом с
# единственным запросом, который его применяет.
TRENDING_DAYS = 7

# Сколько тегов у работы. Число называлось литералом в резолве
# и параметром по умолчанию в `tag_input.html`; теперь у него одно место.
TAGS_MAX = 10


def with_counts(tags):
    """Оба счётчика тега аннотацией: накопленный и недельный.

    Колонок под ними нет — считаются по `StoryTag`, ради даты в
    которой связка и перестала быть голым M2M. Только публичные работы, как
    у жанров: по счётчику читатель не должен догадываться о черновике.
    """
    public = Q(storytag__story__status__in=PUBLIC_STATUSES)
    since = timezone.now() - timedelta(days=TRENDING_DAYS)
    return tags.annotate(
        usage=Count('storytag', filter=public, distinct=True),
        weekly=Count('storytag',
                     filter=public & Q(storytag__created_at__gte=since),
                     distinct=True),
    )


def tag_by_slug(slug: str):
    return with_counts(Tag.objects.filter(slug=slug)).first()


def tags_of(story):
    """Теги работы — включая pending. Фильтрация по видимости делается на
    стороне показа (`tag_list.html` по `viewer_is_author`): автор обязан
    видеть собственный тег, пока тот ждёт модератора."""
    return story.tags.all() if story else Tag.objects.none()


def accept_tags(tags) -> int:
    """Провести теги в `accepted`. Уведомления нет: тег
    заработал молча, и сказать тут нечего — автор увидит, что пометка
    «тексеруде» с чипа исчезла."""
    return Tag.objects.filter(pk__in=[t.pk for t in tags]).update(
        status='accepted')


def reject_tags(tags, reason: str) -> tuple[int, int]:
    """Отклонить теги: снять с работ и сказать авторам, почему.

    Отдаёт «сколько тегов, сколько уведомлений». До этого отклонение было
    одним `update(status='rejected')`, и обещание автору держалось
    наполовину: публике тег переставал показываться (выдача режет по
    `accepted`), а у автора он оставался висеть на работе, без слова о
    том, что случилось и почему.

    Причина обязательна — как у отказа в публикации: «нельзя» без
    «почему» автор не может исправить.

    Одной транзакцией: снятие связок, уведомления и смена статуса — три
    стороны одного решения, и разойтись они не должны. Связки читаются
    **до** удаления, иначе уведомлять уже не о чем.
    """
    reason = reason.strip()
    if not reason:
        raise ValueError('Себепсіз қабылдамауға болмайды.')

    pks = [t.pk for t in tags]
    with transaction.atomic():
        links = list(StoryTag.objects.filter(tag_id__in=pks)
                     .select_related('tag', 'story', 'story__author'))
        changed = Tag.objects.filter(pk__in=pks).update(status='rejected')
        for link in links:
            notify_tag_rejected(link.story, link.tag.name, reason)
        StoryTag.objects.filter(tag_id__in=pks).delete()
    return changed, len(links)


def sitemap_tags():
    """Принятые теги для `sitemap.xml`. Без счётчиков: краулеру нужен
    адрес, а не число использований."""
    return Tag.objects.filter(status='accepted').only('slug').order_by('slug')


def popular_tags(limit: int = 10):
    """Опоры портала — accepted по накопленному использованию."""
    return (with_counts(Tag.objects.filter(status='accepted'))
            .order_by('-usage', 'name')[:limit])


def trending_tags(limit: int = 6):
    """О чём пишут на этой неделе. Теги без недельной активности
    пропускаются: иначе полоса вырождается в копию «Танымал тегтер»."""
    return (with_counts(Tag.objects.filter(status='accepted'))
            .filter(weekly__gt=0)
            .order_by('-weekly', 'name')[:limit])


def is_blocked(name: str) -> bool:
    """Проверка имени тега против блок-листа. Сравнение в нижнем
    регистре: «Спам» обязан ловиться так же, как «спам».

    Совпадение **точное** — тег это одно имя целиком. У комментария
    правило другое (подстрока), и живёт оно в `queries/moderation`;
    отсюда `scope` в самом списке.
    """
    return BlockedTagPattern.objects.filter(
        pattern=(name or '').strip().lower(),
        scope__in=('tag', 'both')).exists()


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


def acceptable_tag_names(names) -> list:
    """Имена, которые вправе стать тегами: до десяти, без
    повторов по регистру, длиной 2–30, мимо блок-листа.

    Отдельной функцией, потому что спрашивают дважды — при сохранении и при
    возврате формы с ошибкой. Разойдись эти два правила, автор увидел бы в
    чипах то, чего после сохранения не окажется.
    """
    out, seen = [], set()
    for raw in names:
        if len(out) >= TAGS_MAX:
            break
        name = (raw or '').strip()
        if len(name) < 2 or len(name) > 30:
            continue
        key = name.lower()
        if key in seen or is_blocked(name):
            continue
        seen.add(key)
        out.append(name)
    return out


def resolve_story_tags(names) -> list:
    """Имена из `tag_input.html` -> список `Tag`.

    Существующий тег любого статуса переиспользуется по имени без учёта
    регистра; новый заводится `pending` — путь к `accepted` решает
    модератор, не форма. Лимит и блок-лист проверяет и клиент, здесь они
    серверной копией, на случай POST в обход JS.
    """
    result = []
    for name in acceptable_tag_names(names):
        existing = Tag.objects.filter(name__iexact=name).first()
        result.append(existing or Tag.objects.create(
            name=name, slug=_unique_tag_slug(name), status='pending'))
    return result


def preview_story_tags(names) -> list:
    """Те же теги, что завёл бы `resolve_story_tags`, но **без записи** —
    для формы, вернувшейся с ошибкой.

    Незнакомое имя отдаётся несохранённым `Tag` со статусом `new`: чип
    рисует его пунктиром, как и всякий тег, которого пока нет. Заводить
    `pending` на неудачной отправке нельзя — тег пережил бы работу,
    которая так и не сохранилась.
    """
    names = acceptable_tag_names(names)
    known = {t.name.lower(): t for t in Tag.objects.annotate(
        lowered=Lower('name')).filter(lowered__in=[n.lower() for n in names])}
    return [known.get(n.lower()) or Tag(slug='', name=n, status='new')
            for n in names]
