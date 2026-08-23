"""Награды, подписки, уведомления и витринные счётчики портала.

Знаков у автора **два класса**, и разница между ними — в источнике факта.
Системный (`AWARDS`) вычисляется из данных: колонки «награды автора» нет
и быть не может (BR-ACH-01), иначе она разойдётся с тем, что человек
сделал. Награда конкурса, наоборот, присуждается жюри и потому хранится
присуждением (DEC-46) — «Бас жүлде» из данных не выводится.

Рейтинга здесь нет и не будет (DEC-41): знак говорит «ты сделал»,
рейтинг — «ты хуже вон того», и аудитории 14-18 второе не нужно.
"""

from dataclasses import dataclass
from typing import Callable

from django.db.models import Count, Q, Sum

from ..domain.awards import READ_TIER_ART, READ_TIERS, next_tier_for, tier_for
from ..domain.catalog import BADGE_LABELS, PUBLIC_STATUSES
from ..domain.notifications import NOTIF_BUCKETS
from ..models import AwardGrant, Follow, Genre, Notification, Story, User
from .author import my_stories_of, public_stories_of
from .contests import submissions_of


# ── Подписки (FR-PROF-10, BR-75) ─────────────────────────────────────────
def is_following(me: str, them: str) -> bool:
    return bool(me) and Follow.objects.filter(
        follower__username=me, following__username=them).exists()


def followers_of(username: str) -> list:
    return list(with_works(
        User.objects.filter(following_set__following__username=username)
        .order_by('username')))


def following_of(username: str) -> list:
    return list(with_works(
        User.objects.filter(follower_set__follower__username=username)
        .order_by('username')))


def with_works(users):
    """Аннотация «сколько работ видит читатель» — её подхватывает
    `User.works`. Без неё каждый автор в списке стоит своего запроса."""
    return users.annotate(works_count=Count(
        'stories', filter=Q(stories__status__in=PUBLIC_STATUSES), distinct=True))


def author_by_username(username: str):
    """Автор по нику или None. С числом публичных работ: его показывают
    и шапка профиля, и карточка автора."""
    if not username:
        return None
    return with_works(User.objects.filter(username=username)).first()


def new_authors(limit: int = 4) -> list:
    """«Жаңа авторлар» для главной — те, у кого меньше всего подписчиков.

    Социальное доказательство: подросток должен видеть, что здесь пишут
    такие же начинающие, а не только авторы с восемью тысячами подписок.
    """
    return list(with_works(User.objects.order_by('followers', 'username'))[:limit])


def portal_stats() -> dict:
    """Счётчики масштаба в хиро гостя (FR-HOME-01).

    Считаются по самим данным. В стабе число произведений складывалось из
    хранимых счётчиков жанров и обещало 780 работ при двадцати трёх —
    первое, что видел гость, было неправдой.
    """
    return {
        'stories': Story.objects.filter(status__in=PUBLIC_STATUSES).count(),
        'authors': User.objects.count(),
        # Просто число строк: со счётчиками произведений жанры приходят
        # отдельно, на полосу-вывеску, и считать их дважды незачем.
        'genres':  Genre.objects.count(),
    }


# ── Прочтения и ступени ──────────────────────────────────────────────────
def reads_total(username: str) -> int:
    """Сколько раз прочитали автора — по публичным работам (BR-73)."""
    return (Story.objects.filter(author__username=username,
                                 status__in=PUBLIC_STATUSES)
            .aggregate(total=Sum('views'))['total'] or 0)


def read_tier(username: str):
    """Высшая взятая ступень. В публичный ряд идёт только она: «Мың» и
    «Он мың» рядом говорят одно и то же."""
    return tier_for(reads_total(username))


def next_read_tier(username: str):
    return next_tier_for(reads_total(username))


def read_ladder(username: str) -> list:
    """Весь путь по ступеням — для своей статистики (FR-PROF-08).

    Публичный ряд показывает одну ступень; здесь видно, что дальше, ради
    чего своя статистика и заводилась.
    """
    total = reads_total(username)
    ahead = next_tier_for(total)
    return [
        {
            'threshold': threshold,
            'label':     label,
            'art':       READ_TIER_ART[threshold][0],
            'tier':      READ_TIER_ART[threshold][1],
            'earned':    total >= threshold,
            'dim':       total < threshold,
            'is_next':   bool(ahead and ahead[0] == threshold),
            'left':      max(0, threshold - total),
        }
        for threshold, label in READ_TIERS
    ]


# ── Системные знаки (FR-PROF-06, BR-ACH-01) ──────────────────────────────
@dataclass(frozen=True)
class Award:
    """Один системный знак: чем выглядит, за что даётся, как проверяется.

    Условие (`earned`) лежит рядом с наградой, а не в отдельном списке
    «как получить»: два описания одного правила однажды разойдутся.
    """

    key: str
    label: str
    art: str        # слаг иллюстрации в `components/awards/_sprite.html`
    tier: str       # металл постамента (BR-ACH-02)
    hint: str       # что сделать, чтобы получить
    earned: Callable[[str], bool]

    def as_dict(self) -> dict:
        return {'key': self.key, 'label': self.label,
                'art': self.art, 'tier': self.tier}


