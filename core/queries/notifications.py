"""Уведомления: лента автора и события, которые её наполняют.

Читающая половина (лента по группам, бейдж, снятие метки) переехала сюда
из `queries/profile.py` вместе с появлением пишущей: пока уведомления
только читались, они были придатком профиля, а теперь их пишут четыре
разных раздела — произведение, профиль, модерация и конкурсы, — и общий
дом им нужен свой.

**Событие создаётся там, где оно произошло**, а не сигналом, в отличие от
счётчиков в `core/counters.py`. Разница не в стиле: у счётчика источник
факта — строка в таблице, и сигнал видит ровно его; у уведомления источник
— человек и его действие, а строка знает только себя. Сигнал на
`StoryComment` видит, что комментарий появился, и не знает ни кому об этом
сказать (автору работы? автору ветки? обоим?), ни что делать с ответом на
свой же комментарий.

Почему это вообще писалось отдельным заходом: до него `Notification`
создавалась ровно в двух местах — `Story.apply_moderation` и
`Story.take_down`, — то есть работал один тип событий из шести. Остальные
пять существовали в демо-корпусе (`_corpus.py` раскладывает их одному
автору руками), поэтому в разработке лента выглядела полной, а на чистой
базе колокольчик звенел бы только на решения модератора: подписка не
приводила ни к чему, о комментарии автор не узнавал.
"""

from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from ..domain.notifications import (
    NOTIF_BUCKETS,
    PUSH_CATEGORIES,
    SUBMISSION_EVENTS,
    award_event,
    comment_quote,
    new_chapter_event,
    tag_rejected_event,
)
from ..models import Follow, Notification, Story, User


# ── Лента ────────────────────────────────────────────────────────────────
# Глубина ленты — семь дней, одним числом на группировку и на бейдж в
# шапке: бейдж, считающий шире ленты, посылает автора искать уведомление,
# которого нет.
FEED_DAYS = 7

# Сколько событие вообще живёт в базе. Лента показывает неделю, а таблица
# хранила всё с первого дня — и растёт она быстрее любой другой, кроме
# журнала оқылым: шесть типов событий на каждое действие портала, а
# журнал хотя бы чистится.
#
# Месяц, а не неделя: за пределами ленты строка ещё отвечает на «дошло ли
# вообще» (`pushed_at`), и запас в три недели стоит дёшево. Дальше не
# отвечает никто — ни лента, ни разбор доставки.
KEEP_DAYS = 30


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
    """Снять «непрочитано» с одного уведомления; отдаёт его или None.
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
    же окном, что и лента: снимать метку с того, чего читатель не видел,
 значит тихо стирать историю."""
    return Notification.objects.filter(
        user=user, read=False, created_at__gte=_feed_window_start()).update(read=True)


def unread_count_for_user(user) -> int:
    """Бейдж в шапке считает то же, что показывает страница: событие старше
    недели в ленту не попадает. Считает база — число зовёт
    контекст-процессор, то есть каждая страница у каждого вошедшего."""
    if user is None:
        return 0
    return Notification.objects.filter(
        user=user, read=False,
        created_at__gte=_feed_window_start()).count()


# ── События ──────────────────────────────────────────────────────────────

def _notify(user, kind: str, *, actor=None, story=None, contest=None,
            text: str = '', outcome: str = ''):
    """Одна дверь на все события: заводит строку — или молчит.

    Молчит в двух случаях, и оба нормальные.

    **Адресата нет.** Автор ветки мог удалить аккаунт, пока писался ответ;
    события без адресата не существует, и падать тут нечему.

    **Адресат сам это и сделал.** Свой комментарий под своей работой, своя
    реакция на свою главу — не события. Проверка стоит здесь, а не в
    каждом вызове: забыть её в одном месте значит показать автору ленту,
    где он разговаривает сам с собой.
    """
    if user is None:
        return None
    if actor is not None and actor.pk == user.pk:
        return None
    return Notification.objects.create(
        user=user, kind=kind, actor=actor, story=story, contest=contest,
        text=text, outcome=outcome)


