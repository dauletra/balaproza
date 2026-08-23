"""Демо-корпус в базе: то, что до Ф14 ехало вместе с кодом.

Пока данные лежат литералами в `core/stub_data.py`, они переносятся между
машинами как обычный код. После Ф14 так больше нельзя, и место этого
механизма занимает эта команда: она **идемпотентна** и запускается сколько
угодно раз — на пустой базе, поверх уже засеянной, после смены схемы.

Почему команда, а не фикстура. Даты идущих конкурсов заданы относительно
сегодняшнего дня (DEC-45): застывший JSON через месяц переведёт конкурс в
другую фазу, и тесты начнут падать по календарю, а не по коду. Команда
пересчитывает такие значения при каждом запуске.

Почему источник — `core.stub_data` напрямую, в обход фасада. Это
единственный модуль, которому так можно, и причина простая: фасад по мере
Ф14 начинает отвечать моделями, и сид, читающий через него, читал бы то,
что сам же записал. Команда — конвертер между двумя мирами, ей положено
видеть исходный; вместе со стабом она и умрёт.

**Команда покрывает весь корпус.** Когда стаб уйдёт, литералы переедут
сюда: удалить стаб — значит забрать его данные себе, иначе демо-корпуса
не станет вовсе.

Справочник жанров сюда не входит: 12 жанров заливает миграция. Портал без
них не работает, и приезжать они обязаны со схемой, а не с командой,
которую можно не запустить.
"""

from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core import stub_data
from core.domain.catalog import BADGE_LABELS
from core.domain.formatting import kk_updated
from core.models import (
    AwardGrant,
    BookOfWeek,
    Chapter,
    ChapterPoll,
    ChapterReaction,
    Contest,
    ContestAward,
    ContestCondition,
    Collection,
    CollectionItem,
    Follow,
    Genre,
    JuryMember,
    LibraryEntry,
    Notification,
    PollOption,
    ReadingProgress,
    SchoolLink,
    Story,
    StoryComment,
    Submission,
    Tag,
    TimelineStage,
    User,
)


# Разбор рукописной давности («3 күн бұрын») в дельту. Код переходный: он
# исчезнет вместе со стабом, когда литералы переедут сюда уже датами.
_RELATIVE_UNITS = {
    'мин':   timedelta(minutes=1),
    'сағат': timedelta(hours=1),
    'күн':   timedelta(days=1),
    'апта':  timedelta(weeks=1),
    'ай':    timedelta(days=30),
}


def _delta_behind(text: str) -> timedelta:
    parts = text.split()
    if parts[0] == 'бүгін':
        return timedelta(0)
    amount, unit = parts[0], parts[1]
    if unit not in _RELATIVE_UNITS:
        raise CommandError(f'непонятная давность в стабе: «{text}»')
    return int(amount) * _RELATIVE_UNITS[unit]


