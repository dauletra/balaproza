"""Что читатель оставляет у работы и что приходит ему самому:
комментарии, полки, прогресс чтения, уведомления."""

from functools import cached_property

from django.db import models
from django.utils import timezone

from ..domain.library import LIBRARY_KINDS
from ..domain.notifications import (
    MODERATION_OUTCOME_LABELS,
    MODERATION_OUTCOMES,
    NOTIF_KIND_LABELS,
    NOTIF_KINDS,
)


class StoryComment(models.Model):
    """Комментарий к произведению или к главе. Вложенность
    ровно одна: ответ на ответ даёт дерево, которое на телефоне не читается
    и которое некому модерировать."""

    story = models.ForeignKey('core.Story', verbose_name='шығарма',
                              on_delete=models.CASCADE,
                              related_name='comment_set')
    author = models.ForeignKey('core.User', verbose_name='авторы',
                               on_delete=models.CASCADE,
                               related_name='comments')
    # К какой главе пришвартован; пусто — комментарий ко всему произведению.
    chapter_number = models.PositiveSmallIntegerField('бөлім', null=True,
                                                      blank=True)
    parent = models.ForeignKey('self', verbose_name='жауап',
                               on_delete=models.CASCADE, null=True, blank=True,
                               related_name='reply_set')
    text = models.TextField('мәтіні')
    # Задержан до решения модератора (D2). Комментарии не проходят
    # премодерацию сплошь — это был бы поток, с которым не справиться, и
    # ответ через сутки перестаёт быть разговором. Задерживается только
    # то, что попало в блок-лист: остальное публикуется сразу и живёт по
    # жалобам.
    #
    # Задержанного не видит никто, включая автора работы: показать его
    # одному значит объяснять, почему второй его не видит.
    held = models.BooleanField('тексеруде', default=False)
    # Агрегат по `CommentLike` — колонка: пересчитывается в момент нажатия,
    # а не подзапросом на каждый комментарий страницы.
    likes = models.PositiveIntegerField('ұнату', default=0)
    created_at = models.DateTimeField('жазылған', default=timezone.now)

    class Meta:
        ordering = ('pk',)
        verbose_name = 'пікір'
        verbose_name_plural = 'пікірлер'

    def __str__(self):
        return f'{self.author.username}: {self.text[:40]}'

    @cached_property
    def replies(self) -> list:
        """Ответы на комментарий, по `pk`. `cached_property`, потому что
        метку `.liked` ставит `queries/story` на уже полученных
        объектах; без своего `select_related` — он рвёт кэш prefetch'а."""
        return list(self.reply_set.all())

    @property
    def is_author_badge(self) -> bool:
        """Пишет автор произведения — выводится, не проставляется руками."""
        return self.author_id == self.story.author_id

    def belongs_to(self, username: str) -> bool:
        """Свой комментарий: меню предлагает «Жою», а не «Шағым»."""
        return bool(username) and self.author.username == username


class CommentLike(models.Model):
    """Кто лайкнул какой комментарий. Повторный клик снимает
    отклик, а для этого надо знать, кто нажимал: счётчик этого не несёт."""

    user = models.ForeignKey('core.User', verbose_name='оқырман',
                             on_delete=models.CASCADE, related_name='comment_likes')
    comment = models.ForeignKey(StoryComment, verbose_name='пікір',
                                on_delete=models.CASCADE, related_name='like_set')
    created_at = models.DateTimeField('басылған', auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('user', 'comment'),
                                    name='unique_like_per_user_per_comment'),
        ]
        verbose_name = 'пікір ұнатуы'
        verbose_name_plural = 'пікір ұнатулары'

    def __str__(self):
        return f'{self.user.username} ♥ #{self.comment_id}'


class LibraryEntry(models.Model):
    """Запись в библиотеке читателя. Три вида — «сақталған»,
    «оқу үстінде», «оқылған» — не пересекаются: работа лежит ровно в одном,
    и это ограничение базы. Номера главы здесь нет — его знает
    `ReadingProgress`, а полка получает аннотацией."""

    KIND_CHOICES = [(k, k) for k in LIBRARY_KINDS]

    user = models.ForeignKey('core.User', verbose_name='оқырман',
                             on_delete=models.CASCADE,
                             related_name='library')
    story = models.ForeignKey('core.Story', verbose_name='шығарма',
                              on_delete=models.CASCADE,
                              related_name='library_entries')
    kind = models.CharField('түрі', max_length=16, choices=KIND_CHOICES)
    added_on = models.DateField('қосылған күні', default=timezone.localdate)

    class Meta:
        ordering = ('-added_on', 'pk')
        indexes = [
            # «Полка такого-то читателя» — единственный способ, которым
            # в эту таблицу ходят.
            models.Index(fields=['user', 'kind']),
        ]
        constraints = [
            models.UniqueConstraint(fields=('user', 'story'),
                                    name='one_library_entry_per_story'),
        ]
        verbose_name = 'кітапхана жазбасы'
        verbose_name_plural = 'кітапхана жазбалары'

    def __str__(self):
        return f'{self.user.username} · {self.story.slug} ({self.kind})'


