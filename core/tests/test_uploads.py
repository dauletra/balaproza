"""Растровые файлы (BR-86): валидатор, пережатие, уборка старого файла.

`MEDIA_ROOT` подменяется на временную папку в тестах, которые реально
пишут и удаляют файлы на диске — тот же приём, что в
`test_admin.MediaUploadsTakeRasterOnly`: боевой `media/` тестам трогать
нельзя, а откат транзакции файлов на диске не касается вовсе.
"""

import shutil
import tempfile
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from core.tests import factories
from core.uploads import (
    RASTER_MAX_BYTES,
    RASTER_MAX_DIMENSION,
    resize_raster_image,
    validate_raster_image,
)


def _image_bytes(size=(64, 64), fmt='PNG'):
    buffer = BytesIO()
    Image.new('RGB', size).save(buffer, format=fmt)
    return buffer.getvalue()


class ValidateRasterImageChecksContentNotJustTheName(TestCase):
    """S8: `FileExtensionValidator` проверял только расширение — файл с
    любым содержимым под именем `.png` проходил."""

    def test_a_real_raster_passes(self):
        upload = SimpleUploadedFile('cover.png', _image_bytes(),
                                    content_type='image/png')
        validate_raster_image(upload)  # не бросает

    def test_text_under_a_raster_extension_is_refused(self):
        upload = SimpleUploadedFile('cover.png', b'not an image at all',
                                    content_type='image/png')
        with self.assertRaises(ValidationError):
            validate_raster_image(upload)

    def test_svg_is_refused_by_extension_alone(self):
        upload = SimpleUploadedFile('cover.svg', b'<svg/>',
                                    content_type='image/svg+xml')
        with self.assertRaises(ValidationError):
            validate_raster_image(upload)

    def test_the_rejection_does_not_name_an_internal_rule_code(self):
        """V2 (AUDIT-WRITE-FLOW): тост показывал «(BR-46)» — идентификатор
        внутреннего требования ребёнку-автору. Пометка нужна в коде и в
        docs/, не в сообщении."""
        upload = SimpleUploadedFile('cover.svg', b'<svg/>',
                                    content_type='image/svg+xml')
        with self.assertRaises(ValidationError) as caught:
            validate_raster_image(upload)
        self.assertNotIn('BR-', str(caught.exception))

    def test_an_oversized_file_is_refused(self):
        upload = SimpleUploadedFile('cover.png', _image_bytes(),
                                    content_type='image/png')
        upload.size = RASTER_MAX_BYTES + 1
        with self.assertRaises(ValidationError):
            validate_raster_image(upload)

    def test_a_validated_file_can_still_be_read_afterwards(self):
        """`.load()` дочитывает файл до конца — без `seek(0)` следующий
        читатель (пережатие после сохранения формы) увидел бы пусто."""
        upload = SimpleUploadedFile('cover.png', _image_bytes(),
                                    content_type='image/png')
        validate_raster_image(upload)
        self.assertTrue(upload.read())


class ResizeRasterImageBoundsAndConverts(TestCase):
    """BR-86: пережатие — граница стороны и формат хранения по имени."""

    def test_an_oversized_image_is_thumbnailed(self):
        big = SimpleUploadedFile(
            'cover.png', _image_bytes(size=(RASTER_MAX_DIMENSION + 400,) * 2),
            content_type='image/png')
        processed = resize_raster_image(big, '.png')
        with Image.open(processed) as out:
            self.assertLessEqual(max(out.size), RASTER_MAX_DIMENSION)

    def test_a_small_image_is_not_upscaled(self):
        small = SimpleUploadedFile('cover.png', _image_bytes(size=(64, 64)),
                                   content_type='image/png')
        processed = resize_raster_image(small, '.png')
        with Image.open(processed) as out:
            self.assertEqual(out.size, (64, 64))

    def test_output_format_follows_the_extension_not_the_content(self):
        """Имя решает формат хранения — иначе `.png`-адрес мог бы нести
        JPEG-байты внутри, и браузер читателя получил бы то, чего не
        обещает расширение в URL."""
        upload = SimpleUploadedFile('cover.png', _image_bytes(fmt='JPEG'),
                                    content_type='image/png')
        processed = resize_raster_image(upload, '.png')
        with Image.open(processed) as out:
            self.assertEqual(out.format, 'PNG')


MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class MediaCleanupSignalsRemoveOrphanFiles(TestCase):
    """BR-86: замена и удаление объекта убирают файл из storage — раньше
    (S8) старый файл оставался в `media/` навсегда."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def test_replacing_the_cover_deletes_the_previous_file(self):
        story = factories.story(author=factories.user())
        story.cover = factories.tiny_image('first.png')
        story.save()
        first_name = story.cover.name
        self.assertTrue(default_storage.exists(first_name))

        # Другое расширение — иначе оба файла легли бы под один и тот же
        # канонический путь (`covers/<slug>.<ext>`), и по имени было бы не
        # отличить «перезаписан на месте» от «остался сиротой».
        story.cover = factories.tiny_image('second.jpg')
        story.save()
        self.assertFalse(default_storage.exists(first_name))
        self.assertTrue(default_storage.exists(story.cover.name))

    def test_deleting_the_story_deletes_its_cover(self):
        story = factories.story(author=factories.user())
        story.cover = factories.tiny_image()
        story.save()
        name = story.cover.name
        story.delete()
        self.assertFalse(default_storage.exists(name))

    def test_removing_the_cover_without_a_replacement_deletes_the_file(self):
        story = factories.story(author=factories.user())
        story.cover = factories.tiny_image()
        story.save()
        name = story.cover.name
        story.cover = ''
        story.save()
        self.assertFalse(default_storage.exists(name))

    def test_a_cascade_delete_still_removes_the_file(self):
        """`User` удаляется, `Story` уходит каскадом — сигнал обязан
        сработать и для строки, которую в коде никто явно не удалял: это
        и есть довод в пользу сигналов, а не ручного вызова в
        `queries/write.py` (`core/counters.py` решает ту же задачу для
        счётчиков по той же причине)."""
        author = factories.user()
        story = factories.story(author=author)
        story.cover = factories.tiny_image()
        story.save()
        name = story.cover.name
        author.delete()
        self.assertFalse(default_storage.exists(name))
