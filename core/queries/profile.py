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
from datetime import datetime, time, timedelta
from typing import Callable

from django.db.models import Count, Q, Sum
from django.utils import timezone

from ..domain.awards import READ_TIER_ART, READ_TIERS, next_tier_for, tier_for
from ..domain.catalog import BADGE_LABELS, PUBLIC_STATUSES
from ..domain.notifications import NOTIF_BUCKETS
from ..models import AwardGrant, Follow, Genre, Notification, Story, User
from .author import AuthorFacts, author_facts


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


def update_profile(user, *, pen_name: str, name: str, bio: str,
                   age, gender: str, avatar) -> None:
    """Сохранить свой профиль (FR-PROF-01, Ф15 Этап 6).

    `age`/`gender` — самодекларация (DEC-24), без верификации. `avatar` —
    пусто значит «не меняем»: тот же приём, что у `update_story_settings`
    и его `cover` — автор не переизбирает файл при каждом сохранении.
    """
    user.pen_name = pen_name
    user.name = name
    user.bio = bio
    user.age = age
    user.gender = gender
    if avatar:
        user.avatar = avatar
    user.save()


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
def reads_total(username: str, *, facts: AuthorFacts = None) -> int:
    """Сколько раз прочитали автора — по публичным работам (BR-73).

    Со снимком считается из уже загруженных работ: правило публичности то
    же самое, и отдельный `SUM` по тем же строкам — просто ещё один
    запрос. Без снимка остаётся агрегатом — сам по себе он дешевле, чем
    выборка всех работ ради суммы.
    """
    if facts is not None:
        return facts.reads
    return (Story.objects.filter(author__username=username,
                                 status__in=PUBLIC_STATUSES)
            .aggregate(total=Sum('views'))['total'] or 0)


def read_tier(username: str, *, facts: AuthorFacts = None):
    """Высшая взятая ступень. В публичный ряд идёт только она: «Мың» и
    «Он мың» рядом говорят одно и то же."""
    return tier_for(reads_total(username, facts=facts))