def _date_behind(text: str):
    """Дата, от которой подпись выходит **той же самой**.

    Проверка не формальность: если разобранная дата даёт другую строку,
    сид молча поменял бы текст на странице библиотеки. Пусть лучше упадёт.
    """
    days = _delta_behind(text).days
    if kk_updated(days) != text:
        raise CommandError(
            f'давность «{text}» не восстанавливается из даты: '
            f'{days} дней дают «{kk_updated(days)}»')
    return timezone.localdate() - timedelta(days=days)


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
            'follows': self._seed_follows(),
            'collections': self._seed_collections(),
            'book of week': self._seed_book_of_week(),
            'library': self._seed_library(),
            'comments': self._seed_comments(),
            'polls': self._seed_polls(),
            'notifications': self._seed_notifications(),
            'school links': self._seed_school_links(),
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
        for author in stub_data.AUTHORS:
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
        for tag in stub_data.TAGS:
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

        for stub in stub_data.STORIES:
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
        for stub in stub_data.STORIES:
            story = Story.objects.get(slug=stub.slug)
            chapters = stub_data.chapters_of(stub.slug)
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
        for stub in stub_data.CONTESTS:
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
        for stub in stub_data.AWARD_GRANTS:
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
        for username, subs in stub_data.SUBMISSIONS_BY_USER.items():
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

    def _seed_follows(self):
        """Подписки и счётчик подписчиков.

        Счётчик приходит из стаба числом, а строки `Follow` — настоящие,
        и их несколько. Это не рассогласование сида, а состояние демо:
        восемь тысяч подписчиков `rudazov` некому создать поимённо. Число
        показывает профиль, строки обслуживают «подписан ли я» и списки.
        """
        added = updated = 0
        for author in stub_data.AUTHORS:
            User.objects.filter(username=author.username).update(
                followers=author.followers)
            updated += 1
        for follower, targets in stub_data.FOLLOWING.items():
            me = User.objects.get(username=follower)
            for target in targets:
                _, is_new = Follow.objects.get_or_create(
                    follower=me, following=User.objects.get(username=target))
                added += is_new
        return added, updated

    def _seed_collections(self):
        """Редакционные жинақтар. Состав пересобирается: порядок внутри —
        и есть подборка, а сверять его построчно дороже, чем переложить."""
        added = updated = 0
        for i, stub in enumerate(stub_data.COLLECTIONS):
            collection, is_new = Collection.objects.update_or_create(
                slug=stub.slug,
                defaults={'name': stub.name, 'tint_hue': stub.tint_hue,
                          'icon': stub.icon, 'curator': stub.curator,
                          'description': stub.description, 'position': i},
            )
            added += is_new
            updated += not is_new
            collection.item_set.all().delete()
            CollectionItem.objects.bulk_create([
                CollectionItem(collection=collection,
                               story=Story.objects.get(slug=slug), position=n)
                for n, slug in enumerate(stub.story_slugs)
            ])
        return added, updated

    def _seed_book_of_week(self):
        stub = stub_data.BOOK_OF_WEEK
        _, is_new = BookOfWeek.objects.update_or_create(
            story=Story.objects.get(slug=stub.story_slug),
            defaults={'editorial_note': stub.editorial_note,
                      'quote': stub.quote,
                      'published_on': timezone.localdate()},
        )
        return int(is_new), int(not is_new)

    def _seed_library(self):
        """Библиотека и место, на котором читатель остановился.

        Давность в стабе — строка («2 күн бұрын»). Здесь она обращается в
        дату: подпись обязана выводиться, иначе она устареет к завтрашнему
        дню. Обращение проверяет само себя — если разобранная дата не даёт
        ту же подпись, сид падает, а не молча меняет текст на странице.
        """
        added = updated = 0
        for username, entries in stub_data.LIBRARY_BY_USER.items():
            user = User.objects.get(username=username)
            for stub in entries:
                _, is_new = LibraryEntry.objects.update_or_create(
                    user=user, story=Story.objects.get(slug=stub.story_slug),
                    defaults={
                        'kind': stub.kind,
                        'progress_chapter': stub.progress_chapter,
                        'added_on': _date_behind(stub.added_relative),
                    },
                )
                added += is_new
                updated += not is_new

        progress = stub_data.SAMPLE_PROGRESS
        ReadingProgress.objects.update_or_create(
            user=User.objects.get(username='aidana'),
            story=Story.objects.get(slug=progress.story_slug),
            defaults={'current_chapter': progress.current_chapter,
                      'quote': progress.quote,
                      'minutes_left': progress.minutes_left,
                      'last_read_on': timezone.localdate()
                      - timedelta(days=progress.last_read_days)},
        )
        return added, updated

    def _seed_comments(self):
        """Комментарии с одним уровнем ответов (BR-30).

        Время в стабе лежало строкой, написанной руками. Здесь остаётся
        момент, а подпись выводится — поэтому две формулировки меняются:
        «1 күн бұрын» становится «кеше», «1 апта бұрын» — «7 күн бұрын».
        Это не потеря: лесенка в проекте одна, и рукописная строка была
        ровно тем, что BR-70a запрещает.
        """
        added = updated = 0
        for story_slug, comments in stub_data.COMMENTS_BY_STORY.items():
            story = Story.objects.get(slug=story_slug)
            story.comment_set.all().delete()
            for stub in comments:
                row = self._comment(story, stub, parent=None)
                added += 1
                for reply in stub.replies:
                    self._comment(story, reply, parent=row)
                    added += 1
        return added, updated

    def _comment(self, story, stub, *, parent):
        return StoryComment.objects.create(
            story=story,
            author=User.objects.get(username=stub.author_username),
            chapter_number=stub.chapter_number,
            parent=parent,
            text=stub.text,
            likes=stub.likes,
            created_at=timezone.now() - _delta_behind(stub.date),
        )

    def _seed_polls(self):
        """Опросы под главами. Голоса — счётчиком: голосовать пока негде."""
        added = updated = 0
        for (story_slug, number), stub in stub_data.POLLS_BY_CHAPTER.items():
            chapter = Chapter.objects.get(story__slug=story_slug, number=number)
            poll, is_new = ChapterPoll.objects.update_or_create(
                chapter=chapter, defaults={'question': stub.question})
            added += is_new
            updated += not is_new
            votes = dict(stub.votes)
            poll.option_set.all().delete()
            PollOption.objects.bulk_create([
                PollOption(poll=poll, slug=slug, text=text,
                           votes=votes.get(slug, 0), position=i)
                for i, (slug, text) in enumerate(stub.options)
            ])
        return added, updated

    def _seed_notifications(self):
        """Уведомления. Хранится момент, «как давно» и группа выводятся."""
        added = updated = 0
        for username, items in stub_data.NOTIFICATIONS_BY_USER.items():
            user = User.objects.get(username=username)
            user.notifications.all().delete()
            for stub in items:
                Notification.objects.create(
                    user=user,
                    kind=stub.kind,
                    created_at=timezone.now() - timedelta(
                        days=stub.days_ago, hours=stub.hours_ago or 0),
                    actor=(User.objects.filter(username=stub.actor_username).first()
                           if stub.actor_username else None),
                    story=(Story.objects.filter(slug=stub.story_slug).first()
                           if stub.story_slug else None),
                    contest=(Contest.objects.filter(slug=stub.contest_slug).first()
                             if stub.contest_slug else None),
                    outcome=stub.outcome,
                    text=stub.text,
                    read=stub.read,
                )
                added += 1
        return added, updated

    def _seed_school_links(self):
        added = updated = 0
        for i, stub in enumerate(stub_data.SCHOOL_LINKS):
            _, is_new = SchoolLink.objects.update_or_create(
                channel=stub.channel,
                defaults={'title': stub.title, 'subtitle': stub.subtitle,
                          'url': stub.url, 'position': i},
            )
            added += is_new
            updated += not is_new
        return added, updated
