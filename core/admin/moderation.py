"""Журналы модерации — на чтение: решение принимается в `/moderation/`."""

from django.contrib import admin
from django.core.exceptions import PermissionDenied

from ..models import ModerationClaim, ModerationDecision, Report


@admin.register(ModerationDecision)
class ModerationDecisionAdmin(admin.ModelAdmin):
    """Журнал решений — только на чтение. Акт человека не правится
    задним числом: исправленный, он рассказывал бы о решении, которого
    никто не принимал, — то же правило, что у `Notification`.

    И не удаляется: из последнего акта выводится статус работы
    (`Story.refresh_status`) и замечание автору в рабочем месте. Удалённый
    возврат молча делал бы возвращённую работу черновиком.

    Запрет — на двери, а не в `has_delete_permission`: права на удаление
    спрашивает и каскад. Отказ там остановил бы удаление работы или
    человека целиком, а акт по несуществующей работе хранить незачем.
    """

    list_display = ('story', 'outcome', 'moderator', 'chapters', 'decided_at')
    list_filter = ('outcome',)
    list_select_related = ('story', 'moderator')
    search_fields = ('story__title', 'moderator__username', 'reason')
    date_hierarchy = 'decided_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions

    def delete_view(self, request, object_id, extra_context=None):
        raise PermissionDenied

    def change_view(self, request, object_id, form_url='', extra_context=None):
        return super().change_view(request, object_id, form_url,
                                   {**(extra_context or {}),
                                    'show_delete': False})


@admin.register(ModerationClaim)
class ModerationClaimAdmin(admin.ModelAdmin):
    """«Взял в работу». Живёт минуты и снимается решением; здесь — чтобы
    снять забытую метку, не трогая саму работу."""

    list_display = ('story', 'moderator', 'claimed_at')
    list_select_related = ('story', 'moderator')

    def has_add_permission(self, request):
        # Метку ставит сам модератор кнопкой в `/moderation/`.
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    """Жалобы — запасной путь для чтения, как у `ModerationDecision`.
    Решение принимается в `/moderation/reports/` (`resolve_report`), а не
    здесь: правка задним числом рассказывала бы о решении, которого никто
    не принимал."""

    list_display = ('reporter', 'story', 'comment', 'reason', 'outcome',
                    'created_at')
    list_filter = ('reason', 'outcome')
    list_select_related = ('reporter', 'story', 'comment__author')
    search_fields = ('reporter__username', 'story__title', 'note',
                     'resolution')
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
