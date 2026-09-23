"""Комментарии и лента уведомлений — последняя только на чтение."""

from django.contrib import admin

from ..domain.notifications import MODERATION_OUTCOME_LABELS
from ..models import Notification, StoryComment


@admin.register(StoryComment)
class StoryCommentAdmin(admin.ModelAdmin):
    """Прочитать, найти, удалить. Задержанный виден меткой и фильтром,
    но пропускают его в `/moderation/comments/`: там решение правит и
    счётчик работы, а галочка здесь — нет. Поэтому `held` и `likes` только
    на чтение.

    Фильтра по работе нет: выпадающий список всех работ портала — не
    фильтр, работа ищется поиском."""

    list_display = ('author', 'story', 'chapter_number', 'short_text',
                    'held', 'created_at')
    list_filter = ('held',)
    list_select_related = ('author', 'story')
    search_fields = ('text', 'author__username', 'story__title')
    autocomplete_fields = ('author', 'story', 'parent')
    readonly_fields = ('held', 'likes')

    @admin.display(description='мәтіні')
    def short_text(self, obj):
        return obj.text[:60]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """Лента событий — только на чтение: уведомление пишет событие, и
    исправленное руками оно рассказывало бы автору о решении, которого
    никто не принимал. Модератору здесь нужно видеть, что автор получил."""

    # `pushed_at` рядом с `read` отвечает на вопрос «дошло ли вообще»:
    # это два разных канала, и событие бывает отправленным в Telegram и
    # непрочитанным на сайте. Пустая колонка у свежих строк — норма,
    # рассылка идёт раз в минуту; пустая у старых — повод смотреть, жива
    # ли `push_notifications`.
    list_display = ('user', 'kind', 'outcome_label', 'short_text',
                    'created_at', 'read', 'pushed_at')
    list_filter = ('kind', 'outcome', 'read')
    list_select_related = ('user',)
    search_fields = ('user__username', 'text')
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description='нәтижесі')
    def outcome_label(self, obj):
        """Исход есть только у решения модерации. Пустой исход у прочих
        событий — не «Модерацияда»: иначе каждый лайк в списке выглядел
        бы работой, ждущей модератора."""
        if obj.kind != 'moderation':
            return ''
        return MODERATION_OUTCOME_LABELS.get(obj.outcome, '')

    @admin.display(description='оқиға')
    def short_text(self, obj):
        return obj.text[:60]