def read_ladder(username: str, *, facts: AuthorFacts = None) -> list:
    """Весь путь по ступеням — для своей статистики (FR-PROF-08).

    Публичный ряд показывает одну ступень; здесь видно, что дальше, ради
    чего своя статистика и заводилась.
    """
    total = reads_total(username, facts=facts)
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

    Проверка читает `AuthorFacts`, а не ник. Пока она принимала ник,
    каждая из пяти наград шла в базу за работами автора сама, а
    `award_catalog` вдобавок звал её дважды на награду — десять полных
    выборок ради пяти галочек.
    """

    key: str
    label: str
    art: str        # слаг иллюстрации в `components/awards/_sprite.html`
    tier: str       # металл постамента (BR-ACH-02)
    hint: str       # что сделать, чтобы получить
    earned: Callable[[AuthorFacts], bool]

    def as_dict(self) -> dict:
        return {'key': self.key, 'label': self.label,
                'art': self.art, 'tier': self.tier}


# Порядок — от первого шага к редкому.
AWARDS = (
    Award('first_publication', 'Алғашқы жарияланым', 'first-publication',
          'bronze', 'Бірінші шығармаңды жарияла',
          lambda f: bool(f.public_stories)),
    Award('contest_participant', 'Байқауға қатысты', 'contest-participant',
          'bronze', 'Кез келген байқауға өтінім жібер',
          lambda f: bool(f.submissions)),
    # Дописанный сериал — самая ценная награда набора: дописать начатое
    # подростку тяжелее всего, и это ровно то поведение, которое платформе
    # нужно поощрять. Одиночный рассказ сюда не считается — он «дописан»
    # в момент публикации (BR-10a, BR-ACH-04).
    Award('finished_serial', 'Сериалды аяқтады', 'finished-serial',
          'silver', 'Көп бөлімді шығармаңды аяқта',
          lambda f: any(s.status == 'Completed' and not s.is_single
                        for s in f.stories)),
    Award('contest_accepted', 'Байқауға қабылданды', 'contest-accepted',
          'silver', 'Өтінімің қазылар алқасынан өтсін',
          lambda f: any(s.status == 'accepted' for s in f.submissions)),
    # Системного «Байқау жеңімпазы» здесь нет — DEC-46. Один общий знак на
    # все конкурсы всех лет вытеснен наградой конкретного конкурса: она
    # называет номинацию, год и работу, а общий — только факт.
    Award('editorial_choice', BADGE_LABELS['editorial'], 'editorial-choice',
          'gold', 'Редакция шығармаңды таңдасын',
          lambda f: any(s.is_editorial_pick for s in f.public_stories)),
)


def award_catalog(username: str, *, facts: AuthorFacts = None) -> list:
    """Все знаки с отметкой «взят» — для своей статистики (FR-PROF-08).

    Тот же реестр, что у публичного ряда: «что можно получить» не может
    разойтись с «что получено», потому что это один список.
    """
    facts = facts or author_facts(username)
    out = []
    for a in AWARDS:
        # Один вызов на награду. Раньше их было два — второй считал `dim`,
        # то есть заново вычислял отрицание уже известного.
        earned = bool(a.earned(facts))
        out.append({**a.as_dict(), 'hint': a.hint, 'earned': earned,
                    # Готовый флаг «обесцветить»: `{% include %}` не умеет `not`.
                    'dim': not earned})
    return out


def achievements_of(username: str, *, facts: AuthorFacts = None) -> list:
    """Полученные знаки — публичный ряд (FR-PROF-06).

    Ссылок здесь нет: URL-ы в слой данных не спускаются. В ряд идёт только
    высшая взятая ступень оқылым — пройденные видно в своей статистике.
    """
    facts = facts or author_facts(username)
    if facts.user is None:
        return []
    out = [a.as_dict() for a in AWARDS if a.earned(facts)]
    tier = read_tier(username, facts=facts)
    if tier:
        art, metal = READ_TIER_ART[tier[0]]
        out.append({'key': 'reads', 'label': tier[1], 'art': art, 'tier': metal})
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
# Глубина ленты — семь дней. Число живёт здесь, а не в двух местах: его
# знают и группировка, и бейдж в шапке, и разойтись им нельзя — бейдж,
# считающий шире ленты, посылает автора искать уведомление, которого нет.
FEED_DAYS = 7


def _feed_window_start():
    """Начало окна ленты: полночь того дня, который ещё показывается.

    Границей идёт момент, а не `__date` над колонкой: функция над полем
    отрезает индекс, а окно у всех запросов одно и то же. Совпадает с
    `Notification.bucket` по построению — там условие `days_ago <= 7`,
    здесь та же полночь семь дней назад по алматинскому времени.
    """
    day = timezone.localdate() - timedelta(days=FEED_DAYS)
    return timezone.make_aware(datetime.combine(day, time.min))


def notifications_for_user(username: str) -> dict:
    """Лента, сгруппированная по времени: сегодня, вчера, на этой неделе.

    Групп три, и старше недели событие не показывается: глубину ленты
    объявляет само требование, четвёртой группы «раньше» в нём нет.
    Внутри группы — свежие сверху.
    """
    grouped = {b: [] for b in NOTIF_BUCKETS}
    if not username:
        return grouped
    # Окно режется в базе, а не циклом по всем уведомлениям автора: лента
    # показывает неделю, и у человека с двумя годами истории отбрасывать
    # лишнее в Python значит везти всю историю ради семи дней.
    rows = (Notification.objects
            .filter(user__username=username,
                    created_at__gte=_feed_window_start())
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

    Считает база. Прежний вариант вытягивал все непрочитанные строки и
    отбрасывал старые по свойству `bucket` — на **каждой** странице у
    каждого вошедшего, потому что число зовёт контекст-процессор.
    """
    if not username:
        return 0
    return Notification.objects.filter(
        user__username=username, read=False,
        created_at__gte=_feed_window_start()).count()