# Порядок — от первого шага к редкому.
AWARDS = (
    Award('first_publication', 'Алғашқы жарияланым', 'first-publication',
          'bronze', 'Бірінші шығармаңды жарияла',
          lambda u: bool(public_stories_of(u))),
    Award('contest_participant', 'Байқауға қатысты', 'contest-participant',
          'bronze', 'Кез келген байқауға өтінім жібер',
          lambda u: bool(submissions_of(u))),
    # Дописанный сериал — самая ценная награда набора: дописать начатое
    # подростку тяжелее всего, и это ровно то поведение, которое платформе
    # нужно поощрять. Одиночный рассказ сюда не считается — он «дописан»
    # в момент публикации (BR-10a, BR-ACH-04).
    Award('finished_serial', 'Сериалды аяқтады', 'finished-serial',
          'silver', 'Көп бөлімді шығармаңды аяқта',
          lambda u: any(s.status == 'Completed' and not s.is_single
                        for s in my_stories_of(u))),
    Award('contest_accepted', 'Байқауға қабылданды', 'contest-accepted',
          'silver', 'Өтінімің қазылар алқасынан өтсін',
          lambda u: any(s.status == 'accepted' for s in submissions_of(u))),
    # Системного «Байқау жеңімпазы» здесь нет — DEC-46. Один общий знак на
    # все конкурсы всех лет вытеснен наградой конкретного конкурса: она
    # называет номинацию, год и работу, а общий — только факт.
    Award('editorial_choice', BADGE_LABELS['editorial'], 'editorial-choice',
          'gold', 'Редакция шығармаңды таңдасын',
          lambda u: any(s.is_editorial_pick for s in public_stories_of(u))),
)


def achievements_of(username: str) -> list:
    """Полученные знаки — публичный ряд (FR-PROF-06).

    Ссылок здесь нет: URL-ы в слой данных не спускаются. В ряд идёт только
    высшая взятая ступень оқылым — пройденные видно в своей статистике.
    """
    if not User.objects.filter(username=username).exists():
        return []
    out = [a.as_dict() for a in AWARDS if a.earned(username)]
    tier = read_tier(username)
    if tier:
        art, metal = READ_TIER_ART[tier[0]]
        out.append({'key': 'reads', 'label': tier[1], 'art': art, 'tier': metal})
    return out


def award_catalog(username: str) -> list:
    """Все знаки с отметкой «взят» — для своей статистики (FR-PROF-08).

    Тот же реестр, что у публичного ряда: «что можно получить» не может
    разойтись с «что получено», потому что это один список.
    """
    return [{**a.as_dict(), 'hint': a.hint,
             'earned': bool(a.earned(username)),
             # Готовый флаг «обесцветить»: `{% include %}` не умеет `not`.
             'dim': not a.earned(username)}
            for a in AWARDS]


def winning_stories_of(username: str) -> list:
    """Работы автора, отмеченные наградой конкурса (DEC-46)."""
    seen, out = set(), []
    for grant in (AwardGrant.objects.filter(story__author__username=username)
                  .select_related('story', 'story__author')):
        if grant.story_id not in seen:
            seen.add(grant.story_id)
            out.append(grant.story)
    return out


def contest_awards_of(username: str) -> list:
    """Награды конкурсов автора (DEC-46), свежие сверху.

    Работа называется только пока публична (BR-73): снятая с публикации не
    должна проступать через награду. Сама награда остаётся — она
    принадлежит автору, а не видимости текста.
    """
    out = []
    for grant in (AwardGrant.objects.filter(story__author__username=username)
                  .select_related('award', 'contest', 'story')):
        out.append({
            'key':     f'{grant.contest.slug}:{grant.award.slug}',
            'title':   grant.award.title,
            'image':   grant.award.image,
            'contest': grant.contest,
            'story':   grant.story if grant.story.is_public else None,
            'year':    grant.contest.year,
            'note':    grant.note,
        })
    return sorted(out, key=lambda i: (-i['year'], i['contest'].name, i['title']))


# ── Уведомления (FR-NOTIF-01, BR-70a) ────────────────────────────────────
def notifications_for_user(username: str) -> dict:
    """Лента, сгруппированная по времени: сегодня, вчера, на этой неделе.

    Групп три, и старше недели событие не показывается: глубину ленты
    объявляет само требование, четвёртой группы «раньше» в нём нет.
    Внутри группы — свежие сверху.
    """
    grouped = {b: [] for b in NOTIF_BUCKETS}
    if not username:
        return grouped
    rows = (Notification.objects.filter(user__username=username)
            .select_related('actor', 'story', 'story__author', 'contest')
            .order_by('-created_at'))
    for n in rows:
        if n.bucket in grouped:
            grouped[n.bucket].append(n)
    return grouped


def unread_count_for_user(username: str) -> int:
    """Бейдж в шапке считает то же, что показывает страница.

    Событие старше недели в ленту не попадает (BR-70a), и учитывать его в
    бейдже значит послать автора искать уведомление, которого нет.
    """
    if not username:
        return 0
    return sum(1 for n in Notification.objects.filter(user__username=username,
                                                      read=False)
               if n.bucket)
