"""Конкурс и его состав: условия, этапы, жюри, номинации, награды, заявки."""

from functools import cached_property

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from ..domain.contests import (
    AI_DECLARATION_LABELS,
    AI_DECLARATIONS,
    SUBMISSION_STATUS_LABELS,
    SUBMISSION_STATUSES,
)
from ..domain.formatting import kk_period
from ..managers import ContestQuerySet, from_annotation
from ..uploads import _ext, validate_raster_image


def contest_poster_path(instance, filename):
    return f'contests/{instance.slug}{_ext(filename)}'


def award_image_path(instance, filename):
    """`awards/<contest>/<award>.<ext>`. Конкурс в пути обязателен:
    «бас-жүлде» есть у каждого второго, и эмблемы затирали бы друг друга."""
    return f'awards/{instance.contest.slug}/{instance.slug}{_ext(filename)}'


class Contest(models.Model):
    """Конкурс. Заводит админ; всё, что можно вывести, выводится.

    Хранятся **три даты** — открытие приёма, дедлайн, итоги; из них
    считаются фаза, отсчёт дней и год. Колонок `status`, `days_left`,
    `year`, `submissions` нет: они протухают назавтра.

    Списки состава — `cached_property`: страница спрашивает их по нескольку
    раз, а экземпляр живёт один запрос.
    """

    objects = ContestQuerySet.as_manager()

    slug = models.SlugField('slug', max_length=64, unique=True)
    name = models.CharField('атауы', max_length=120)
    subtitle = models.CharField('санаты', max_length=160, blank=True)

    opens_on = models.DateField('қабылдау басталады')
    closes_on = models.DateField('қабылдау жабылады')
    results_on = models.DateField('қорытынды жарияланады')

    # None — конкурс без денежного приза. Ноль означал бы «приз есть, но
    # он нулевой», а это разные вещи.
    prize_kzt = models.PositiveIntegerField('сыйлық (₸)', null=True, blank=True)
    # Афиша грузится админом. Пусто — платформа рисует свою.
    poster = models.FileField('афиша', upload_to=contest_poster_path,
                              blank=True, max_length=200,
                              validators=[validate_raster_image])
    # Семейство повторяющегося конкурса; пусто — разовый. Слагом,
    # а не совпадением имён: у выпусков имена расходятся.
    series = models.SlugField('серия', max_length=64, blank=True)
    description = models.TextField('сипаттамасы', blank=True)

    # Пороги объёма для подачи. У конкурса свои — подпись чек-листа
    # берёт числа отсюда, а не вписывает литералом.
    min_chars = models.PositiveIntegerField('ең аз көлемі', default=5_000)
    max_chars = models.PositiveIntegerField('ең көп көлемі', default=15_000)
    # Возрастная вилка **этого конкурса**. Любая граница может
    # отсутствовать, обе — тоже: своего ценза у платформы нет.
    min_age = models.PositiveSmallIntegerField('ең кіші жас', null=True, blank=True)
    max_age = models.PositiveSmallIntegerField('ең үлкен жас', null=True, blank=True)

    class Meta:
        ordering = ('-results_on',)
        verbose_name = 'байқау'
        verbose_name_plural = 'байқаулар'
        constraints = [
            # Инвариант дат: приём открывается не позже дедлайна, итоги —
            # строго после него. Нарушение делает фазу невыводимой.
            # Сообщения — редактору в форме админки: без них он читал бы
            # имя ограничения по-английски.
            models.CheckConstraint(
                condition=models.Q(opens_on__lte=models.F('closes_on')),
                name='contest_opens_before_it_closes',
                violation_error_message='Қабылдау басталмай тұрып жабыла '
                                        'алмайды.'),
            models.CheckConstraint(
                condition=models.Q(closes_on__lt=models.F('results_on')),
                name='contest_results_after_it_closes',
                violation_error_message='Қорытынды қабылдау жабылғаннан '
                                        'кейін ғана жарияланады.'),
        ]

    def __str__(self):
        return self.name

    # ── Списки состава ───────────────────────────────────────────────────
    @cached_property
    def awards(self) -> list:
        return list(self.award_set.all())

    @cached_property
    def timeline(self) -> list:
        return list(self.stage_set.all())

    @cached_property
    def jury(self) -> list:
        return list(self.jury_set.all())

    @cached_property
    def conditions(self) -> list:
        """Условия именно этого конкурса, строками. Общие для всех живут
        в `common_rules` и здесь не повторяются."""
        return [c.text for c in self.condition_set.all()]

    # ── Фаза и сроки ────────────────────────────────────────────
    @property
    def phase(self) -> str:
        """Одна из `CONTEST_PHASES`; единственный источник — три даты.
        «Қазылар қарауда» отдельная: между дедлайном и итогами конкурс не
        «активен» и ещё не «завершён»."""
        today = timezone.localdate()
        if today < self.opens_on:
            return 'upcoming'
        if today <= self.closes_on:
            return 'accepting'
        if today < self.results_on:
            return 'judging'
        return 'finished'

    @property
    def is_accepting(self) -> bool:
        """Можно ли подать работу. Именно это, а не «конкурс активен»,
        решает судьбу кнопки «Қатысу»."""
        return self.phase == 'accepting'

    @property
    def is_finished(self) -> bool:
        return self.phase == 'finished'

    @property
    def days_left(self):
        return (self.closes_on - timezone.localdate()).days if self.is_accepting else None

    @property
    def days_until_open(self):
        if self.phase != 'upcoming':
            return None
        return (self.opens_on - timezone.localdate()).days

    @property
    def year(self) -> int:
        """Год проведения — год объявления итогов. Нужен конкурсной
        биографии автора: «1 жыл бұрын» устаревает каждый день."""
        return self.results_on.year

    # ── Производное от состава ───────────────────────────────────────────
    @property
    def submissions(self) -> int:
        """Число поданных работ — по заявкам (аннотация `submission_count`)."""
        return from_annotation(self, 'submission_count',
                               self.submission_set.count)

    @cached_property
    def awards_by_slug(self) -> dict:
        return {a.slug: a for a in self.awards}

    @cached_property
    def grants(self) -> list:
        """Присуждения этого конкурса, в порядке номинаций."""
        return list(self.grant_set.all())

    @cached_property
    def winner_stories(self) -> list:
        """Произведения-победители, в порядке номинаций, без повторов.
        Автор выводится через работу, вторым полем не хранится."""
        seen, out = set(), []
        for grant in self.grants:
            if grant.story_id not in seen:
                seen.add(grant.story_id)
                out.append(grant.story)
        return out

    @cached_property
    def winners(self) -> tuple:
        """Слаги победителей — производное от присуждений, не хранимый кортеж."""
        return tuple(s.slug for s in self.winner_stories)

    @cached_property
    def other_editions(self) -> list:
        """Другие выпуски того же семейства, свежие сверху. Без них
        завершённый конкурс — тупик, хотя приём в выпуск этого года может
        идти прямо сейчас."""
        if not self.series:
            return []
        return list(Contest.objects.for_card()
                    .filter(series=self.series)
                    .exclude(pk=self.pk).order_by('-results_on'))

    @cached_property
    def current_stage(self):
        """Этап, идущий сейчас. Нужен рейлу — «что происходит
        прямо сейчас» единственное, чего нет в хиро."""
        return next((s for s in self.timeline if s.state == 'active'), None)

    @cached_property
    def next_stage(self):
        return next((s for s in self.timeline if s.state == 'upcoming'), None)


