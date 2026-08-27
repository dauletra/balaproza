"""Данные для одного теста — вместо литералов демо-корпуса.

Пятьсот семьдесят строк суиты были завязаны на `dalney-berega`, `aidana`
и `rudazov`: тест «сериал показывает N бөлім» проверял не правило, а
конкретную работу, которую кто-то однажды придумал. Такая связка стоит
дважды — правку корпуса нельзя сделать, не сломав суиту, а по красному
тесту не видно, что именно перестало работать: правило или демо-данные.

Корпус остаётся там, где нужен **объём**: смоук по всем маршрутам и
бюджеты запросов должны идти по странице, на которой что-то есть.
Сценарий же приносит своё: три работы с нужными статусами читаются прямо
в тесте, а не выясняются походом в `_corpus.py`.

Имена уникальны в пределах прогона — счётчик, а не случайность:
воспроизводимость важнее красоты, а `--parallel` разводит процессы по
разным базам.
"""

from itertools import count

from django.utils import timezone

from core.models import (
    Chapter,
    Contest,
    Genre,
    Story,
    StoryComment,
    Tag,
    User,
)

_seq = count(1)


def _uniq(prefix: str) -> str:
    return f'{prefix}-{next(_seq)}'


def user(**over) -> User:
    """Автор портала. Пароль не выдаётся — вход в тестах через `login_as`."""
    username = over.pop('username', None) or _uniq('reader')
    fields = {
        'name': 'Сынақ Авторы',
        'pen_name': username,
        'bio': '',
    }
    fields.update(over)
    return User.objects.create(username=username, **fields)


def genre() -> Genre:
    """Любой жанр из справочника. Свой не заводим: список закрыт (DEC-11)."""
    return Genre.objects.order_by('position', 'pk').first()


def story(*, author=None, chapters: int = 0, chars: int = 1200, **over) -> Story:
    """Произведение с нужным статусом и, если попросили, с текстом.

    `chapters` — сколько глав написать. Именно написать: числа частей
    отдельно от текста больше не существует (DEC-51), и «сериал на три
    бөлім» в тесте означает три записи с телом.
    """
    slug = over.pop('slug', None) or _uniq('story')
    fields = {
        'title': f'Сынақ шығармасы {slug}',
        'author': author or user(),
        'primary_genre': over.pop('primary_genre', None) or genre(),
        'status': 'Published',
        'format': 'single' if chapters <= 1 else 'serial',
        'audience': '10+',
        'annotation': 'Сынақ аннотациясы.',
    }
    fields.update(over)
    obj = Story.objects.create(slug=slug, **fields)
    for number in range(1, chapters + 1):
        chapter(obj, number=number, chars=chars)
    return obj


def chapter(story_obj, *, number: int = 1, chars: int = 1200, **over) -> Chapter:
    fields = {'title': f'{number}-бөлім', 'body': 'а' * chars}
    fields.update(over)
    return Chapter.objects.create(story=story_obj, number=number, **fields)


def tag(*, status: str = 'accepted', **over) -> Tag:
    slug = over.pop('slug', None) or _uniq('tag')
    fields = {'name': slug, 'status': status}
    fields.update(over)
    return Tag.objects.create(slug=slug, **fields)


def contest(*, phase: str = 'accepting', **over) -> Contest:
    """Конкурс в нужной фазе.

    Фаза не хранится — она выводится из трёх дат (DEC-45), поэтому тест
    просит фазу, а даты считаются здесь. Иначе каждый тест выписывал бы
    `opens_on`/`closes_on`/`results_on` руками и однажды ошибся бы в
    знаке.
    """
    today = timezone.localdate()
    day = timezone.timedelta(days=1)
    spans = {
        'upcoming':  (today + 5 * day, today + 20 * day, today + 40 * day),
        'accepting': (today - 5 * day, today + 20 * day, today + 40 * day),
        'judging':   (today - 40 * day, today - 5 * day, today + 20 * day),
        'finished':  (today - 90 * day, today - 60 * day, today - 30 * day),
    }
    opens_on, closes_on, results_on = spans[phase]
    slug = over.pop('slug', None) or _uniq('contest')
    fields = {
        'name': f'Сынақ байқауы {slug}',
        'opens_on': opens_on,
        'closes_on': closes_on,
        'results_on': results_on,
    }
    fields.update(over)
    return Contest.objects.create(slug=slug, **fields)


def comment(story_obj, *, author=None, chapter_number=None, **over) -> StoryComment:
    fields = {'text': 'Сынақ пікірі.'}
    fields.update(over)
    return StoryComment.objects.create(
        story=story_obj, author=author or user(),
        chapter_number=chapter_number, **fields)
