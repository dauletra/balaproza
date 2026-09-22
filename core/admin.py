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

from . import data
from .domain.contests import CONTEST_PHASE_LABELS
from .domain.notifications import MODERATION_OUTCOME_LABELS
from .queries.notifications import notify_award_granted, notify_submission_decided
from .models import (
    AwardGrant,
    BlockedTagPattern,
    BookOfWeek,
    Collection,
    CollectionItem,
    Chapter,
    ChapterPoll,
    ChapterReaction,
    ChapterRevision,
    Contest,
    ContestAward,
    ContestCondition,
    Genre,
    JuryMember,
    ModerationClaim,
    ModerationDecision,
    Notification,
    PortalDay,
    PollOption,
    Report,
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
    групповые: модерация тегов — просмотр списка новых имён разом.

    Отказ спрашивает причину и уходит через `reject_tags`, а не через
    `queryset.update()`: решение о теге это ещё и снятие его с работ, и
    весть автору — порознь они оставляли обещание BR-TAG-03
    выполненным наполовину. Промежуточная страница — та же механика, что
    у решения по работе: форма списка текста не передаёт.
    """

    list_display = ('name', 'slug', 'status', 'usage', 'created_at')
    list_filter = ('status',)
    search_fields = ('name', 'slug')
    actions = ('accept', 'reject')

    @admin.display(description='жұмыстарда')
    def usage(self, obj):
        """Скольких работ коснётся решение. Число тут не украшение: отказ
        снимает тег со всех разом, и знать об этом надо до нажатия."""
        return obj.stories.count()

    @admin.action(description='Қабылдау (accepted)')
    def accept(self, request, queryset):
        updated = data.accept_tags(queryset)
        self.message_user(request, f'{updated} тег қабылданды.')

    @admin.action(description='Қабылдамау (rejected)')
    def reject(self, request, queryset):
        """Причина обязательна (BR-11, BR-TAG-03): «нельзя» без «почему»
        автор исправить не может."""
        error = ''
        if 'apply' in request.POST:
            reason = (request.POST.get('reason') or '').strip()
            if not reason:
                error = 'Себепті жазу керек: онсыз автор неге екенін білмейді.'
            else:
                changed, told = data.reject_tags(queryset, reason)
                self.message_user(
                    request,
                    f'{changed} тег қабылданбады, {told} жұмыстан алынып '
                    f'тасталды, авторларға хабарланды.',
                    messages.SUCCESS)
                return None

        return render(request, 'admin/core/tag/reject.html', {
            **self.admin_site.each_context(request),
            'title': 'Тегті қабылдамау',
            'opts': self.model._meta,
            'tags': queryset,
            # Сколько работ задето — то же число, что в колонке списка, но
            # здесь оно про весь выбор разом.
            'affected': StoryTag.objects.filter(tag__in=queryset).count(),
            'error': error,
            'reason': request.POST.get('reason', ''),
            'action': 'reject',
            'selected': queryset.values_list('pk', flat=True),
        })


@admin.register(BlockedTagPattern)
class BlockedTagPatternAdmin(admin.ModelAdmin):
    list_display = ('pattern', 'note')
    search_fields = ('pattern',)


class ChapterInline(admin.TabularInline):
    """Главы внутри произведения: по отдельности их не ищут. `char_count`
    только для чтения — он считается из текста при сохранении.

    `published_revision` показывается, но не редактируется: подменить
    опубликованный текст руками значит опубликовать непроверенное — то
    самое, ради чего ревизии и заведены (BR-79). Меняет её только решение
    модератора.
    """

    model = Chapter
    extra = 0
    fields = ('number', 'title', 'char_count', 'published_revision')
    readonly_fields = ('char_count', 'published_revision')
    ordering = ('number',)
    show_change_link = True


class ChapterRevisionInline(admin.TabularInline):
    """История главы и её очередь. Текст ревизии здесь и читает модератор:
    в списке глав лежат номера, а решение принимается по написанному."""

    model = ChapterRevision
    extra = 0
    fields = ('state', 'title', 'body', 'char_count', 'submitted_at',
              'decided_at')
    readonly_fields = ('char_count', 'submitted_at', 'decided_at')
    ordering = ('-created_at',)


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

    **Решения здесь больше не принимаются** — для них есть раздел
    `/moderation/` (DEC-71), где рядом с кнопками лежит то, по чему решают:
    текст поданного, сравнение с опубликованным и прошлые замечания.
    Действия списка остались запасным путём на случай, когда раздел
    недоступен, и ведут в ту же дверь `Story.apply_moderation`.

    Поле статуса остаётся редактируемым, но с BR-79 оно пересчитывается:
    правка руками держится до следующего пересчёта, о чём говорит
    предупреждение.
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
            'fields': ('status', 'completed_by_author', 'is_editorial_pick'),
            'description': 'Модерация шешімі — тізімдегі әрекет арқылы: '
                           'сонда ғана автор хабарлама алады (BR-11). '
                           '«Мәртебесі» енді бөлімдерден есептеледі (BR-79): '
                           'қолмен қойылғаны келесі есептеуде қайта жазылады. '
                           '«Аяқталды» — автордың сөзі, модерацияның нәтижесі '
                           'емес.',
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
        # Очередь — работы с **поданной ревизией** (BR-79), а не со
        # значением статуса: у публичного сериала, дописавшего главу,
        # статус остаётся публичным, и фильтр по нему прятал бы от
        # модератора ровно то, что ему прислали.
        queue = queryset.filter(chapter__revisions__state='pending').distinct()
        skipped = queryset.count() - queue.count()

        error = ''
        if 'apply' in request.POST:
            reason = (request.POST.get('reason') or '').strip()
            if outcome != 'approved' and not reason:
                error = 'Себепті жазу керек: онсыз автор нені түзетерін білмейді.'
            else:
                done = [story.apply_moderation(outcome, reason,
                                               moderator=request.user)
                        for story in queue]
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
    list_display = ('story', 'number', 'title', 'char_count', 'published')
    list_filter = ('story',)
    search_fields = ('title', 'story__title')
    readonly_fields = ('char_count', 'published_revision')
    inlines = (ChapterRevisionInline, ChapterReactionInline)

    @admin.display(description='жарияланған', boolean=True)
    def published(self, obj):
        return obj.is_published


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

    def save_model(self, request, obj, form, change):
        """Присуждение — единственное место, где рождается победа (DEC-46):
        отдельного статуса заявки под неё нет. Уведомление уходит только
        на само присуждение, не на правку комментария к нему."""
        super().save_model(request, obj, form, change)
        if not change:
            notify_award_granted(obj)


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

    def save_model(self, request, obj, form, change):
        """Решение по заявке автор узнаёт от платформы, а не проверками
        страницы конкурса (BR-41).

        Уведомление — на **смену** статуса, а не на каждое сохранение:
        поправленный комментарий жюри не повод сообщать «өтінімің
        қабылданды» второй раз. Тот же приём, что у `StoryAdmin`, где
        ручная правка статуса работы разбирается по `form.changed_data`.
        """
        decided = change and 'status' in form.changed_data
        super().save_model(request, obj, form, change)
        if decided:
            notify_submission_decided(obj)


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

    # `pushed_at` рядом с `read` отвечает на вопрос «дошло ли вообще»:
    # это два разных канала, и событие бывает отправленным в Telegram и
    # непрочитанным на сайте. Пустая колонка у свежих строк — норма,
    # рассылка идёт раз в минуту; пустая у старых — повод смотреть, жива
    # ли `push_notifications`.
    list_display = ('user', 'kind', 'outcome_label', 'short_text',
                    'created_at', 'read', 'pushed_at')
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


@admin.register(ModerationDecision)
class ModerationDecisionAdmin(admin.ModelAdmin):
    """Журнал решений — только на чтение (BR-82). Акт человека не правится
    задним числом: исправленный, он рассказывал бы о решении, которого
    никто не принимал, — то же правило, что у `Notification`."""

    list_display = ('story', 'outcome', 'moderator', 'chapters', 'decided_at')
    list_filter = ('outcome',)
    search_fields = ('story__title', 'moderator__username', 'reason')
    date_hierarchy = 'decided_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ModerationClaim)
class ModerationClaimAdmin(admin.ModelAdmin):
    """«Взял в работу». Живёт минуты и снимается решением; здесь — чтобы
    снять забытую метку, не трогая саму работу."""

    list_display = ('story', 'moderator', 'claimed_at')
    autocomplete_fields = ('story',)


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    """Жалобы (BR-33) — запасной путь для чтения, как у `ModerationDecision`.
    Решение принимается в `/moderation/reports/` (`resolve_report`), а не
    здесь: правка задним числом рассказывала бы о решении, которого никто
    не принимал."""

    list_display = ('reporter', 'story', 'comment', 'reason', 'outcome',
                    'created_at')
    list_filter = ('reason', 'outcome')
    search_fields = ('reporter__username', 'story__title', 'note')
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


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
