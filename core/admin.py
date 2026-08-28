"""Админка — единственный инструмент модерации в MVP (DEC-23).

Стандартный admin обязан уметь всё, что модератор делает руками: решить
судьбу отправленной работы (BR-11), провести тег по его пути (BR-TAG-03),
собрать конкурс со всем составом и загрузить файлы в `media/` (BR-46).

**Чего здесь нет намеренно.** Библиотека, прогресс чтения и подписки —
личные записи читателя, и список чужих полок в админке был бы витриной
персональных данных. Уведомления — только на чтение: их пишет событие.
"""

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.db.models import Count
from django.shortcuts import render

from .domain.contests import CONTEST_PHASE_LABELS
from .domain.notifications import MODERATION_OUTCOME_LABELS
from .models import (
    AwardGrant,
    BlockedTagPattern,
    BookOfWeek,
    Collection,
    CollectionItem,
    Chapter,
    ChapterPoll,
    ChapterReaction,
    Contest,
    ContestAward,
    ContestCondition,
    Genre,
    JuryMember,
    Notification,
    PollOption,
    SchoolLink,
    Story,
    StoryComment,
    StoryTag,
    Submission,
    Tag,
    TimelineStage,
    User,
)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Админка пользователя без `first_name` / `last_name`: поля у модели
    убраны, и унаследованные наборы ссылались бы на несуществующие
    колонки, роняя страницу."""

    list_display = ('username', 'public_name', 'name', 'is_staff', 'date_joined')
    list_filter = ('is_staff', 'is_superuser', 'is_active')
    search_fields = ('username', 'name', 'pen_name', 'email')
    ordering = ('username',)

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Аты-жөні', {
            'fields': ('name', 'pen_name', 'bio', 'avatar', 'age', 'gender', 'email'),
            'description': '«Нақты аты» көпшілікке көрінбейді — оны '
                           'модерация мен байқау қазылары ғана көреді. '
                           '«Жасы»/«Жынысы» — өзі толтырған, құжатпен '
                           'расталмаған (DEC-24).',
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
    """Путь тега: pending → accepted | rejected (BR-TAG-03). Действия
    групповые: модерация тегов — просмотр списка новых имён разом."""

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
    """Главы внутри произведения: по отдельности их не ищут. `char_count`
    только для чтения — он считается из текста при сохранении."""

    model = Chapter
    extra = 0
    fields = ('number', 'title', 'char_count')
    readonly_fields = ('char_count',)
    ordering = ('number',)
    show_change_link = True


class StoryTagInline(admin.TabularInline):
    """Теги работы. `tags` — M2M через `StoryTag` (Ф15, DEC-31) и потому
    не рендерится обычным виджетом в fieldsets — только инлайном."""

    model = StoryTag
    extra = 0
    fields = ('tag', 'created_at')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('tag',)


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    """Карточка работы и рабочий стол модератора (DEC-23, BR-11).

    Решение принимается **действием**, а не правкой поля «мәртебесі»:
    статус, изменённый в форме, ничего не сообщает автору, и работа молча
    возвращается из очереди. Действие меняет статус и пишет уведомление
    одним движением (`Story.apply_moderation`).

    Поле статуса остаётся редактируемым — как путь модератора, когда автор
    недоступен; такая правка сопровождается предупреждением.
    """

    list_display = ('title', 'author', 'status', 'primary_genre',
                    'is_editorial_pick', 'views', 'updated_at')
    list_filter = ('status', 'format', 'is_editorial_pick', 'primary_genre')
    search_fields = ('title', 'slug', 'author__username', 'author__pen_name')
    autocomplete_fields = ('author',)
    prepopulated_fields = {'slug': ('title',)}
    inlines = (ChapterInline, StoryTagInline)
    actions = ('approve', 'send_back', 'reject')
    fieldsets = (
        (None, {'fields': ('title', 'slug', 'author', 'annotation', 'cover')}),
        ('Сипаттамасы', {
            'fields': ('primary_genre', 'secondary_genre',
                       'format', 'audience'),
            'description': '«Жас белгісі» бос болса — автор әлі таңдамаған. '
                           'Оны автордың орнына қоюға болмайды (BR-10b).',
        }),
        ('Модерация', {
            'fields': ('status', 'is_editorial_pick'),
            'description': 'Модерация шешімі — тізімдегі әрекет арқылы: '
                           'сонда ғана автор хабарлама алады (BR-11). '
                           'Мұндағы өріс — аяқталған серияны «Аяқталды» '
                           'деп белгілеу сияқты жағдайлар үшін.',
        }),
        ('Сандар', {
            'fields': ('views', 'recent_views', 'likes', 'comments'),
            'description': 'Уақытша: Ф14 аяқталғанда бұлар сұраныстан '
                           'есептеледі.',
        }),
    )

    # ── Решение модератора (BR-11, BR-72b) ────────────────────────────────

    @admin.action(description='Жариялау (модерациядан өткізу)')
    def approve(self, request, queryset):
        return self._decide(request, queryset, 'approved')

    @admin.action(description='Толықтыруға қайтару')
    def send_back(self, request, queryset):
        return self._decide(request, queryset, 'needs_work')

    @admin.action(description='Қабылдамау (ережеге қайшы)')
    def reject(self, request, queryset):
        return self._decide(request, queryset, 'rejected')

    def _decide(self, request, queryset, outcome):
        """Общий ход всех трёх решений: спросить причину и применить.

        Промежуточная страница нужна ради самой причины: без неё
        отрицательное решение нельзя записать (BR-11), а форма списка
        передать текст не умеет. Страница одна на все три кнопки — две
        механики рядом читались бы как разные по последствиям действия.
        """
        queue = queryset.filter(status='OnModeration')
        skipped = queryset.count() - queue.count()

        error = ''
        if 'apply' in request.POST:
            reason = (request.POST.get('reason') or '').strip()
            if outcome != 'approved' and not reason:
                error = 'Себепті жазу керек: онсыз автор нені түзетерін білмейді.'
            else:
                done = [story.apply_moderation(outcome, reason) for story in queue]
                self.message_user(
                    request,
                    f'{len(done)} шығарма: «{MODERATION_OUTCOME_LABELS[outcome]}». '
                    f'Авторларға хабарлама жіберілді.',
                    messages.SUCCESS)
                if skipped:
                    self._warn_skipped(request, skipped)
                return None

        if not queue:
            self._warn_skipped(request, skipped)
            return None

        return render(request, 'admin/core/story/moderation.html', {
            **self.admin_site.each_context(request),
            'title': MODERATION_OUTCOME_LABELS[outcome],
            'opts': self.model._meta,
            'stories': queue,
            'outcome': outcome,
            'outcome_label': MODERATION_OUTCOME_LABELS[outcome],
            'reason_required': outcome != 'approved',
            'error': error,
            'reason': request.POST.get('reason', ''),
            'action': request.POST.get('action', ''),
            'selected': queryset.values_list('pk', flat=True),
        })

    def _warn_skipped(self, request, skipped):
        """Работы, которых решение не касается, названы числом, а не молча
        пропущены: иначе модератор считает решёнными все выбранные."""
        if skipped:
            self.message_user(
                request,
                f'{skipped} шығарма өткізілді: модерацияға жіберілмеген. '
                f'Шешім автор өзі жібергенге ғана қабылданады.',
                messages.WARNING)

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
                'Модерация шешімін тізімдегі әрекет арқылы қабылда (BR-11).',
                messages.WARNING)


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
    """Конкурс заводится тремя датами, остальное считается. Полей «статус»,
    «осталось дней» и «число заявок» в форме нет и быть не может: они
    выводятся (BR-40a)."""

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

    def get_queryset(self, request):
        # Число заявок в колонке — аннотация, которую подхватывает
        # `Contest.submissions`, а не `COUNT` на каждую строку списка.
        return super().get_queryset(request).annotate(
            submission_count=Count('submission_set'))

    @admin.display(description='кезеңі')
    def phase_label(self, obj):
        return CONTEST_PHASE_LABELS[obj.phase]

    @admin.display(description='өтінім', ordering='submission_count')
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
    list_display = ('author', 'contest', 'story', 'submitted_on', 'status',
                    'ai_declaration')
    list_filter = ('status', 'contest', 'ai_declaration')
    search_fields = ('author__username', 'story__title')
    autocomplete_fields = ('author', 'story')
    # Ответы формы подачи (DEC-21/DEC-24) — жюри и модератору видны,
    # автор их повторно не редактирует.
    readonly_fields = ('ai_declaration', 'age_confirmed', 'rules_confirmed')


class CollectionItemInline(admin.TabularInline):
    """Состав подборки. Порядок редакционный: первые три идут на обложку,
    поэтому инлайн сортируется по `position`, а не по порядку вставки."""

    model = CollectionItem
    extra = 1
    ordering = ('position',)
    autocomplete_fields = ('story',)


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    """Жинақ — редакционная кураторская работа (DEC-31). Пользовательских
    подборок нет: личное хранение — это «Кітапхана»."""

    list_display = ('name', 'position', 'curator', 'count')
    list_editable = ('position',)
    prepopulated_fields = {'slug': ('name',)}
    inlines = (CollectionItemInline,)

    def get_queryset(self, request):
        # `Collection.count` считает `len(item_set.all())` — с prefetch это
        # один запрос на весь список вместо одного на подборку.
        return super().get_queryset(request).prefetch_related('item_set')

    @admin.display(description='шығарма саны')
    def count(self, obj):
        return obj.count


@admin.register(BookOfWeek)
class BookOfWeekAdmin(admin.ModelAdmin):
    """Отдельной записью на неделю, а не флагом у произведения: флаг
    пришлось бы снимать руками, и главная показала бы двух сразу."""

    list_display = ('published_on', 'story')
    autocomplete_fields = ('story',)


@admin.register(StoryComment)
class StoryCommentAdmin(admin.ModelAdmin):
    """Модерации комментариев в MVP ровно столько: прочитать и удалить."""

    list_display = ('author', 'story', 'chapter_number', 'short_text',
                    'created_at')
    list_filter = ('story',)
    search_fields = ('text', 'author__username')
    autocomplete_fields = ('author', 'story', 'parent')

    @admin.display(description='мәтіні')
    def short_text(self, obj):
        return obj.text[:60]


class PollOptionInline(admin.TabularInline):
    """Варианты опроса. Голоса — колонка, править их руками можно, но не
    нужно: это данные читателей, а не редакции."""

    model = PollOption
    extra = 2
    ordering = ('position',)


@admin.register(ChapterPoll)
class ChapterPollAdmin(admin.ModelAdmin):
    """Опрос под главой (FR-STORY-13, DEC-33). Инструмент автора, а не
    модерации, — здесь он как запасной путь завести и закрыть опрос."""

    list_display = ('chapter', 'question', 'is_closed')
    inlines = (PollOptionInline,)

    @admin.display(description='жабылған', boolean=True)
    def is_closed(self, obj):
        """Закрыт ли опрос — выводится из наличия следующей главы
        (BR-POLL-05), фильтровать по нему нельзя: колонки нет."""
        return obj.closed


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """Лента событий — только на чтение: уведомление пишет событие, и
    исправленное руками оно рассказывало бы автору о решении, которого
    никто не принимал. Модератору здесь нужно видеть, что автор получил."""

    list_display = ('user', 'kind', 'outcome_label', 'short_text',
                    'created_at', 'read')
    list_filter = ('kind', 'outcome', 'read')
    search_fields = ('user__username', 'text')
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description='нәтижесі')
    def outcome_label(self, obj):
        return MODERATION_OUTCOME_LABELS.get(obj.outcome, '')

    @admin.display(description='оқиға')
    def short_text(self, obj):
        return obj.text[:60]


@admin.register(SchoolLink)
class SchoolLinkAdmin(admin.ModelAdmin):
    list_display = ('title', 'channel', 'subtitle', 'position')
    list_editable = ('position',)
