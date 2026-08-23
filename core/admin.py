"""Админка — единственный инструмент модерации в MVP (DEC-23).

Кастомного UI не будет до V2, значит стандартный admin обязан уметь всё,
что модератору нужно делать руками. Пока это справочники, путь тега (BR-TAG-03),
карточка произведения и конкурс со всем составом; рабочий процесс
модерации со сменой статуса и уведомлением автору приедет своим этапом
(docs/19 §19.4).
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import (
    AwardGrant,
    BlockedTagPattern,
    Chapter,
    ChapterReaction,
    Contest,
    ContestAward,
    ContestCondition,
    Genre,
    JuryMember,
    Story,
    Submission,
    Tag,
    TimelineStage,
    User,
)


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


class ChapterInline(admin.TabularInline):
    """Главы внутри произведения: по отдельности их не ищут.

    `char_count` только для чтения — он считается из текста при
    сохранении, и вписанное руками число разошлось бы с прогрессом
    чтения «X / N» на странице главы.
    """

    model = Chapter
    extra = 0
    fields = ('number', 'title', 'char_count')
    readonly_fields = ('char_count',)
    ordering = ('number',)
    show_change_link = True


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'status', 'primary_genre',
                    'is_editorial_pick', 'views', 'updated_at')
    list_filter = ('status', 'format', 'is_editorial_pick', 'primary_genre')
    search_fields = ('title', 'slug', 'author__username', 'author__pen_name')
    autocomplete_fields = ('author', 'tags')
    prepopulated_fields = {'slug': ('title',)}
    inlines = (ChapterInline,)
    fieldsets = (
        (None, {'fields': ('title', 'slug', 'author', 'annotation', 'cover')}),
        ('Сипаттамасы', {
            'fields': ('primary_genre', 'secondary_genre', 'tags',
                       'format', 'chapters', 'audience'),
            'description': '«Жас белгісі» бос болса — автор әлі таңдамаған. '
                           'Оны автордың орнына қоюға болмайды (BR-10b).',
        }),
        ('Модерация', {'fields': ('status', 'is_editorial_pick')}),
        ('Сандар', {
            'fields': ('views', 'recent_views', 'likes', 'comments'),
            'description': 'Уақытша: Ф14 аяқталғанда бұлар сұраныстан '
                           'есептеледі (docs/19 §19.3).',
        }),
    )


class ChapterReactionInline(admin.TabularInline):
    model = ChapterReaction
    extra = 0
    ordering = ('kind',)


@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    list_display = ('story', 'number', 'title', 'char_count')
    list_filter = ('story',)
    search_fields = ('title', 'story__title')
    readonly_fields = ('char_count',)
    inlines = (ChapterReactionInline,)


class ContestConditionInline(admin.TabularInline):
    model = ContestCondition
    extra = 1


class TimelineStageInline(admin.TabularInline):
    """Этапы. Состояние («идёт», «прошёл») не редактируется — оно
    выводится из дат, и поля под него нет намеренно (DEC-45)."""

    model = TimelineStage
    extra = 1


class JuryMemberInline(admin.TabularInline):
    model = JuryMember
    extra = 1


class ContestAwardInline(admin.TabularInline):
    """Номинации. Показываются участнику **до** итогов: «вот что получит
    победитель» отвечает на «зачем участвовать» лучше суммы в тенге."""

    model = ContestAward
    extra = 1


@admin.register(Contest)
class ContestAdmin(admin.ModelAdmin):
    """Конкурс заводится тремя датами, остальное считается.

    Полей «статус», «осталось дней» и «число заявок» в форме нет и быть
    не может: они выводятся. Заведённые руками, они врали — «87 өтінім»
    стояло при одной настоящей заявке (BR-40a).
    """

    list_display = ('name', 'phase_label', 'opens_on', 'closes_on',
                    'results_on', 'submissions')
    list_filter = ('series',)
    search_fields = ('name', 'slug', 'series')
    prepopulated_fields = {'slug': ('name',)}
    inlines = (ContestConditionInline, TimelineStageInline,
               JuryMemberInline, ContestAwardInline)
    fieldsets = (
        (None, {'fields': ('name', 'slug', 'subtitle', 'description')}),
        ('Мерзімдер', {
            'fields': ('opens_on', 'closes_on', 'results_on'),
            'description': 'Кезең осы үш күннен есептеледі — оны бөлек '
                           'қоятын өріс жоқ (DEC-45).',
        }),
        ('Шарттар', {'fields': ('min_chars', 'max_chars', 'min_age', 'max_age'),
                     'description': 'Жас шегі — осы байқаудың талабы. '
                                    'Платформаның өз цензы жоқ (DEC-47).'}),
        ('Басқа', {'fields': ('prize_kzt', 'poster', 'series')}),
    )

    @admin.display(description='кезеңі')
    def phase_label(self, obj):
        return obj.phase_label

    @admin.display(description='өтінім')
    def submissions(self, obj):
        return obj.submissions


@admin.register(AwardGrant)
class AwardGrantAdmin(admin.ModelAdmin):
    """Присуждение — акт жюри, поэтому оно вводится, а не вычисляется."""

    list_display = ('contest', 'award', 'story', 'author')
    list_filter = ('contest',)
    autocomplete_fields = ('story',)

    @admin.display(description='авторы')
    def author(self, obj):
        return obj.author


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ('author', 'contest', 'story', 'submitted_on', 'status')
    list_filter = ('status', 'contest')
    search_fields = ('author__username', 'story__title')
    autocomplete_fields = ('author', 'story')
