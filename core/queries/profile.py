"""Награды, подписки, уведомления и витринные счётчики портала.

Знаков два класса, и разница в источнике факта: системный (`AWARDS`)
вычисляется из данных (BR-ACH-01), награда конкурса присуждается жюри и
потому хранится присуждением (DEC-46).

Рейтинга здесь нет и не будет (DEC-41): знак говорит «ты сделал»,
рейтинг — «ты хуже вон того», и аудитории 14-18 второе не нужно.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Callable

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from ..domain.awards import READ_TIER_ART, READ_TIERS, next_tier_for, tier_for
from ..domain.catalog import BADGE_LABELS, PUBLIC_STATUSES
from ..domain.notifications import NOTIF_BUCKETS
from ..models import AwardGrant, Follow, Notification, User


# ── Подписки (FR-PROF-10, BR-75) ─────────────────────────────────────────
def is_following(me, them) -> bool:
    """Подписан ли `me` на `them`. Гость (`None`) не подписан ни на кого."""
    return (me is not None and them is not None
            and Follow.objects.filter(follower=me, following=them).exists())


def toggle_follow(follower, following) -> bool:
    """Подписка на автора — toggle (FR-PROF-04). Возвращает новое состояние.

    `User.followers` пересчитывается по строкам, а не сдвигается на
    единицу: сдвиг однажды разъезжается и остаётся неверным навсегда. На
    себя не подписываются — это держит `CheckConstraint` в базе.
    """
    if follower.pk == following.pk:
        return False
    with transaction.atomic():
        link = Follow.objects.filter(follower=follower, following=following).first()
        if link is None:
            Follow.objects.create(follower=follower, following=following)
            now_following = True
        else:
            link.delete()
            now_following = False
        User.objects.filter(pk=following.pk).update(
            followers=Follow.objects.filter(following=following).count())
    return now_following


def followers_of(user):
    if user is None:
        return User.objects.none()
    return with_works(User.objects.filter(following_set__following=user)
                      .order_by('username'))


def following_of(user):
    if user is None:
        return User.objects.none()
    return with_works(User.objects.filter(follower_set__follower=user)
                      .order_by('username'))


def followers_count_of(user) -> int:
    """Сколько человек подписано на автора. Отдельно от `followers_of`:
    страница подписок показывает два сегмента, а открывает один, и
    соседнему нужно число, а не список имён со счётчиком работ у каждого."""
    return Follow.objects.filter(following=user).count()


def following_count_of(user) -> int:
    """Сколько людей читает сам автор. Пара к `followers_count_of`."""
    return Follow.objects.filter(follower=user).count()


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
    """Сохранить свой профиль (FR-PROF-01). `age`/`gender` — самодекларация
    (DEC-24); пустой `avatar` значит «не меняем»: автор не переизбирает файл
    при каждом сохранении."""
    user.pen_name = pen_name
    user.name = name
    user.bio = bio
    user.age = age
    user.gender = gender
    if avatar:
        user.avatar = avatar
    user.save()


def new_authors(limit: int = 4):
    """«Жаңа авторлар» для главной — кто пришёл на портал последним.

    По дате прихода, а не по числу подписчиков (DEC-57): подросток должен
    видеть, что здесь пишут такие же начинающие, а мало подписчиков бывает
    и у того, кто пишет второй год. Порядок, а не окно `NEW_AUTHOR_DAYS`,
    как у оси каталога: ряд на главной обязан быть непустым, и в тихий
    месяц «последние четверо» честнее, чем пустое место.
    """
    return with_works(User.objects.order_by('-date_joined', 'username'))[:limit]


def portal_stats(*, stories, genres) -> dict:
    """Счётчики масштаба в хиро гостя (FR-HOME-01), по самим данным.

    Два числа из трёх приходят от страницы: она держит и список публичных
    работ, и полосу жанров целиком, и `COUNT` по тем же строкам был бы
    вторым обращением за тем, что уже в памяти. Считать здесь остаётся
    только авторов — их страница не перечисляет.
    """
    return {
        'stories': len(stories),
        'authors': User.objects.count(),
        'genres':  len(genres),
    }


# ── Прочтения и ступени ──────────────────────────────────────────────────
def reads_total(user) -> int:
    """Сколько раз прочитали автора — по публичным работам (BR-73). Из
    снимка на объекте: отдельный `SUM` по тем же строкам — ещё один запрос.
    """
    return user.reads if user is not None else 0


def read_tier(user):
    """Высшая взятая ступень. В публичный ряд идёт только она: «Мың» и
    «Он мың» рядом говорят одно и то же."""
    return tier_for(reads_total(user))


def read_ladder(user) -> list:
    """Весь путь по ступеням — для своей статистики (FR-PROF-08). Публичный
    ряд показывает одну; здесь видно, что дальше."""
    total = reads_total(user)
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

    Условие (`earned`) лежит рядом с наградой, а не в отдельном списке «как
    получить»: два описания одного правила однажды разойдутся.
    """

    key: str
    label: str
    art: str        # слаг иллюстрации в `components/awards/_sprite.html`
    tier: str       # металл постамента (BR-ACH-02)
    hint: str       # что сделать, чтобы получить
    earned: Callable[..., bool]

    def as_dict(self) -> dict:
        return {'key': self.key, 'label': self.label,
                'art': self.art, 'tier': self.tier}