class ContestCondition(models.Model):
    """Условие конкретного конкурса, одной строкой: только то, чем он
    отличается. Общие правила живут одним списком в `common_rules` и в
    каждый конкурс не переписываются."""

    contest = models.ForeignKey(Contest, verbose_name='байқау',
                                on_delete=models.CASCADE,
                                related_name='condition_set')
    text = models.CharField('шарт', max_length=200)
    position = models.PositiveSmallIntegerField('реті', default=0)

    class Meta:
        ordering = ('position', 'pk')
        verbose_name = 'байқау шарты'
        verbose_name_plural = 'байқау шарттары'

    def __str__(self):
        return self.text


class TimelineStage(models.Model):
    """Этап конкурса. Хранятся даты, состояние выводится: проставленное
    руками, оно устаревает молча."""

    contest = models.ForeignKey(Contest, verbose_name='байқау',
                                on_delete=models.CASCADE,
                                related_name='stage_set')
    label = models.CharField('атауы', max_length=80)
    starts = models.DateField('басталуы')
    # Однодневный этап задаётся равными датами — «15 жел» вместо диапазона.
    ends = models.DateField('аяқталуы')
    position = models.PositiveSmallIntegerField('реті', default=0)

    class Meta:
        ordering = ('position', 'starts')
        verbose_name = 'байқау кезеңі'
        verbose_name_plural = 'байқау кезеңдері'

    def __str__(self):
        return f'{self.label} ({kk_period(self.starts, self.ends)})'

    def clean(self):
        """Этап, кончившийся раньше начала, рисуется на таймлайне конкурса
        перевёрнутым отрезком, а `state` у него сразу «прошёл»."""
        if self.starts and self.ends and self.ends < self.starts:
            raise ValidationError(
                {'ends': 'Кезең басталмай тұрып аяқтала алмайды.'})

    @property
    def state(self) -> str:
        today = timezone.localdate()
        if today > self.ends:
            return 'done'
        if today >= self.starts:
            return 'active'
        return 'upcoming'


class JuryMember(models.Model):
    """Член жюри конкурса. Имя и роль — то, что видит участник."""

    contest = models.ForeignKey(Contest, verbose_name='байқау',
                                on_delete=models.CASCADE,
                                related_name='jury_set')
    name = models.CharField('аты-жөні', max_length=120)
    role = models.CharField('рөлі', max_length=40)
    position = models.PositiveSmallIntegerField('реті', default=0)

    class Meta:
        ordering = ('position', 'pk')
        verbose_name = 'қазылар алқасының мүшесі'
        verbose_name_plural = 'қазылар алқасы'

    def __str__(self):
        return f'{self.name} — {self.role}'


