"""Люди: аккаунт и подписка одного на другого."""

from functools import cached_property

from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone

from ..domain.catalog import PUBLIC_STATUSES
from ..domain.formatting import kk_joined
from ..managers import from_annotation
from ..uploads import _ext, validate_raster_image


def user_avatar_path(instance, filename):
    return f'avatars/{instance.username}{_ext(filename)}'


class User(AbstractUser):
    """Пользователь портала; роли «читатель» нет. `first_name` /
    `last_name` убраны: казахское имя не делится на две западные графы.
    Настоящего имени сайт не хранит вовсе — только `pen_name`,
    под которым автор выступает."""

    first_name = None
    last_name = None

    # Единственное имя у аккаунта — публичное. Обязательно с онбординга:
    # пустое поле означало бы, что автора называют по нику
    # (`@id<цифры>`) до первого сознательного выбора, а его теперь нет.
    pen_name = models.CharField('лақап аты', max_length=60, blank=True)
    bio = models.CharField('өзі туралы', max_length=200, blank=True)
    # Возраста и пола здесь нет, и это решение, а не пробел (D4/D5).
    #
    # Пол не использовался нигде: обязательное поле на входе, два
    # значения, не показывается ни на одной странице. Дата рождения имела
    # ровно один сценарий — возрастная вилка конкурса, — но её и там
    # решает отдельный чекбокс формы подачи (`Submission.age_confirmed`),
    # потому что самодекларацию всё равно никто не проверяет.
    #
    # Площадка собирает данные несовершеннолетних, и каждое лишнее поле
    # здесь — обязательство, которое кто-то должен защищать. Два поля,
    # не дававших ничего, стоили конверсии на входе и абзаца в политике
    # конфиденциальности.
    avatar = models.FileField('аватар', upload_to=user_avatar_path, blank=True,
                              max_length=200, validators=[validate_raster_image])
    # Колонка, а не `follower_set.count()`: её читают `ORDER BY` ленты
    # «Жаңа авторлар» и `WHERE` оси каталога. Пересчитывается по строкам
    # `Follow`, а не сдвигается на единицу, — так она сама себя исправляет.
    followers = models.PositiveIntegerField('жазылушы саны', default=0)
    # Провайдер личности. `null=True` — у сидовых и тестовых
    # пользователей его нет и не будет. Не участвует в `username`: тот —
    # случайный плейсхолдер, telegram_id только связывает
    # повторный вход с уже существующим аккаунтом.
    telegram_id = models.BigIntegerField('telegram id', unique=True,
                                         null=True, blank=True)
    # Акт согласия, не булев флаг — с датой, как
    # `AwardGrant`/`Notification.outcome`. Онбординг завершён ⟺ это поле
    # не `None`; отдельного флага «завершил онбординг» не заводим.
    terms_accepted_at = models.DateTimeField('ережелерге келісті',
                                             null=True, blank=True)
    # Слать ли уведомления в Telegram. По умолчанию да: право писать
    # получено на входе (виджет просит `request-access=write`), и человек,
    # вошедший через Telegram, ждёт ответа именно там.
    #
    # Снимается двумя способами. Сам человек — на `/me/edit/`. Сама
    # платформа — когда бот получил отказ, после которого повторять
    # бессмысленно: адресат закрыл бота или не дал права писать
    # (`push_notifications`). Второе важнее первого: без него очередь
    # каждый раз ломилась бы в закрытую дверь.
    telegram_push = models.BooleanField('Telegram-хабарлама', default=True)
    # Что именно слать — три семьи событий (`domain.PUSH_CATEGORIES`).
    # Отдельно от `telegram_push` намеренно: тот про **канал** и снимается
    # платформой, эти три — выбор человека. Одним общим выключателем автор,
    # уставший от откликов, терял бы и решения модератора.
    push_moderation = models.BooleanField('модерация мен байқау', default=True)
    push_response = models.BooleanField('оқырман жауабы', default=True)
    push_new_chapter = models.BooleanField('жаңа бөлімдер', default=True)

    class Meta:
        verbose_name = 'пайдаланушы'
        verbose_name_plural = 'пайдаланушылар'
        indexes = [
            # Поиск ищет автора всеми тремя именами `ILIKE`-подстрокой.
            # B-tree её не берёт — совпадение начинается не с начала
            # строки; триграммный берёт и сам складывает регистр.
            GinIndex(fields=['pen_name'], name='user_pen_name_trgm',
                     opclasses=['gin_trgm_ops']),
            GinIndex(fields=['username'], name='user_username_trgm',
                     opclasses=['gin_trgm_ops']),
        ]

    def __str__(self):
        return self.public_name

    def get_full_name(self):
        return self.public_name

    def get_short_name(self):
        return self.public_name

    @property
    def public_name(self) -> str:
        """Как автора называют читателю. Ник — запасной вариант, не второй."""
        return self.pen_name or f'@{self.username}'

    @cached_property
    def works(self) -> int:
        """Сколько работ автора видит читатель. Черновики не в
        счёт: иначе число выдаёт читателю, что у автора есть неопубликованное.
        """
        return from_annotation(
            self, 'works_count',
            lambda: self.stories.filter(status__in=PUBLIC_STATUSES).count())

    # ── Снимок автора на один запрос ─────────────────────────────────────
    # Профиль спрашивает работы автора из восьми мест. Снимок живёт в
    # `self.__dict__`, то есть ровно запрос; долгоживущий экземпляр —
    # команда, скрипт — покажет прочитанное в начале, как всякий снимок.
    @cached_property
    def authored(self) -> list:
        """Все работы автора, любого статуса, «что трогал последним»."""
        from ..queries.catalog import all_stories

        return list(all_stories().by_author(self).latest_edited())

    @cached_property
    def public_works(self) -> list:
        """Работы, которые видит посторонний. Режется из уже
        загруженных: правило то же, а второй `WHERE` — второй запрос."""
        return [s for s in self.authored if s.is_public]

    @cached_property
    def own_submissions(self) -> list:
        from ..queries.contests import submissions_of

        return list(submissions_of(self))

    @cached_property
    def library_entries(self) -> list:
        """Вся библиотека — три полки одной выборкой."""
        from ..queries.author import library_of

        return list(library_of(self))

    def shelf(self, kind: str) -> list:
        """Одна полка из общей выборки: три вкладки библиотеки стоили трёх
        запросов ради трёх счётчиков."""
        return [e for e in self.library_entries if e.kind == kind]

    @cached_property
    def reads(self) -> int:
        """Сколько раз прочитали автора — по публичным работам."""
        return sum(s.views for s in self.public_works)

    @property
    def joined_since(self) -> str:
        """«2 айдан бері» / «3 жыл 2 айдан бері» в шапке профиля —
        `kk_joined` по алматинскому календарному дню, а не UTC: полночь
        31 декабря по UTC — это уже 1 января в Алматы, и счёт дней обязан
        идти по нему же, не по серверному часовому поясу."""
        joined_date = timezone.localtime(self.date_joined).date()
        days = (timezone.localdate() - joined_date).days
        return kk_joined(days)


class Follow(models.Model):
    """Подписка одного автора на другого. Списки
    «Жазылымдар» и «Жазылушылар» публичны, но входа в контент из них нет:
    читать зовут жинақтар и каталог."""

    follower = models.ForeignKey('core.User', verbose_name='кім жазылды',
                                 on_delete=models.CASCADE,
                                 related_name='following_set')
    following = models.ForeignKey('core.User', verbose_name='кімге жазылды',
                                  on_delete=models.CASCADE,
                                  related_name='follower_set')
    created_at = models.DateTimeField('жазылған күні', auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.UniqueConstraint(fields=('follower', 'following'),
                                    name='unique_follow_pair'),
            # На себя не подписываются. Проверка в базе, потому что такая
            # строка ломает счётчики тихо, а не громко.
            models.CheckConstraint(
                condition=~models.Q(follower=models.F('following')),
                name='no_self_follow'),
        ]
        verbose_name = 'жазылым'
        verbose_name_plural = 'жазылымдар'

    def __str__(self):
        return f'{self.follower.username} → {self.following.username}'
