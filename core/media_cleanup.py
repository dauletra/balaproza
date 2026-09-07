"""Растровые поля держат актуальный файл в storage (BR-86).

Сигналы `pre_save`/`post_delete`, а не ручной вызов в `queries/write.py`/
`queries/profile.py` — по той же причине, что и у `core/counters.py`:
массовое удаление в админке и каскад от удаления `User` идут в обход
доменных функций, и ручной вызов там ничего не увидит. `poster`
(`Contest`) и `image` (`ContestAward`) вообще грузятся только из
`admin.py` — правки самой админки это не требует ни строки.

Раньше замена файла оставляла старый висеть в `media/` навсегда (Django
добавляет суффикс к имени вместо перезаписи), а удаление объекта не
трогало его файл вовсе (S8 в AUDIT-WRITE-FLOW.md).
"""

from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

from .models import Contest, ContestAward, Story, User
from .uploads import _ext, resize_raster_image

RASTER_FIELDS = {
    Story: 'cover',
    User: 'avatar',
    Contest: 'poster',
    ContestAward: 'image',
}


@receiver(pre_save, sender=Story)
@receiver(pre_save, sender=User)
@receiver(pre_save, sender=Contest)
@receiver(pre_save, sender=ContestAward)
def _process_and_replace_raster_field(sender, instance, **kwargs):
    """Пережать новый файл и убрать старый — до того, как поле само себя
    сохранит в storage (сигнал успевает раньше `FileField.pre_save`).

    Сверка идёт с тем, что **сейчас в базе** (`values_list` одним
    запросом), а не с тем, что лежит в объекте до правки: только так
    отличимо «поле не трогали» от «поле заменили на то же значение» —
    второго не бывает у файлов (новая загрузка всегда новое имя), а
    первое не должно ни пережимать повторно, ни трогать файл.
    """
    field_name = RASTER_FIELDS[sender]
    new_file = getattr(instance, field_name)

    old_name = ''
    if instance.pk:
        old_name = (sender.objects.filter(pk=instance.pk)
                   .values_list(field_name, flat=True).first()) or ''
    new_name = new_file.name if new_file else ''
    if old_name == new_name:
        return

    if old_name:
        new_file.storage.delete(old_name)
    if new_file:
        setattr(instance, field_name, resize_raster_image(new_file, _ext(new_name)))


@receiver(post_delete, sender=Story)
@receiver(post_delete, sender=User)
@receiver(post_delete, sender=Contest)
@receiver(post_delete, sender=ContestAward)
def _delete_raster_field_file(sender, instance, **kwargs):
    """Убрать файл при удалении объекта — включая массовое удаление и
    каскад: подписанный `post_delete` выключает быстрый путь
    `Collector.can_fast_delete` и Django шлёт сигнал на каждый объект."""
    file = getattr(instance, RASTER_FIELDS[sender])
    if file:
        file.storage.delete(file.name)