class ContestAward(models.Model):
    """Номинация конкурса и её награда. Общего реестра
    номинаций нет и быть не может — он и есть то, чем один конкурс
    отличается от другого. Раму эмблемы рисует платформа: иначе через
    десять конкурсов ряд наград станет коллекцией чужих JPEG."""

    contest = models.ForeignKey(Contest, verbose_name='байқау',
                                on_delete=models.CASCADE,
                                related_name='award_set')
    slug = models.SlugField('slug', max_length=48)
    title = models.CharField('атауы', max_length=80)
    image = models.FileField('эмблема', upload_to=award_image_path,
                             blank=True, max_length=200,
                             validators=[validate_raster_image])
    description = models.CharField('сипаттамасы', max_length=200, blank=True)
    position = models.PositiveSmallIntegerField('реті', default=0)

    class Meta:
        ordering = ('position', 'pk')
        constraints = [
            models.UniqueConstraint(fields=('contest', 'slug'),
                                    name='unique_award_slug_per_contest'),
        ]
        verbose_name = 'байқау номинациясы'
        verbose_name_plural = 'байқау номинациялары'

    def __str__(self):
        return f'{self.contest.slug} · {self.title}'


class AwardGrant(models.Model):
    """Присуждение: кому и за что вручена награда конкурса.
    Хранится сам акт — решение жюри из данных не вычисляется, и этим
    конкурсные награды отличаются от системных знаков. Автор не
    хранится: он у работы."""

    contest = models.ForeignKey(Contest, verbose_name='байқау',
                                on_delete=models.CASCADE,
                                related_name='grant_set')
    award = models.ForeignKey(ContestAward, verbose_name='номинация',
                              on_delete=models.CASCADE,
                              related_name='grant_set')
    story = models.ForeignKey('core.Story', verbose_name='шығарма',
                              on_delete=models.CASCADE,
                              related_name='award_grants')
    note = models.CharField('түсініктеме', max_length=200, blank=True)

    class Meta:
        ordering = ('award__position', 'pk')
        constraints = [
            models.UniqueConstraint(fields=('contest', 'award'),
                                    name='unique_grant_per_award'),
        ]
        verbose_name = 'марапат'
        verbose_name_plural = 'марапаттар'

    def __str__(self):
        return f'{self.award.title} — {self.story.title}'

    def clean(self):
        """Награда вручается внутри одного конкурса и только допущенной
        работе. База этого не держит — связи три независимых внешних
        ключа, и выпадающие списки формы предлагают номинации всех
        конкурсов и все работы портала: опечатка в выборе дала бы победу в
        чужом конкурсе или работе, которая в нём не участвовала."""
        if not (self.contest_id and self.award_id and self.story_id):
            return
        if self.award.contest_id != self.contest_id:
            raise ValidationError(
                {'award': 'Бұл номинация басқа байқаудікі.'})
        if not Submission.objects.filter(
                contest_id=self.contest_id, story_id=self.story_id,
                status='accepted').exists():
            raise ValidationError(
                {'story': 'Бұл шығарма осы байқауға қабылданған өтінімдер '
                          'арасында жоқ.'})

    @property
    def author(self):
        return self.story.author


class Submission(models.Model):
    """Заявка автора на конкурс. Один автор — одна работа;
    ограничение базы, а не только формы: вторая заявка ломает счёт
    участников и конкурсную биографию."""

    STATUS_CHOICES = [(s, SUBMISSION_STATUS_LABELS[s])
                      for s in SUBMISSION_STATUSES]
    AI_DECLARATION_CHOICES = [(v, AI_DECLARATION_LABELS[v])
                              for v in AI_DECLARATIONS]

    contest = models.ForeignKey(Contest, verbose_name='байқау',
                                on_delete=models.CASCADE,
                                related_name='submission_set')
    author = models.ForeignKey('core.User', verbose_name='авторы',
                               on_delete=models.CASCADE,
                               related_name='submissions')
    story = models.ForeignKey('core.Story', verbose_name='шығарма',
                              on_delete=models.CASCADE,
                              related_name='submissions')
    submitted_on = models.DateField('берілген күні')
    status = models.CharField('күйі', max_length=16, choices=STATUS_CHOICES,
                              default='reviewing')
    # Личный кабинет автора его показывает, чужой профиль — никогда.
    note = models.CharField('қазылар пікірі', max_length=300, blank=True)
    # Ответы формы подачи: пишутся один раз, дальше видны
    # только жюри и модератору.
    ai_declaration = models.CharField('AI көмегі', max_length=8,
                                      choices=AI_DECLARATION_CHOICES,
                                      default='no')
    age_confirmed = models.BooleanField('жасын растады', default=False)
    rules_confirmed = models.BooleanField('ережені растады', default=False)

    class Meta:
        ordering = ('-submitted_on',)
        constraints = [
            models.UniqueConstraint(fields=('contest', 'author'),
                                    name='one_submission_per_author_per_contest'),
        ]
        verbose_name = 'өтінім'
        verbose_name_plural = 'өтінімдер'

    def __str__(self):
        return f'{self.author.username} → {self.contest.slug}'
