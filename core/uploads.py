"""Растровые файлы (BR-46, BR-86): проверка содержимого и пережатие.

Чистые функции без импорта моделей — их зовёт `models.py` (валидатор
поля) и `media_cleanup.py` (пережатие в сигнале). Импорт моделей здесь
дал бы цикл: `models.py` импортирует `validate_raster_image` отсюда же.

Раньше проверялось только расширение (`FileExtensionValidator`): файл с
любым содержимым под именем `.png` проходил, лимита размера не было,
пережатия — тоже, а замена файла оставляла старый висеть в `media/`
навсегда (S8 в AUDIT-WRITE-FLOW.md). Уборка старого файла — в
`media_cleanup.py`, сигналами, а не здесь: она про модели, а не про байты.
"""

from io import BytesIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

# Расширение → формат Pillow. Один словарь на «что разрешено» и «во что
# пережимать» — раньше это был список расширений в одном месте и решение
# «сохранять как PNG» в другом, и они бы разошлись при добавлении формата.
RASTER_FORMATS = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.webp': 'WEBP'}

# Общие на все четыре растровых поля платформы (Story.cover, User.avatar,
# Contest.poster, ContestAward.image) — разной политики под каждое не
# просят ни аудит, ни продукт.
RASTER_MAX_BYTES = 5 * 1024 * 1024
RASTER_MAX_DIMENSION = 2000


def _ext(filename: str) -> str:
    return Path(filename).suffix.lower()


def validate_raster_image(file) -> None:
    """Растр и только растр (BR-46), теперь по содержимому, а не по имени.

    Порядок — от дешёвой проверки к дорогой: расширение (без чтения байт),
    размер (уже прочитан загрузчиком, `file.size` ничего не стоит), и
    только потом настоящее декодирование. `.load()`, а не `.verify()`:
    `verify()` не распаковывает пиксели и не ловит ни усечённый файл, ни
    Pillow-бомбу распаковки (`Image.DecompressionBombError` — она бьёт
    именно на декодировании, не раньше).
    """
    ext = _ext(file.name)
    if ext not in RASTER_FORMATS:
        raise ValidationError(
            'Тек растр сурет: png, jpg, webp. SVG қабылданбайды (BR-46).')
    if file.size > RASTER_MAX_BYTES:
        raise ValidationError(
            f'Файл тым үлкен — {RASTER_MAX_BYTES // (1024 * 1024)} '
            f'МБ-тан аспасын.')
    try:
        with Image.open(file) as img:
            img.load()
    except (UnidentifiedImageError, OSError, ValueError):
        raise ValidationError('Файл бүлінген немесе сурет емес.')
    finally:
        # `.load()` дочитывает файл до конца — следующему читателю того же
        # объекта (пережатие после сохранения формы) нужен байт с начала.
        file.seek(0)


def resize_raster_image(file, ext: str) -> ContentFile:
    """Пережать в границу стороны и в формат по расширению (BR-86).

    Формат берётся из **расширения**, а не из того, что Pillow нашёл в
    байтах: иначе `.png` в адресе мог бы содержать JPEG-байты внутри —
    расхождение имени и содержимого, которое ловил бы уже не Pillow, а
    браузер читателя. `exif_transpose` — до ресайза: телефонная фотография
    без него ляжет боком, поворот записан в EXIF, а не в пикселях.
    """
    fmt = RASTER_FORMATS[ext]
    with Image.open(file) as img:
        img = ImageOps.exif_transpose(img)
        if img.width > RASTER_MAX_DIMENSION or img.height > RASTER_MAX_DIMENSION:
            img.thumbnail((RASTER_MAX_DIMENSION, RASTER_MAX_DIMENSION), Image.LANCZOS)
        if fmt == 'JPEG' and img.mode not in ('RGB', 'L'):
            # JPEG не несёт альфа-канал — прозрачность иначе роняла бы save().
            img = img.convert('RGB')
        buffer = BytesIO()
        save_kwargs = {'quality': 85, 'optimize': True} if fmt == 'JPEG' else {}
        img.save(buffer, format=fmt, **save_kwargs)
    return ContentFile(buffer.getvalue(), name=file.name)