class ReadingProgress(models.Model):
    """Где читатель остановился — двигатель «Оқуды жалғастыру».
    Цитата хранится, потому что позиции в тексте у нас нет: читалка не
    сообщает, где закрыли страницу."""

    user = models.ForeignKey('core.User', verbose_name='оқырман',
                             on_delete=models.CASCADE,
                             related_name='reading_progress')
    story = models.ForeignKey('core.Story', verbose_name='шығарма',
                              on_delete=models.CASCADE,
                              related_name='reading_progress')
    current_chapter = models.PositiveSmallIntegerField('бөлім', default=1)
    quote = models.TextField('соңғы абзац', blank=True)
    minutes_left = models.PositiveSmallIntegerField('қалған минут', default=0)
    last_read_on = models.DateField('соңғы оқыған күні', default=timezone.localdate)

    class Meta:
        ordering = ('-last_read_on',)
        constraints = [
            models.UniqueConstraint(fields=('user', 'story'),
                                    name='one_progress_per_story'),
        ]
        verbose_name = 'оқу барысы'
        verbose_name_plural = 'оқу барысы'

    def __str__(self):
        return f'{self.user.username} · {self.story.slug} → {self.current_chapter}'


class Notification(models.Model):
    """Событие в ленте автора. Уведомление ведёт к
    своему предмету: имя приходит из объекта, а в `text` лежит
    только событие. Исключения — чужие слова: цитата читателя у
    комментария и причина модератора у отказа."""

    KIND_CHOICES = [(k, NOTIF_KIND_LABELS[k]) for k in NOTIF_KINDS]
    OUTCOME_CHOICES = [(o, MODERATION_OUTCOME_LABELS[o])
                       for o in MODERATION_OUTCOMES]

    user = models.ForeignKey('core.User', verbose_name='кімге',
                             on_delete=models.CASCADE,
                             related_name='notifications')
    kind = models.CharField('түрі', max_length=16, choices=KIND_CHOICES)
    created_at = models.DateTimeField('болған уақыты', default=timezone.now)
    # Кто инициатор; пусто — системное событие.
    actor = models.ForeignKey('core.User', verbose_name='кім', null=True,
                              blank=True, on_delete=models.CASCADE,
                              related_name='caused_notifications')
    story = models.ForeignKey('core.Story', verbose_name='шығарма', null=True,
                              blank=True, on_delete=models.CASCADE,
                              related_name='notifications')
    contest = models.ForeignKey('core.Contest', verbose_name='байқау', null=True,
                                blank=True, on_delete=models.CASCADE,
                                related_name='notifications')
    # Хранится: это акт модератора, а не состояние работы. Из
    # `Story.status` не выводится — статус живёт дальше события, и
    # вчерашний отказ сказал бы «Модерацияда».
    outcome = models.CharField('модерация нәтижесі', max_length=16, blank=True,
                               choices=OUTCOME_CHOICES)
    text = models.CharField('оқиға', max_length=300, blank=True)
    read = models.BooleanField('оқылды', default=False)
    # Когда событие ушло в Telegram; пусто — ещё не уходило. Колонка, а не
    # отдельная таблица очереди: очередь тут и есть «уведомления без этой
    # отметки», и вторая таблица дублировала бы первую целиком.
    #
    # `read` отвечает на другой вопрос и заменить её не может: «прочитано»
    # — про человека и ленту на сайте, «отправлено» — про бота. Событие
    # бывает отправленным и непрочитанным, и это норма.
    pushed_at = models.DateTimeField('Telegram-ға жіберілді',
                                     null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'хабарлама'
        verbose_name_plural = 'хабарламалар'
        indexes = [
            # Лента и бейдж в шапке спрашивают одно: «этого автора за
            # последнюю неделю». Бейдж — на каждой странице у каждого
            # вошедшего, так что этот индекс трогают чаще прочих.
            models.Index(fields=['user', '-created_at']),
            # Очередь отправки. Частичный: неотправленных в любой момент
            # единицы — всё, что успело накопиться между запусками команды,
            # — а полный индекс по `pushed_at` рос бы вместе со всей
            # историей уведомлений ради выборки из десяти строк.
            models.Index(fields=['created_at'],
                         condition=models.Q(pushed_at__isnull=True),
                         name='notif_unpushed'),
        ]

    def __str__(self):
        return f'{self.user.username} · {self.kind}'

    @property
    def days_ago(self) -> int:
        """Сколько календарных дней назад. Именно календарных: лента
        группирует по «сегодня / вчера / за неделю», а не по суткам."""
        return (timezone.localdate() - timezone.localtime(self.created_at).date()).days

    @property
    def bucket(self) -> str:
        """Группа ленты или '' у события старше недели: групп ровно три,
        четвёртой («раньше») нет — значит неделя и есть глубина
        ленты."""
        days = self.days_ago
        if days <= 0:
            return 'today'
        if days == 1:
            return 'yesterday'
        return 'past_week' if days <= 7 else ''
