"""Админка — единственный инструмент модерации в MVP (DEC-23).

Кастомного UI не будет до V2, значит стандартный admin обязан уметь всё,
что модератору нужно делать руками. Пока это справочники и путь тега
(BR-TAG-03); статусы произведений приедут со своим этапом (docs/19).
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import BlockedTagPattern, Genre, Tag, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Стандартная админка пользователя без `first_name` / `last_name`.

    Эти поля у модели убраны (см. `core.models.User`), поэтому наборы
    полей приходится перечислить заново: унаследованные ссылаются на
    несуществующие колонки и роняют страницу.
    """

    list_display = ('username', 'public_name', 'name', 'is_staff', 'date_joined')
    list_filter = ('is_staff', 'is_superuser', 'is_active')
    search_fields = ('username', 'name', 'pen_name', 'email')
    ordering = ('username',)

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Аты-жөні', {
            'fields': ('name', 'pen_name', 'bio', 'email'),
            'description': '«Нақты аты» көпшілікке көрінбейді — оны '
                           'модерация мен байқау қазылары ғана көреді.',
        }),
        ('Рұқсаттар', {'fields': ('is_active', 'is_staff', 'is_superuser',
                                  'groups', 'user_permissions')}),
        ('Маңызды күндер', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2'),
        }),
    )

    @admin.display(description='көпшілікке')
    def public_name(self, obj):
        return obj.public_name


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ('name', 'position', 'slug', 'hue', 'icon')
    list_editable = ('position',)
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('position',)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    """Путь тега: pending → accepted | rejected (BR-TAG-03).

    Действия групповые, потому что модерация тегов — это просмотр списка
    новых имён разом, а не заход в карточку каждого.
    """

    list_display = ('name', 'slug', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('name', 'slug')
    actions = ('accept', 'reject')

    @admin.action(description='Қабылдау (accepted)')
    def accept(self, request, queryset):
        updated = queryset.update(status='accepted')
        self.message_user(request, f'{updated} тег қабылданды.')

    @admin.action(description='Қабылдамау (rejected)')
    def reject(self, request, queryset):
        updated = queryset.update(status='rejected')
        self.message_user(request, f'{updated} тег қабылданбады.')


@admin.register(BlockedTagPattern)
class BlockedTagPatternAdmin(admin.ModelAdmin):
    list_display = ('pattern', 'note')
    search_fields = ('pattern',)