# Порядок — от первого шага к редкому.
AWARDS = (
    Award('first_publication', 'Алғашқы жарияланым', 'first-publication',
          'bronze', 'Бірінші шығармаңды жарияла',
          lambda u: bool(u.public_works)),
    Award('contest_participant', 'Байқауға қатысты', 'contest-participant',
          'bronze', 'Кез келген байқауға өтінім жібер',
          lambda u: bool(u.own_submissions)),
    # Одиночный рассказ сюда не считается: он «дописан» в момент публикации
    # (BR-10a, BR-ACH-04), а награда — за доведённое до конца длинное.
    Award('finished_serial', 'Сериалды аяқтады', 'finished-serial',
          'silver', 'Көп бөлімді шығармаңды аяқта',
          lambda u: any(s.status == 'Completed' and not s.is_single
                        for s in u.authored)),
    Award('contest_accepted', 'Байқауға қабылданды', 'contest-accepted',
          'silver', 'Өтінімің қазылар алқасынан өтсін',
          lambda u: any(s.status == 'accepted' for s in u.own_submissions)),
    # Системного «Байқау жеңімпазы» здесь нет (DEC-46): награда конкретного
    # конкурса называет номинацию, год и работу, а общий знак — только факт.
    Award('editorial_choice', BADGE_LABELS['editorial'], 'editorial-choice',
          'gold', 'Редакция шығармаңды таңдасын',
          lambda u: any(s.is_editorial_pick for s in u.public_works)),
)


def award_catalog(user) -> list:
    """Все знаки с отметкой «взят» — для своей статистики (FR-PROF-08). Тот
    же реестр, что у публичного ряда: «что можно получить» не может
    разойтись с «что получено», потому что это один список."""
    out = []
    for a in AWARDS:
        # Список полный и у того, кто не взял ни одной: серая плитка
        # отвечает на «что дальше», ради чего раздел и заводился (BR-ACH-08).
        earned = bool(user is not None and a.earned(user))
        out.append({**a.as_dict(), 'hint': a.hint, 'earned': earned,
                    # Готовый флаг «обесцветить»: `{% include %}` не умеет `not`.
                    'dim': not earned})
    return out


def achievements_of(user) -> list:
    """Полученные знаки — публичный ряд (FR-PROF-06). В ряд идёт только
    высшая взятая ступень оқылым; пройденные видно в своей статистике."""
    if user is None:
        return []
    out = [a.as_dict() for a in AWARDS if a.earned(user)]
    tier = read_tier(user)
    if tier:
        art, metal = READ_TIER_ART[tier[0]]
        out.append({'key': 'reads', 'label': tier[1], 'art': art, 'tier': metal})
    return out


def contest_awards_of(user) -> list:
    """Награды конкурсов автора (DEC-46), свежие сверху. Работа называется
    только пока публична (BR-73); сама награда остаётся — она принадлежит
    автору, а не видимости текста."""
    if user is None:
        return []
    out = []
    for grant in (AwardGrant.objects.filter(story__author=user)
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
# Глубина ленты — семь дней, одним числом на группировку и на бейдж в
# шапке: бейдж, считающий шире ленты, посылает автора искать уведомление,
# которого нет.
FEED_DAYS = 7


def _feed_window_start():
    """Начало окна ленты: полночь того дня, который ещё показывается.

    Моментом, а не `__date` над колонкой: функция над полем отрезает
    индекс. Совпадает с `Notification.bucket` по построению.
    """
    day = timezone.localdate() - timedelta(days=FEED_DAYS)
    return timezone.make_aware(datetime.combine(day, time.min))


def notifications_for_user(user) -> dict:
    """Лента по группам: сегодня, вчера, на этой неделе. Старше недели
    событие не показывается — четвёртой группы в требовании нет."""
    grouped = {b: [] for b in NOTIF_BUCKETS}
    if user is None:
        return grouped
    # Окно режется в базе: у человека с двумя годами истории отбрасывать
    # лишнее в Python значит везти всю историю ради семи дней.
    rows = (Notification.objects
            .filter(user=user, created_at__gte=_feed_window_start())
            .select_related('actor', 'story', 'story__author', 'contest')
            .order_by('-created_at'))
    for n in rows:
        if n.bucket in grouped:
            grouped[n.bucket].append(n)
    return grouped


def mark_notification_read(user, pk):
    """Снять «непрочитано» с одного уведомления (BR-71); отдаёт его или None.
    `user` в фильтре — закрытая дверь: без него любой вошедший снимал бы
    метку с чужой ленты по прямому адресу."""
    notification = Notification.objects.filter(pk=pk, user=user).select_related(
        'actor', 'story', 'contest').first()
    if notification is not None and not notification.read:
        Notification.objects.filter(pk=notification.pk).update(read=True)
        notification.read = True
    return notification


def mark_all_notifications_read(user) -> int:
    """«Барлығын оқылды деп белгілеу»; отдаёт число снятых меток. Режется тем
    же окном, что и лента: снимать метку с того, чего читатель не видел
    (BR-70a), значит тихо стирать историю."""
    return Notification.objects.filter(
        user=user, read=False, created_at__gte=_feed_window_start()).update(read=True)


def unread_count_for_user(user) -> int:
    """Бейдж в шапке считает то же, что показывает страница: событие старше
    недели в ленту не попадает (BR-70a). Считает база — число зовёт
    контекст-процессор, то есть каждая страница у каждого вошедшего."""
    if user is None:
        return 0
    return Notification.objects.filter(
        user=user, read=False,
        created_at__gte=_feed_window_start()).count()
