"""Уведомления: лента автора.

Читающая половина — лента по группам, бейдж в шапке, снятие метки —
переехала сюда из `queries/profile.py` целиком, без единой правки: пока
уведомления только читались, они были придатком профиля, а писать их
предстоит из четырёх разделов сразу, и общий дом им нужен свой.

Чистый переезд; сами события встают рядом следующим заходом.
"""

from datetime import datetime, time, timedelta

from django.utils import timezone

from ..domain.notifications import NOTIF_BUCKETS
from ..models import Notification


# ── Лента (FR-NOTIF-01, BR-70a) ──────────────────────────────────────────
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
