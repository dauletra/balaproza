"""Аккаунты."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from ..models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Админка пользователя без `first_name` / `last_name`: поля у модели
    убраны, и унаследованные наборы ссылались бы на несуществующие
    колонки, роняя страницу."""

    list_display = ('username', 'public_name', 'is_staff', 'date_joined')
    list_filter = ('is_staff', 'is_superuser', 'is_active')
    search_fields = ('username', 'pen_name', 'email')
    ordering = ('username',)

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Аты-жөні', {
            'fields': ('pen_name', 'bio', 'avatar', 'email'),
            'description': 'Нақты аты-жөні, жасы және жынысы сайтта мүлде '
                           'сақталмайды: балалар алаңында әр артық өріс — '
                           'қорғауға тиіс міндеттеме.',
        }),
        ('Хабарламалар', {
            'fields': ('telegram_push', 'push_moderation', 'push_response',
                       'push_new_chapter'),
            'description': '«Telegram-хабарлама» — арнаның өзі: өшірілген '
                           'болса, бот бұғатталған. Қалған үшеуі — автордың '
                           'таңдауы. Сайттағы хабарламалар бәрібір қалады.',
        }),
        ('Кіру', {
            'fields': ('telegram_id', 'terms_accepted_at'),
            'description': 'Telegram ID — аккаунтты қайтару рәсімі осы: '
                           'өтініш тексерілгеннен кейін аккаунтқа жаңа '
                           'Telegram байланады. ID сайтта ешқайда '
                           'көрсетілмейді; басқа аккаунтта тұрғанын форма '
                           'қабылдамайды. Келісім күні — адамның өз әрекеті, '
                           'оны қолмен қоюға болмайды.',
        }),
        ('Рұқсаттар', {'fields': ('is_active', 'is_staff', 'is_superuser',
                                  'groups', 'user_permissions')}),
        ('Маңызды күндер', {'fields': ('last_login', 'date_joined')}),
    )
    readonly_fields = ('terms_accepted_at',)
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2'),
        }),
    )

    @admin.display(description='көпшілікке')
    def public_name(self, obj):
        return obj.public_name