def notify_comment(comment) -> list:
    """Комментарий или ответ на него.

    Адресатов бывает два: автор работы узнаёт про любой комментарий под
    ней, автор ветки — про ответ себе. Совпали (автор ответил в своей же
    работе) — уведомление одно: две одинаковые строки в ленте читаются как
    сбой, а не как два события.
    """
    story = comment.story
    targets = [story.author]
    if comment.parent_id:
        targets.append(comment.parent.author)

    seen, created = set(), []
    for target in targets:
        if target is None or target.pk in seen:
            continue
        seen.add(target.pk)
        note = _notify(target, 'comment', actor=comment.author, story=story,
                       text=comment_quote(comment.text))
        if note is not None:
            created.append(note)
    return created


# Сколько молчать после уведомления об отклике на ту же работу от того же
# читателя. Под каждой главой пять кнопок, и читатель сериала на сорок
# частей за вечер нажимает их сорок раз — без окна лента автора
# превратилась бы в поток, в котором не видно ни комментария, ни решения
# модератора. Сутки: «тебя читают» — это событие дня, а не минуты.
REACTION_QUIET_HOURS = 24


def notify_reaction(chapter, actor):
    """Отклик на главу. Адресат — автор работы, не главы:
    у главы своего автора нет.

    Работа берётся отдельным запросом, а не через `chapter.story`: тот же
    один запрос, но сразу с автором — иначе их два, а зовётся это из
    обработчика нажатия, где каждый лишний на счету.
    """
    story = Story.objects.select_related('author').filter(
        pk=chapter.story_id).first()
    if story is None:
        return None
    recently = Notification.objects.filter(
        user=story.author, kind='like', actor=actor, story=story,
        created_at__gte=timezone.now() - timedelta(hours=REACTION_QUIET_HOURS),
    ).exists()
    if recently:
        return None
    return _notify(story.author, 'like', actor=actor, story=story)


def notify_new_chapter(story, chapters: int = 1) -> int:
    """Подписчикам автора — что читать дальше. Отдаёт число разосланных.

    Зовётся из `Story.apply_moderation` и только на **впервые
    опубликованные** главы: одобренная правка уже стоящего у
    читателя текста — не новая часть, и звать за ней второй раз незачем.

    `bulk_create` здесь безопасен, в отличие от остальных массовых вставок
    проекта: единственная слепая зона `core/counters.py` — счётчики на
    сигналах, а у `Notification` их нет. Поимённое создание стоило бы
    запроса на подписчика, то есть цена рассылки росла бы с популярностью
    автора — ровно наоборот тому, как надо.
    """
    follower_ids = list(Follow.objects
                        .filter(following_id=story.author_id)
                        .values_list('follower_id', flat=True))
    if not follower_ids:
        return 0
    text = new_chapter_event(chapters)
    Notification.objects.bulk_create([
        Notification(user_id=follower_id, kind='new_chapter',
                     actor_id=story.author_id, story=story, text=text)
        for follower_id in follower_ids
    ])
    return len(follower_ids)


def notify_follow(follower, following):
    """Новый подписчик. Только на подписку: об отписке автору
    не сообщают — это не событие, а его отсутствие."""
    return _notify(following, 'follower', actor=follower)


def notify_submission_decided(submission):
    """Решение по заявке на конкурс.

    Только окончательное: «қаралуда» — состояние, с которого заявка
    начинается, и сообщать о нём нечего. Актора нет — решение принимает
    жюри от имени конкурса, а не человек от своего имени, как и у решения
    модератора.
    """
    text = SUBMISSION_EVENTS.get(submission.status)
    if not text:
        return None
    return _notify(submission.author, 'contest', contest=submission.contest,
                   text=text)


def notify_tag_rejected(story, tag_name: str, reason: str):
    """Тег снят с работы модератором.

    Без актора, как и решение по публикации: платформа не подписывает
    свои решения именем модератора. Ведёт в баптаулар — туда, где автор
    может поставить другой тег, а не в кабинет вообще.
    """
    return _notify(story.author, 'tag', story=story,
                   text=tag_rejected_event(tag_name, reason))


def notify_award_granted(grant):
    """Победа в номинации. Отдельно от решения по заявке: победа
    не статус документа, а акт жюри, и приходит она присуждением."""
    return _notify(grant.story.author, 'contest', contest=grant.contest,
                   text=award_event(grant.award.title))


# ── Очередь доставки в Telegram ──────────────────────────────────────────
#
# Очередь — это сами уведомления без отметки об отправке, а не отдельная
# таблица: вторая повторяла бы первую целиком.
#
# Почему доставка вообще отложенная, а не прямо в `_notify`: ходить в
# чужой сервис внутри запроса пользователя нельзя. Telegram, отвечающий
# три секунды, — это форма комментария, отвечающая три секунды; Telegram
# упавший — это форма, не отправляющая комментарий вовсе. Событие
# записывается всегда, доставка догоняет.

