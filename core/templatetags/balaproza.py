"""Шаблонные хелперы Balaproza.

Подключай в шаблоне через {% load balaproza %} — НО: filter `page_range`
автоматически доступен только если шаблон сам его load-ит. Pagination —
системный компонент, потому добавлю там {% load balaproza %} в начало.

**Подпись — работа этого модуля, а не модели.** Пятнадцать свойств
`*_label` / `*_line` / `*_relative` жили на моделях и делали ровно одно:
собирали строку для шаблона. Правило записи при этом всё равно лежало в
`domain/formatting`, а модель была передаточным звеном — и вместе с ней
`models.py` отвечал ещё и за то, как выглядит страница.

Ни один фильтр здесь не считает сам: время «сколько назад» приходит из
`domain.formatting`, фраза конкурса — из `domain.contests`. Фильтр только
достаёт из объекта то, что нужно функции.
"""

from datetime import datetime, timedelta

from django import template
from django.utils import timezone

from core.domain.contests import CONTEST_PHASE_LABELS
from core.domain.contests import eligibility_line as contest_eligibility_line
from core.domain.contests import timing_line as contest_timing_line
from core.domain.formatting import kk_ago, kk_date, kk_period, kk_updated, spaced_number
from core.domain.notifications import MODERATION_OUTCOME_LABELS

register = template.Library()


@register.filter(name="compact_count")
def compact_count(value):
    """Компактный счётчик для карточек: 840 → 840, 8920 → 8,9 мың, 12482 → 12 мың.

    На мобильном карточка узкая (138px), полное число просмотров съедает строку
    с автором. Разделитель дробной части — запятая (казахская типографика).

    Ветка выбирается по **округлённому** значению, а не по сырому `n`. Раньше
    9970 попадало в ветку с десятичной (9970 < 10000), округлялось до
    «10,0 мың» и вставало в каталоге рядом с «10 мың» у 10000 — одно и то же
    число в двух формах на одном экране.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return value

    if n < 1000:
        return str(n)

    k = n / 1000
    if round(k, 1) < 10:
        return f"{k:.1f}".replace('.', ',') + " мың"
    # Округление, а не `n // 1000`: усечение вернуло бы «9 мың» ровно для тех
    # значений (9950-9999), ради которых ветка и выбирается по округлённому.
    return f"{round(k)} мың"


@register.filter(name="spaced")
def spaced(value):
    """Разряды через неразрывный пробел: 500000 → 500 000.

    Нужен для сумм в тенге: `stringformat:"d"` выводил «500000» сплошняком.

    Сама разрядка живёт в `core.domain.formatting.spaced_number`: те же
    числа собираются и на стороне данных — в подсказках чек-листа подачи, —
    а два места, описывающих одну форму записи, однажды разойдутся.
    """
    return spaced_number(value)


@register.filter(name="belongs_to")
def belongs_to(comment, username):
    """Свой ли это комментарий — для набора пунктов меню (BR-33).

    Фильтр, а не вычисление во view: комментарии вложены (BR-30), и view
    пришлось бы разворачивать нити в плоскую структуру только ради одного
    булева поля. Логика владения живёт в `StoryComment.belongs_to`.
    """
    checker = getattr(comment, "belongs_to", None)
    return bool(checker and checker(username or ""))


@register.filter(name="page_range")
def page_range(total, current):
    """Список номеров страниц для пагинации.
    0 в результате означает «…» (gap).

    Логика:
      total <= 7              → [1..total]
      current близко к началу → [1,2,3,4,5,0,total]
      current близко к концу  → [1,0,total-4,...,total]
      иначе                   → [1,0,current-1,current,current+1,0,total]
    """
    try:
        total = int(total)
        current = int(current)
    except (TypeError, ValueError):
        return []

    if total <= 7:
        return list(range(1, total + 1))

    if current <= 4:
        return [1, 2, 3, 4, 5, 0, total]
    if current >= total - 3:
        return [1, 0, total - 4, total - 3, total - 2, total - 1, total]
    return [1, 0, current - 1, current, current + 1, 0, total]


# ───────────────────────────── Время ──────────────────────────────────────

def _elapsed(value) -> timedelta:
    """Сколько прошло. Момент считается по часам, дата — по календарю.

    Разница не косметическая: `submitted_on` и `added_on` — это дни без
    времени суток, и вычитать из них `now()` значит получить «вчера» в
    полночь того же дня.
    """
    if isinstance(value, datetime):
        return timezone.now() - value
    return timedelta(days=(timezone.localdate() - value).days)


@register.filter(name="ago")
def ago(value):
    """«45 мин бұрын», «2 сағат бұрын», «3 күн бұрын» — из момента.

    Одна подпись на комментарий, уведомление и заявку: до этого каждая из
    трёх моделей звала `kk_ago` по-своему, и уведомление, в отличие от
    комментария, теряло минуты — свежее событие называлось «бүгін».
    """
    if not value:
        return ""
    delta = _elapsed(value)
    return kk_ago(delta.days, delta.seconds // 3600,
                  (delta.seconds % 3600) // 60)


@register.filter(name="since")
def since(value):
    """«Когда трогали» — лесенка с неделями (`kk_updated`).

    Отдельно от `ago` намеренно: у своей работы и закладки неделя и есть
    единица счёта, у события — нет (см. `domain/formatting`).
    """
    if not value:
        return ""
    return kk_updated(_elapsed(value).days)


@register.filter(name="short_date")
def short_date(value):
    """«5 жел» — дата конкурса в короткой форме."""
    return kk_date(value) if value else ""


@register.filter(name="period")
def period(stage):
    """Срок этапа конкурса; однодневный — просто дата."""
    return kk_period(stage.starts, stage.ends) if stage else ""


# ──────────────────────── Подписи предметной области ──────────────────────

@register.filter(name="format_badge")
def format_badge(story):
    """Знак формата на карточке: «Бір оқылым» или «Серия» (DEC-28)."""
    return "Бір оқылым" if story.is_single else "Серия"


@register.filter(name="reading_meta")
def reading_meta(story):
    """Чем измеряется работа: одночастная — минутами, сериал — частями."""
    if story.is_single:
        return f"{story.read_minutes} минут оқу"
    return f"{story.chapters} бөлім"


@register.filter(name="phase_label")
def phase_label(contest):
    """Фаза словом — из реестра `CONTEST_PHASE_LABELS` (BR-40)."""
    return CONTEST_PHASE_LABELS[contest.phase] if contest else ""


@register.filter(name="timing_line")
def timing_line(contest):
    """«Что дальше и когда» — правило живёт в `domain.contests`.

    Пустой конкурс здесь законен: уведомление ссылается на него только у
    одного из шести видов, а шаблон перебирает все шесть.
    """
    if not contest:
        return ""
    return contest_timing_line(contest.phase, contest.opens_on,
                               contest.closes_on, contest.results_on)


@register.filter(name="eligibility_line")
def eligibility_line(contest):
    """Возрастное требование словами (BR-48)."""
    if not contest:
        return ""
    return contest_eligibility_line(contest.min_age, contest.max_age)


@register.filter(name="outcome_label")
def outcome_label(notification):
    """Подпись исхода модерации — из реестра, а не из шаблона (BR-72b).

    Лучше пусто, чем чужая подпись: незнакомый исход не называется никак.
    """
    return MODERATION_OUTCOME_LABELS.get(notification.outcome, "")
