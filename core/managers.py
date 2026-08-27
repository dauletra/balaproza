"""QuerySet'ы моделей: выдача, выраженная там, где она исполняется.

Здесь лежит то, что раньше было приватными функциями `queries/*`
(`_reading_effort`, `catalog_base`, `_list_base`, `_base`, `_accepting_q`) и
потому было доступно только внутри своего модуля. Разница не в размере файла:
цепочка `Story.objects.public().for_card()` **комбинируется** — её можно
продолжить фильтром, посчитать `.count()` и нарезать на странице, — а результат
функции, отдававшей готовый список, продолжить было нечем.

Аннотации живут тоже здесь, и это единственный способ починить их скрытый
контракт: свойства модели (`Story.chapters`, `read_minutes`, `badges`,
`has_chapters`) читают аннотацию выдачи и без неё уходят в запрос на каждую
строку. Пока аннотацию ставила приватная функция, «поставить» её означало
«вспомнить»; теперь она приезжает вместе с выдачей.

Модели импортируются внутри методов: `models.py` подключает этот модуль, и
верхнеуровневый импорт был бы циклом. К моменту вызова приложение загружено.
"""

from django.db.models import (
    Count,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce, Lower
from django.utils import timezone

from .domain.catalog import AUDIENCE_ORDER, NEW_AUTHOR_FOLLOWERS, PUBLIC_STATUSES

# Знаков в минуту: темп, комфортный для казахской прозы. То же число, что в
# `Story.read_minutes`, в двух видах — одна форма нужна объекту, вторая базе.
CHARS_PER_MINUTE = 900


def chapter_count_subquery(story_ref: str = 'pk'):
    """Сколько частей у работы — подзапросом, для аннотации `chapter_count`.

    `story_ref` — чем внешняя выдача ссылается на произведение. По умолчанию
    это сама работа; выдачам, где строка **про** работу (полка библиотеки,
    прогресс чтения), передаётся `'story'`, и число едет с их собственной
    строкой, не добавляя запроса.

    Подзапросом, а не `Count` по join, — по той же причине, что и объём: фильтр
    по тегам размножил бы строки и посчитал каждую главу столько раз, сколько у
    работы тегов.
    """
    from .models import Chapter

    return Coalesce(
        Subquery(
            Chapter.objects.filter(story=OuterRef(story_ref)).values('story')
            .annotate(n=Count('pk')).values('n')[:1],
            output_field=IntegerField(),
        ),
        Value(0),
    )


class StoryQuerySet(QuerySet):
    """Произведения: публичность, карточка, объём чтения, порядок."""

    def public(self):
        """Только то, что видит читатель (DEC-23, BR-10a).

        По `PUBLIC_STATUSES`, а не по литералу `'Published'`: после DEC-37
        публичный сериал носит `Completed` или `OnProcess`, и сравнение со
        строкой молча выкидывает из выдачи все сериалы, отдавая при этом 200.
        """
        return self.filter(status__in=PUBLIC_STATUSES)

    def for_card(self):
        """Всё, что спрашивает карточка: автор, жанры, теги.

        Не оптимизация, а условие работоспособности: без этого страница из
        двадцати карточек делает под сотню запросов.
        """
        return (self.select_related('author', 'primary_genre', 'secondary_genre')
                .prefetch_related('tags'))

    def with_reading_effort(self):
        """«Сколько это читать» и три знака карточки — одной выдачей.

        Объём берётся **подзапросом**, а не `Sum` по join: как только к выдаче
        добавится фильтр по тегам, join размножит строки, и сумма знаков
        вырастет во столько раз, сколько у работы тегов. Ошибка беззвучная —
        часть каталога просто уезжает не в свой фильтр.
        """
        from .models import Chapter, Submission

        written = Subquery(
            Chapter.objects.filter(story=OuterRef('pk')).values('story')
            .annotate(total=Sum('char_count')).values('total')[:1],
            output_field=IntegerField(),
        )
        return self.annotate(
            # Оценки «объявленных частей на 1800 знаков» здесь больше нет:
            # части, которых никто не написал, портал не обещает (DEC-51).
            effective_chars=Coalesce(written, Value(0)),
            chapter_count=chapter_count_subquery(),
        ).annotate(
            # Округление вверх целочисленным делением — тот же расчёт, что в
            # `Story.read_minutes`.
            read_minutes_db=(F('effective_chars') + Value(CHARS_PER_MINUTE - 1))
            / Value(CHARS_PER_MINUTE),
            # Участвует ли работа в **незавершённом** конкурсе — знак «Байқауға
            # қатысады» (DEC-45). Подхватывает `Story.badges`.
            in_open_contest=Exists(
                Submission.objects.filter(
                    story=OuterRef('pk'),
                    contest__results_on__gt=timezone.localdate())),
            # Есть ли хоть одна записанная глава — подхватывает
            # `Story.has_chapters`. Отдельно от объёма намеренно: глава с
            # пустым телом даёт ноль знаков, но работа уже не пустой черновик,
            # и полоса внимания звала бы автора писать то, что он начал.
            has_any_chapter=Exists(Chapter.objects.filter(story=OuterRef('pk'))),
        )

    def by_author(self, author):
        """Работы одного автора. Принимает `User` или ник строкой.

        Строка остаётся ради вызовов, у которых объекта на руках нет; там, где
        он есть, join по строке лишний.
        """
        if not author:
            return self.none()
        if isinstance(author, str):
            return self.filter(author__username=author)
        return self.filter(author=author)

    def sorted_by(self, sort: str):
        """Порядок выдачи.

        `pk` вторым ключом везде, где первый допускает ничью: без него Postgres
        вправе вернуть равные строки в любом порядке, и страница каталога
        перетасовывалась бы между запросами.
        """
        if sort == 'alphabet':
            return self.order_by(Lower('title'), 'pk')
        if sort == 'recent':
            return self.order_by('-created_at', '-pk')
        if sort == 'popularity':
            return self.order_by('-views', 'pk')
        return self.order_by('-recent_views', 'pk')

    def latest_edited(self):
        """«Что я трогал последним» — порядок авторского кабинета.

        `nulls_last` обязателен: Postgres при `DESC` ставит `NULL` **первыми**,
        и работы без даты правки уехали бы наверх вместо конца.
        """
        return self.order_by(F('updated_at').desc(nulls_last=True), 'pk')

    # ── Оси каталога ─────────────────────────────────────────────────────
    def with_audience(self, audience: str):
        """Ось «Жасың» — **накопительная** (DEC-38): читателю четырнадцати лет
        доступно и то, что помечено 10+. Безопасное направление сохраняется —
        младшая вилка старших отметок не видит."""
        if audience not in AUDIENCE_ORDER:
            return self
        allowed = AUDIENCE_ORDER[:AUDIENCE_ORDER.index(audience) + 1]
        return self.filter(audience__in=allowed)

    def with_length(self, length: str):
        """Ось «Оқу уақыты». Требует `with_reading_effort()` до себя."""
        if length == 'short':
            return self.filter(read_minutes_db__lte=10)
        if length == 'medium':
            return self.filter(read_minutes_db__gt=10, read_minutes_db__lte=30)
        if length == 'long':
            return self.filter(read_minutes_db__gt=30)
        return self

    def of_kind(self, kind: str):
        """Ось «Түрі» (DEC-37). Значения «любой сериал» нет намеренно."""
        if kind == 'single':
            return self.filter(format='single')
        if kind == 'done':
            return self.filter(format='serial', status='Completed')
        if kind == 'ongoing':
            return self.filter(format='serial', status='OnProcess')
        return self

    def with_badge(self, badge: str):
        """Ось «Белгі»: знак редакции хранится, знак конкурса выводится."""
        if badge == 'editorial':
            return self.filter(is_editorial_pick=True)
        if badge == 'contest':
            # Участие в **незавершённом** конкурсе, а не в идущем приёме:
            # работа, ушедшая к жюри, всё ещё в конкурсе.
            return self.filter(
                submissions__contest__results_on__gt=timezone.localdate()
            ).distinct()
        return self

    def by_author_tier(self, tier: str):
        if tier == 'new':
            return self.filter(author__followers__lt=NEW_AUTHOR_FOLLOWERS)
        return self

    def matching(self, query: str):
        """Поиск по названию и автору — подстрокой (`ILIKE`, GIN-индексы 0009)."""
        q = (query or '').strip()
        if not q:
            return self
        return self.filter(Q(title__icontains=q)
                           | Q(author__pen_name__icontains=q)
                           | Q(author__username__icontains=q)
                           | Q(author__name__icontains=q))

    def in_genre(self, slug: str):
        if not slug:
            return self
        return self.filter(Q(primary_genre__slug=slug)
                           | Q(secondary_genre__slug=slug))

    def with_tag(self, slug: str):
        """Оба условия — на одной связке (BR-TAG-07).

        У многозначного отношения это означает «тег с таким слагом И
        принятый», то есть непринятый слаг не находит ничего. Отдельным
        `.exists()` та же проверка стоила запроса на каждый вызов, а страница
        тега зовёт выдачу семь раз — сама плюс счётчик каждого пресета.
        """
        if not slug:
            return self
        return self.filter(tags__slug=slug, tags__status='accepted')


class ContestQuerySet(QuerySet):
    """Конкурсы: число заявок и три календарных вопроса.

    Фазы выражены для базы теми же тремя датами, что и `Contest.phase`
    (DEC-45). Расходиться им нельзя: свойство отвечает на странице, эти условия
    — в выдаче, и разное «идёт ли приём» в двух местах читатель увидит сразу.
    """

    def with_counts(self):
        """Число заявок аннотацией — его подхватывает `Contest.submissions`.

        Без неё каждая карточка списка спрашивает своё `COUNT`: десять запросов
        на десять конкурсов, и растут они вместе с разделом.
        """
        return self.annotate(submission_count=Count('submission_set'))

    def for_card(self):
        """Конкурс для карточки списка: фаза, приз, победители.

        Номинации, этапы, жюри и условия карточка не показывает — тянуть их
        значит платить четыре запроса за то, чего на экране нет.
        """
        return self.with_counts().prefetch_related('grant_set__story')

    def full(self):
        """Конкурс со всем составом — для его собственной страницы."""
        return self.with_counts().prefetch_related(
            'award_set', 'stage_set', 'jury_set', 'condition_set',
            'grant_set__award', 'grant_set__story__author')

    def accepting(self):
        """Идёт приём работ — это и решает кнопку «Қатысу» (DEC-45)."""
        today = timezone.localdate()
        return self.filter(opens_on__lte=today, closes_on__gte=today)

    def unfinished(self):
        """Итоги ещё не объявлены. **Не то же самое, что `accepting`**: в
        судействе конкурс тоже не завершён, но подать в него уже нельзя."""
        return self.filter(results_on__gt=timezone.localdate())

    def finished(self):
        return self.filter(results_on__lte=timezone.localdate())