# Насколько старое ещё стоит слать. Команда ходит раз в минуту; час —
# это запас на её остановку, перезапуск сервера, недоступный Telegram.
# Старше — не шлём совсем: «главу одобрили» через сутки после события
# приходит человеку, который давно всё увидел на сайте, и выглядит
# сбоем. Заодно это и естественный конец очереди: просроченное уходит из
# выборки само, без отдельного состояния «уже не будем».
PUSH_MAX_AGE_HOURS = 1

# Сколько строк забирает один запуск. Bot API держит около тридцати
# сообщений в секунду; двести за проход с паузой между ними укладываются
# заведомо, а хвост подберёт следующая минута.
PUSH_BATCH = 200


def _chosen_kinds() -> Q:
    """«Этот вид этому человеку ещё нужен» — условием для базы.

    Собирается из `PUSH_CATEGORIES`, а не переписывается здесь списком:
    вторая копия разошлась бы с первой молча, и это худший из возможных
    отказов — человек снял галку, а сообщения идут.
    """
    chosen = Q()
    for category in PUSH_CATEGORIES:
        chosen |= Q(kind__in=category.kinds,
                    **{f'user__{category.field}': True})
    return chosen


def pending_pushes(limit: int = PUSH_BATCH) -> list:
    """Что осталось доставить, старое первым.

    Порядок хронологический: события приходят человеку в том же порядке,
    в каком случились, — иначе решение модератора обгоняет комментарий,
    на который оно отвечает.

    Три условия на адресата: есть куда слать (`telegram_id`), канал жив
    (`telegram_push`) и этот вид событий он не выключал. Все три в
    запросе, а не в команде: иначе пачка из двухсот строк целиком
    состояла бы из тех, кому слать не надо.
    """
    edge = timezone.now() - timedelta(hours=PUSH_MAX_AGE_HOURS)
    return list(Notification.objects
                .filter(pushed_at__isnull=True, created_at__gte=edge,
                        user__telegram_id__isnull=False,
                        user__telegram_push=True)
                .filter(_chosen_kinds())
                .select_related('user', 'actor', 'story', 'contest')
                .order_by('created_at', 'pk')[:limit])


def push_settings_of(user) -> list:
    """Три переключателя с текущим состоянием — для формы профиля.

    Данными, а не разметкой: подписи и состав семей живут в домене, и
    шаблон их перечислять не должен — иначе новая семья событий
    появляется в очереди и не появляется в настройках.
    """
    if user is None:
        return []
    return [{'name': c.field, 'label': c.label, 'hint': c.hint,
             'checked': getattr(user, c.field)}
            for c in PUSH_CATEGORIES]


def mark_pushed(notifications) -> int:
    """Отметить доставленным — одним запросом на всю пачку.

    Отметка ставится и на то, что доставить **не удастся никогда**
    (адресат закрыл бота): иначе эти строки крутились бы в очереди до
    истечения срока, отнимая место у живых.
    """
    ids = [n.pk for n in notifications]
    if not ids:
        return 0
    return Notification.objects.filter(pk__in=ids).update(
        pushed_at=timezone.now())


def disable_push(user) -> None:
    """Перестать слать этому человеку (`telegram_push`).

    Зовётся, когда Telegram ответил отказом, после которого повторять
    бессмысленно: бота закрыли, аккаунт удалён, право писать не дано.
    Уведомления на сайте при этом остаются — выключен канал, а не
    события.
    """
    User.objects.filter(pk=user.pk).update(telegram_push=False)
    user.telegram_push = False


def prune_notifications() -> int:
    """Удалить события старше `KEEP_DAYS`. Отдаёт, сколько удалено.

    Суточная уборка, как `recount_views` у журнала оқылым, и по той же
    причине: без неё таблица растёт линейно с возрастом портала, а
    показывается из неё неделя.

    Дата, а не «оставить последние N на человека»: у активного автора
    неделя это десятки событий, у читателя — ноль, и порог по числу
    означал бы разную глубину истории у разных людей без всякой причины.
    """
    edge = timezone.now() - timedelta(days=KEEP_DAYS)
    removed, _ = Notification.objects.filter(created_at__lt=edge).delete()
    return removed
