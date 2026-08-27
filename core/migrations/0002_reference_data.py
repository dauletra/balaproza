"""Справочники: 12 жанров (DEC-11) и стартовый блок-лист тегов (BR-TAG-05).

Миграцией, а не сидом: это не демо-контент, а часть системы. Портал без
жанров не работает — цвет карточки, полоса на главной и ось каталога
берутся отсюда, — поэтому справочник обязан приезжать вместе со схемой,
на любую машину и в прод, а не отдельной командой, которую забудут.

Значения вписаны литералами и ниоткуда не читаются. Данные миграции
заморожены на момент её написания: импорт живого модуля означал бы, что
уже применённая миграция меняет смысл при следующей правке кода. Модуль,
из которого их можно было бы взять, к тому же успел исчезнуть — стаб
удалён, а справочник на месте.
"""

from django.db import migrations

# slug, название, OKLCH hue, слаг иконки. Порядок строк — порядок вывески
# на главной: он редакторский, поэтому хранится (Genre.position).
GENRES = [
    ('fantastika', 'Фантастика', 250, 'planet'),
    ('fantezi',    'Фэнтези',    295, 'feather'),
    ('triller',    'Триллер',    210, 'skull'),
    ('romantika',  'Романтика',    8, 'heart'),
    ('drama',      'Драма',      195, 'drop'),
    ('horror',     'Хоррор',      25, 'fir'),
    ('erteg',      'Ертегі',      75, 'book'),
    ('tarih',      'Тарихи',      40, 'book'),
    ('komediya',   'Комедия',     55, 'smile'),
    ('fanfik',     'Фанфик',     330, 'pen'),
    ('balalar',    'Балалар',    180, 'backpack'),
    ('shyttyrman', 'Шытырман',   145, 'cityscape'),
]

# Стартовый список, не окончательный: таблица затем и заведена, чтобы
# модератор пополнял её сам, не дожидаясь релиза.
BLOCKED_TAG_PATTERNS = ['spam', 'реклама', 'политика']


def seed(apps, schema_editor):
    Genre = apps.get_model('core', 'Genre')
    BlockedTagPattern = apps.get_model('core', 'BlockedTagPattern')
    for position, (slug, name, hue, icon) in enumerate(GENRES):
        Genre.objects.update_or_create(
            slug=slug,
            defaults={'name': name, 'hue': hue, 'icon': icon,
                      'position': position},
        )
    for pattern in BLOCKED_TAG_PATTERNS:
        BlockedTagPattern.objects.get_or_create(pattern=pattern)


def unseed(apps, schema_editor):
    apps.get_model('core', 'Genre').objects.filter(
        slug__in=[g[0] for g in GENRES]).delete()
    apps.get_model('core', 'BlockedTagPattern').objects.filter(
        pattern__in=BLOCKED_TAG_PATTERNS).delete()


class Migration(migrations.Migration):

    dependencies = [('core', '0001_initial')]

    operations = [migrations.RunPython(seed, unseed)]
