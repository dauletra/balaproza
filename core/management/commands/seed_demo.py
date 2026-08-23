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

**Команда растёт по этапам.** Сейчас она умеет пользователей, теги,
произведения, главы и конкурсы — всё, для чего есть модели. Библиотека,
подписки, комментарии приезжают своими этапами (docs/19 §19.4), и тогда
же в неё переезжают литералы из стаба: удалить стаб — значит забрать его
данные себе, иначе демо-корпуса не станет вовсе.

Справочник жанров сюда не входит: 12 жанров заливает миграция. Портал без
них не работает, и приезжать они обязаны со схемой, а не с командой,
которую можно не запустить.
"""

from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core import data
from core.domain.catalog import BADGE_LABELS
from core.models import (
    AwardGrant,
    Chapter,
    ChapterReaction,
    Contest,
    ContestAward,
    ContestCondition,
    Genre,
    JuryMember,
    Story,
    Submission,
    Tag,
    TimelineStage,
    User,
)


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
            'stories': self._seed_stories(),
            'chapters': self._seed_chapters(),
            'contests': self._seed_contests(),
            'grants': self._seed_grants(),
            'submissions': self._seed_submissions(),
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

    def _seed_stories(self):
        """Произведения со связями: автор, жанры, теги.

        `updated_at` проставляется отдельным `update()`: поле объявлено
        `auto_now`, и обычное сохранение затёрло бы демо-давность
        сегодняшним днём. Там, где в стабе давность не задана вовсе
        (`None`), остаётся сегодняшняя дата — у строки в базе времени
        изменения не может не быть, и «не задано» после Ф14 исчезает как
        состояние.
        """
        genres = {g.slug: g for g in Genre.objects.all()}
        users = {u.username: u for u in User.objects.all()}
        tags = {t.slug: t for t in Tag.objects.all()}
        added = updated = 0

        for stub in data.STORIES:
            primary, secondary = stub.genres[0], (stub.genres[1:] or (None,))[0]
            story, is_new = Story.objects.update_or_create(
                slug=stub.slug,
                defaults={
                    'title':           stub.title,
                    'author':          users[stub.author_username],
                    'cover':           stub.cover,
                    'annotation':      stub.annotation,
                    'primary_genre':   genres[primary],
                    'secondary_genre': genres.get(secondary) if secondary else None,
                    'status':          stub.status,
                    'audience':        stub.audience,
                    'format':          stub.format,
                    'chapters':        stub.chapters,
                    'views':           stub.views,
                    'recent_views':    stub.recent_views,
                    'likes':           stub.likes,
                    'comments':        stub.comments,
                    # Знак редакции — акт человека; конкурсный знак выводится
                    # из заявки и сюда не переносится (см. `Story.badges`).
                    'is_editorial_pick': BADGE_LABELS['editorial'] in stub.badges,
                },
            )
            story.tags.set([tags[slug] for slug in stub.tags if slug in tags])
            if stub.updated_days_ago is not None:
                Story.objects.filter(pk=story.pk).update(
                    updated_at=timezone.now() - timedelta(days=stub.updated_days_ago))
            added += is_new
            updated += not is_new
        return added, updated

    def _seed_chapters(self):
        """Главы с текстом и счётчиками реакций.

        Лишние записи удаляются: идемпотентность — это сходимость к
        эталону, а не «дописать, чего не хватает». Убранная из стаба глава
        обязана исчезнуть и из базы, иначе повторный сид копит мусор.
        """
        added = updated = 0
        for stub in data.STORIES:
            story = Story.objects.get(slug=stub.slug)
            chapters = data.chapters_of(stub.slug)
            story.chapter_set.exclude(
                number__in=[c.number for c in chapters]).delete()

            for stub_chapter in chapters:
                chapter, is_new = Chapter.objects.update_or_create(
                    story=story, number=stub_chapter.number,
                    defaults={'title': stub_chapter.title,
                              'body': stub_chapter.body},
                )
                added += is_new
                updated += not is_new

                kinds = dict(stub_chapter.reactions)
                chapter.reactions.exclude(kind__in=kinds).delete()
                for kind, count in kinds.items():
                    ChapterReaction.objects.update_or_create(
                        chapter=chapter, kind=kind, defaults={'count': count})
        return added, updated

    def _seed_contests(self):
        """Конкурсы вместе с составом: условия, этапы, жюри, номинации.

        Даты приезжают из стаба как есть — там они заданы относительно
        сегодняшнего дня (DEC-45), и каждый прогон сида сдвигает их
        заново. Именно поэтому корпус не фикстура: застывший JSON через
        месяц перевёл бы идущий конкурс в другую фазу.

        Состав пересобирается целиком. Для условий, этапов и жюри это
        честнее сверки по строкам: у них нет своего ключа, кроме порядка,
        а на них никто не ссылается. Номинации, наоборот, обновляются по
        слагу — на них ссылаются присуждения, и пересоздание стёрло бы
        решение жюри.
        """
        added = updated = 0
        for stub in data.CONTESTS:
            contest, is_new = Contest.objects.update_or_create(
                slug=stub.slug,
                defaults={
                    'name':        stub.name,
                    'subtitle':    stub.subtitle,
                    'opens_on':    stub.opens_on,
                    'closes_on':   stub.closes_on,
                    'results_on':  stub.results_on,
                    'prize_kzt':   stub.prize_kzt,
                    'poster':      stub.poster,
                    'series':      stub.series,
                    'description': stub.description,
                    'min_chars':   stub.min_chars,
                    'max_chars':   stub.max_chars,
                    'min_age':     stub.min_age,
                    'max_age':     stub.max_age,
                },
            )
            added += is_new
            updated += not is_new

            contest.condition_set.all().delete()
            ContestCondition.objects.bulk_create([
                ContestCondition(contest=contest, text=text, position=i)
                for i, text in enumerate(stub.conditions)
            ])

            contest.stage_set.all().delete()
            TimelineStage.objects.bulk_create([
                TimelineStage(contest=contest, label=s.label, starts=s.starts,
                              ends=s.ends, position=i)
                for i, s in enumerate(stub.timeline)
            ])

            contest.jury_set.all().delete()
            JuryMember.objects.bulk_create([
                JuryMember(contest=contest, name=m.name, role=m.role, position=i)
                for i, m in enumerate(stub.jury)
            ])

            slugs = [a.slug for a in stub.awards]
            contest.award_set.exclude(slug__in=slugs).delete()
            for i, award in enumerate(stub.awards):
                ContestAward.objects.update_or_create(
                    contest=contest, slug=award.slug,
                    defaults={'title': award.title, 'image': award.image,
                              'description': award.description, 'position': i},
                )
        return added, updated

    def _seed_grants(self):
        """Присуждения (DEC-46) — акт жюри, поэтому переносятся как данные,
        а не выводятся из чего-либо."""
        added = updated = 0
        for stub in data.AWARD_GRANTS:
            contest = Contest.objects.get(slug=stub.contest_slug)
            _, is_new = AwardGrant.objects.update_or_create(
                contest=contest,
                award=contest.award_set.get(slug=stub.award_slug),
                defaults={'story': Story.objects.get(slug=stub.story_slug),
                          'note': stub.note},
            )
            added += is_new
            updated += not is_new
        return added, updated

    def _seed_submissions(self):
        """Заявки авторов. Автор берётся из ключа стаба, а не из работы:
        подаёт человек, и BR-23 считает заявки именно по нему."""
        added = updated = 0
        for username, subs in data.SUBMISSIONS_BY_USER.items():
            author = User.objects.get(username=username)
            for stub in subs:
                _, is_new = Submission.objects.update_or_create(
                    contest=Contest.objects.get(slug=stub.contest_slug),
                    author=author,
                    defaults={'story': Story.objects.get(slug=stub.story_slug),
                              'submitted_on': stub.submitted_on,
                              'status': stub.status,
                              'note': stub.note},
                )
                added += is_new
                updated += not is_new
        return added, updated
