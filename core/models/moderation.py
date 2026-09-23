"""Модерация: решения по ревизиям, захват работы модератором, жалобы
на уже опубликованное."""

from django.db import models
from django.utils import timezone

from ..domain.notifications import MODERATION_OUTCOME_LABELS, MODERATION_OUTCOMES
from ..domain.reports import REPORT_REASON_LABELS, REPORT_REASONS


class ModerationDecision(models.Model):
    """Решение модератора как акт — с тем, кто его принял.

    До этой модели след решения был один: `Notification`, адресованное
    автору. У него нет автора решения, и вопрос «кто одобрил вот это»
    ответа не имел вовсе. Акт с датой и человеком не выводится из
    состояния объекта — как `AwardGrant`.

    Уведомление никуда не делось: это разные вещи. Решение — что
    произошло; уведомление — что об этом сказали автору.
    """

    OUTCOME_CHOICES = [(o, MODERATION_OUTCOME_LABELS[o])
                       for o in MODERATION_OUTCOMES]

    story = models.ForeignKey('core.Story', verbose_name='шығарма',
                              on_delete=models.CASCADE,
                              related_name='moderation_decisions')
    # Модератор мог уйти с портала; решение остаётся — оно уже случилось.
    moderator = models.ForeignKey('core.User', verbose_name='модератор', null=True,
                                  blank=True, on_delete=models.SET_NULL,
                                  related_name='+')
    outcome = models.CharField('нәтижесі', max_length=16,
                               choices=OUTCOME_CHOICES)
    reason = models.TextField('себебі', blank=True)
    # Сколько глав затронуло решение: одно нажатие решает судьбу пачки
    # ревизий, и «одобрено 3 бөлім» — часть того, что случилось.
    chapters = models.PositiveSmallIntegerField('бөлім саны', default=0)
    decided_at = models.DateTimeField('шешілген', auto_now_add=True)

    class Meta:
        ordering = ('-decided_at', '-pk')
        verbose_name = 'модерация шешімі'
        verbose_name_plural = 'модерация шешімдері'
        indexes = [models.Index(fields=['story', '-decided_at'])]

    def __str__(self):
        return f'{self.story_id} · {self.outcome}'

    @property
    def label(self) -> str:
        return MODERATION_OUTCOME_LABELS.get(self.outcome, '')


class ModerationClaim(models.Model):
    """«Взял в работу».

    Отдельной строкой, а не полем у `Story`: состояние живёт минуты,
    удаляется решением и не имеет отношения к произведению как таковому.
    Двое модераторов, открывшие одну работу, до этого узнавали друг о
    друге только по результату — второй читал уже решённое.

    Метка не запрещает решать: она предупреждает. Запрет означал бы, что
    забытая метка блокирует очередь до вмешательства администратора.
    """

    story = models.OneToOneField('core.Story', verbose_name='шығарма',
                                 on_delete=models.CASCADE,
                                 related_name='claim')
    moderator = models.ForeignKey('core.User', verbose_name='модератор',
                                  on_delete=models.CASCADE, related_name='+')
    claimed_at = models.DateTimeField('алынған', auto_now_add=True)

    class Meta:
        verbose_name = 'қаралуда'
        verbose_name_plural = 'қаралуда'

    def __str__(self):
        return f'{self.story_id} → {self.moderator_id}'


class Report(models.Model):
    """Жалоба читателя на уже опубликованный контент.

    Не про очередь `/moderation/` (та — про ревизии до публикации):
    цель здесь — история или комментарий, уже показанные читателю. Ровно
    одно из `story`/`comment` заполнено — проверяется в
    `queries.moderation.create_report`, а не ограничением базы: тот же
    приём, что у `Notification.story`/`contest`.

    Рассмотрение — акт с автором и датой, как `ModerationDecision`: без
    этого «кто отклонил жалобу» осталось бы без ответа. Снятие контента
    жалоба не делает сама — решает `queries.moderation.resolve_report`
    (`Story.take_down` или удаление комментария).
    """

    REASON_CHOICES = [(r, REPORT_REASON_LABELS[r]) for r in REPORT_REASONS]
    OUTCOME_CHOICES = [
        ('dismissed', 'Бұзушылық жоқ'),
        ('upheld',    'Расталды'),
    ]

    reporter = models.ForeignKey('core.User', verbose_name='кімнен',
                                 on_delete=models.CASCADE,
                                 related_name='reports_filed')
    story = models.ForeignKey('core.Story', verbose_name='шығарма', null=True,
                              blank=True, on_delete=models.CASCADE,
                              related_name='reports')
    # SET_NULL, не CASCADE: снятие комментария по этой же жалобе (`uphold`)
    # не должно стирать акт рассмотрения, а открытая жалоба — пропадать
    # молча, если автор удалит комментарий раньше решения.
    comment = models.ForeignKey('core.StoryComment', verbose_name='пікір', null=True,
                                blank=True, on_delete=models.SET_NULL,
                                related_name='reports')
    reason = models.CharField('себебі', max_length=16, choices=REASON_CHOICES)
    note = models.CharField('түсініктеме', max_length=500, blank=True)
    created_at = models.DateTimeField('жіберілген', default=timezone.now)
    outcome = models.CharField('нәтижесі', max_length=16, blank=True,
                               choices=OUTCOME_CHOICES)
    resolved_at = models.DateTimeField('қаралған', null=True, blank=True)
    # Почему снято — слова модератора. У работы они уходят и автору
    # (`take_down`), у пікір — никуда больше: без этой колонки причину,
    # которую форма требовала, стирал первый же редирект, и на «за что
    # удалили» ответа не было нигде.
    resolution = models.CharField('шешім себебі', max_length=300, blank=True)
    # Модератор мог уйти с портала; шешім қалады — ол болып қойды.
    resolved_by = models.ForeignKey('core.User', verbose_name='қараған',
                                    null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ('created_at',)
        verbose_name = 'шағым'
        verbose_name_plural = 'шағымдар'
        constraints = [
            # Одна **открытая** жалоба на цель от одного человека. Без
            # этого очередь модератора заваливалась одним кликом,
            # повторённым сто раз.
            #
            # Именно открытая, а не любая: работа живёт дальше и
            # дописывается, и жалоба на то, что появилось после
            # рассмотрения прошлой, — законная. Закрыть дорогу навсегда
            # значило бы наказать читателя за то, что он однажды
            # пожаловался не по делу.
            models.UniqueConstraint(
                fields=('reporter', 'story'),
                condition=models.Q(story__isnull=False,
                                   resolved_at__isnull=True),
                name='one_open_report_per_story_per_reporter'),
            models.UniqueConstraint(
                fields=('reporter', 'comment'),
                condition=models.Q(comment__isnull=False,
                                   resolved_at__isnull=True),
                name='one_open_report_per_comment_per_reporter'),
        ]

    def __str__(self):
        target = f'шығарма #{self.story_id}' if self.story_id else f'пікір #{self.comment_id}'
        return f'{self.reporter_id} → {target}'

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None
