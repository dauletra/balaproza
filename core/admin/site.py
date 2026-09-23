"""Ссылки школы и суточные снимки портала."""

from django.contrib import admin

from ..models import PortalDay, SchoolLink


@admin.register(SchoolLink)
class SchoolLinkAdmin(admin.ModelAdmin):
    list_display = ('title', 'channel', 'subtitle', 'position')
    list_editable = ('position',)


@admin.register(PortalDay)
class PortalDayAdmin(admin.ModelAdmin):
    """История суточных снимков — только на чтение, как лента событий.

    Строка это акт: «столько нас было в этот день». Исправленная руками,
    она перестаёт им быть, а восстановить её нечем — накопленные
    счётчики убывают, журнал оқылым живёт две недели.

    Страница сводки показывает сегодня и неделю назад; сюда ходят, когда
    нужно больше двух точек — посмотреть, тянется ли что-то месяц.
    """

    list_display = ('day', 'readers', 'returning_readers', 'returning_share',
                    'signed_up', 'published', 'public', 'overdue')
    date_hierarchy = 'day'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description='қайта келгені, %')
    def returning_share(self, obj):
        return obj.returning_share
