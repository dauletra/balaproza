"""Демо-корпус в базе: то, что до Ф14 ехало вместе с кодом.

Пока данные лежат литералами в `core/stub_data.py`, они переносятся между
машинами как обычный код. После Ф14 так больше нельзя, и место этого
механизма занимает эта команда: она **идемпотентна** и запускается сколько
угодно раз — на пустой базе, поверх уже засеянной, после смены схемы.

Почему команда, а не фикстура. Даты идущих конкурсов заданы относительно
сегодняшнего дня (DEC-45): застывший JSON через месяц переведёт конкурс в
другую фазу, и тесты начнут падать по календарю, а не по коду. Команда
пересчитывает такие значения при каждом запуске.

Почему источник — `core.data`, а не `core.stub_data` напрямую. Дверь к
данным одна (`test_data_facade`), и у сида нет причин быть исключением.

**Команда растёт по этапам.** Сейчас она умеет пользователей и теги —
всё, для чего есть модели. Произведения, главы, конкурсы приезжают своими
этапами (docs/19 §19.4), и тогда же в неё переезжают литералы из стаба:
удалить стаб — значит забрать его данные себе, иначе демо-корпуса не
станет вовсе.

Справочник жанров сюда не входит: 12 жанров заливает миграция. Портал без
них не работает, и приезжать они обязаны со схемой, а не с командой,
которую можно не запустить.
"""

from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core import data
from core.models import Tag, User


class Command(BaseCommand):
    help = 'Раскладывает демо-корпус по моделям. Идемпотентна.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--quiet', action='store_true',
            help='Без отчёта в stdout (для вызова из тестов).',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        # Отчёт — по-английски, как у самих команд Django. Это вывод
        # инструмента, а не строка интерфейса (docs/16 про второе), и
        # консоль Windows в cp1251 на «жаңартылды» падает: ң и ү в эту
        # кодировку не отображаются вовсе.
        report = {
            'users': self._seed_users(),
            'tags': self._seed_tags(),
        }
        if not options['quiet']:
            for name, (added, updated) in report.items():
                self.stdout.write(f'{name}: {added} created, {updated} updated')

    def _seed_users(self):
        """Авторы стаба как пользователи портала.

        Пароль не выдаётся: вход в дизайн-фазе — фейковая сессия, а до
        этапа 9 настоящего логина нет вовсе. Пустой пароль (`''`) означал
        бы «вход без пароля», а не «входа нет», — поэтому явный
        `set_unusable_password`.

        Из года прихода (`joined_year` — единственное, что о времени знает
        стаб) собирается 1 января: в интерфейсе показывается только год
        (BR-73, docs/12 §12.4), а день никогда не выводится.
        """
        added = updated = 0
        for author in data.AUTHORS:
            joined = timezone.make_aware(datetime(author.joined_year, 1, 1))
            user, is_new = User.objects.update_or_create(
                username=author.username,
                defaults={
                    'name':      author.name,
                    'pen_name':  author.pen_name,
                    'bio':       author.bio,
                    'date_joined': joined,
                },
            )
            if is_new:
                user.set_unusable_password()
                user.save(update_fields=['password'])
            added += is_new
            updated += not is_new
        return added, updated

    def _seed_tags(self):
        """UGC-теги. Счётчики использования не переносятся: колонок под них
        нет и не будет — это агрегаты по работам (см. `core.models.Tag`)."""
        added = updated = 0
        for tag in data.TAGS:
            _, is_new = Tag.objects.update_or_create(
                slug=tag.slug,
                defaults={'name': tag.name, 'status': tag.status},
            )
            added += is_new
            updated += not is_new
        return added, updated
