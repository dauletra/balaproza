"""Работы и главы — правка того, что не решает модератор: состав,
порядок, удаление."""

from django.contrib import admin, messages
from django.db.models import Exists, OuterRef

from .. import data
from ..models import (
    Chapter,
    ChapterPoll,
    ChapterReaction,
    ChapterRevision,
    PollOption,
    Story,
    StoryTag,
    Tag,
)


# Подсказка к полям, которые пересчитываются по строкам: правка руками
# исчезла бы наутро, поэтому они только на чтение.
_RECOUNTED = ('Бұл сандар жолдардан есептеледі және тәулік сайын қайта '
              'саналады — қолмен түзету келесі таңда өшер еді.')


class ChapterInline(admin.TabularInline):
    """Главы внутри произведения: по отдельности их не ищут. `char_count`
    только для чтения — он считается из текста при сохранении.

    `published_revision` показывается, но не редактируется: подменить
    опубликованный текст руками значит опубликовать непроверенное — то
    самое, ради чего ревизии и заведены. Меняет её только решение
    модератора.

    Номер, добавление и удаление — тоже не здесь. Номера держат контиг,
    а удаление главы смыкает оставшиеся, переводит её пікірлер в общие и
    пересчитывает статус работы (`data.delete_chapter`) — галочка
    «өшіру» в инлайне сделала бы только первое из четырёх. Удалить главу
    можно с её собственной карточки, и там это делает та же функция, что
    у автора.
    """

    model = Chapter
    extra = 0
    fields = ('number', 'title', 'char_count', 'published_revision')
    readonly_fields = ('number', 'char_count', 'published_revision')
    ordering = ('number',)
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ChapterRevisionInline(admin.TabularInline):
    """История главы и её очередь — только на чтение.

    Ревизия — то, по чему решает модератор, и то, что видит читатель.
    Правленная здесь поданная подменила бы текст, который одобрят;
    правленная опубликованная — выложила бы непроверенное; `state`,
    переставленный руками, публиковал бы без решения. Удалить нельзя тоже:
    у опубликованной связь `SET_NULL` снимет текст с публикации, у поданной
    пропадёт место в очереди."""

    model = ChapterRevision
    extra = 0
    fields = ('state', 'title', 'body', 'char_count', 'submitted_at',
              'decided_at')
    readonly_fields = fields
    ordering = ('-created_at',)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class StoryTagInline(admin.TabularInline):
    """Теги работы. `tags` — M2M через `StoryTag` и потому
    не рендерится обычным виджетом в fieldsets — только инлайном.

    Отклонённый тег сюда не ставится: отказ снял его со всех работ и
    сообщил авторам, и вернуть его руками значило бы тихо отменить
    решение."""

    model = StoryTag
    extra = 0
    fields = ('tag', 'created_at')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('tag',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'tag':
            kwargs['queryset'] = Tag.objects.exclude(status='rejected')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    """Карточка работы: редакционная правка, но не решение.

    **Решения здесь не принимаются.** Для них есть раздел
    `/moderation/`, где рядом с кнопками лежит то, по чему решают:
    текст поданного, сравнение с опубликованным и прошлые замечания.
    Действия списка, повторявшие эти три кнопки, сняты: дубль ходил в ту
    же дверь `Story.apply_moderation`, то есть расхождения в поведении
    дать не мог, — но каждая правка модерации трогала два экрана и два
    набора тестов, а показать модератору текст он всё равно не умел.

    Поле статуса остаётся редактируемым, но пересчитывается по главам:
    правка руками держится до следующего пересчёта, о чём говорит
    предупреждение.
    """

    list_display = ('title', 'author', 'status', 'primary_genre',
                    'is_editorial_pick', 'views', 'updated_at')
    list_filter = ('status', 'format', 'is_editorial_pick', 'primary_genre')
    list_select_related = ('author', 'primary_genre')
    search_fields = ('title', 'slug', 'author__username', 'author__pen_name')
    autocomplete_fields = ('author',)
    prepopulated_fields = {'slug': ('title',)}
    # «Жас белгісі» — выбор автора, и подсказка раздела запрещает ставить
    # его за автора: запрет живёт в форме, а не только в словах.
    readonly_fields = ('audience', 'views', 'recent_views', 'likes',
                       'comments')
    inlines = (ChapterInline, StoryTagInline)
    fieldsets = (
        (None, {'fields': ('title', 'slug', 'author', 'annotation', 'cover')}),
        ('Сипаттамасы', {
            'fields': ('primary_genre', 'secondary_genre',
                       'format', 'audience'),
            'description': '«Жас белгісі» бос болса — автор әлі таңдамаған. '
                           'Оны автордың орнына қоюға болмайды.',
        }),
        ('Модерация', {
            'fields': ('status', 'completed_by_author', 'is_editorial_pick'),
            'description': 'Модерация шешімі мұнда емес, «Модерация» '
                           'бөлімінде (жоғарыдағы сілтеме): сонда ғана автор '
                           'хабарлама алады. «Мәртебесі» бөлімдерден '
                           'есептеледі: қолмен қойылғаны келесі есептеуде '
                           'қайта жазылады. «Аяқталды» — автордың сөзі, '
                           'модерацияның нәтижесі емес.',
        }),
        ('Сандар', {
            'fields': ('views', 'recent_views', 'likes', 'comments'),
            'description': _RECOUNTED,
        }),
    )

    def save_model(self, request, obj, form, change):
        """Ручная правка статуса — не модерация, и об этом говорится вслух:
        уведомление пишет только `apply_moderation`, а молча работа ушла бы
        из очереди, и автор об этом не узнал."""
        left_moderation = (
            change and 'status' in form.changed_data
            and form.initial.get('status') == 'OnModeration'
        )
        super().save_model(request, obj, form, change)
        if left_moderation:
            self.message_user(
                request,
                'Мәртебе қолмен өзгертілді — автор хабарлама алмады. '
                'Модерация шешімін «Модерация» бөлімінде қабылда.',
                messages.WARNING)


class ChapterReactionInline(admin.TabularInline):
    """Агрегат по голосам читателей — только на чтение: суточная сверка
    пересчитывает его по строкам `ChapterReactionVote`."""

    model = ChapterReaction
    extra = 0
    fields = ('kind', 'count')
    readonly_fields = fields
    ordering = ('kind',)

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    """Рабочая копия главы правится — читатель видит не её, а
    опубликованную ревизию. Фильтра по работе нет: выпадающий список всех
    работ портала — не фильтр, работа ищется поиском.

    Остальное — путь автора, и здесь его не повторяют. Главу не заводят
    (номер, порядок и ревизия появляются в рабочем месте автора), не
    переносят в другую работу вместе с опубликованным текстом и не
    перенумеровывают руками. Удаление идёт через `data.delete_chapter`:
    оставшиеся смыкаются, пікірлер главы становятся общими, статус работы
    пересчитывается."""

    list_display = ('story', 'number', 'title', 'char_count', 'published')
    list_select_related = ('story', 'published_revision')
    search_fields = ('title', 'story__title')
    readonly_fields = ('story', 'number', 'position', 'char_count',
                       'published_revision')
    inlines = (ChapterRevisionInline, ChapterReactionInline)

    def has_add_permission(self, request):
        return False

    def delete_model(self, request, obj):
        data.delete_chapter(obj.story, obj.pk)

    def delete_queryset(self, request, queryset):
        for chapter in queryset.select_related('story'):
            data.delete_chapter(chapter.story, chapter.pk)

    @admin.display(description='жарияланған', boolean=True)
    def published(self, obj):
        return obj.is_published


class PollOptionInline(admin.TabularInline):
    """Варианты опроса. Голоса — агрегат по `PollVote`, данные читателей, а
    не редакции: только на чтение."""

    model = PollOption
    extra = 2
    ordering = ('position',)
    readonly_fields = ('votes',)


@admin.register(ChapterPoll)
class ChapterPollAdmin(admin.ModelAdmin):
    """Опрос под главой. Инструмент автора, а не
    модерации, — здесь он как запасной путь завести и закрыть опрос."""

    list_display = ('chapter', 'question', 'is_closed')
    list_select_related = ('chapter__story',)
    # Глава — поиском, а не списком всех глав портала; у заведённого опроса
    # она не меняется: голоса отданы под этим текстом.
    autocomplete_fields = ('chapter',)
    inlines = (PollOptionInline,)

    def get_readonly_fields(self, request, obj=None):
        return ('chapter',) if obj else ()

    def get_queryset(self, request):
        # Правило `ChapterPoll.closed` одним подзапросом на весь список, а
        # не `EXISTS` на строку.
        return super().get_queryset(request).annotate(
            next_chapter_exists=Exists(Chapter.objects.filter(
                story_id=OuterRef('chapter__story_id'),
                number__gt=OuterRef('chapter__number'))))

    @admin.display(description='жабылған', boolean=True)
    def is_closed(self, obj):
        """Закрыт ли опрос — выводится из наличия следующей главы,
        фильтровать по нему нельзя: колонки нет."""
        return obj.next_chapter_exists
