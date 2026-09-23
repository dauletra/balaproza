"""Конкурс со всем составом, награды и заявки."""

from django.contrib import admin
from django.db.models import Count

from ..domain.contests import CONTEST_PHASE_LABELS
from ..queries.notifications import notify_award_granted, notify_submission_decided
from ..models import (
    AwardGrant,
    Contest,
    ContestAward,
    ContestCondition,
    JuryMember,
    Submission,
    TimelineStage,
)


class ContestConditionInline(admin.TabularInline):
    model = ContestCondition
    extra = 1


class TimelineStageInline(admin.TabularInline):
    """Этапы. Состояние («идёт», «прошёл») не редактируется — оно
    выводится из дат, и поля под него нет намеренно."""

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
    выводятся."""

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
                           'қоятын өріс жоқ.',
        }),
        ('Шарттар', {'fields': ('min_chars', 'max_chars', 'min_age', 'max_age'),
                     'description': 'Жас шегі — осы байқаудың талабы. '
                                    'Платформаның өз цензы жоқ.'}),
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
    """Присуждение — акт жюри, поэтому оно вводится, а не вычисляется.
    Номинация того же конкурса и допущенная работа — проверка
    `AwardGrant.clean`, форма показывает её у своего поля."""

    list_display = ('contest', 'award', 'story', 'author')
    list_filter = ('contest',)
    list_select_related = ('contest', 'award', 'story__author')
    autocomplete_fields = ('story',)

    @admin.display(description='авторы')
    def author(self, obj):
        return obj.author

    def save_model(self, request, obj, form, change):
        """Присуждение — единственное место, где рождается победа:
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
    list_select_related = ('author', 'contest', 'story')
    search_fields = ('author__username', 'story__title')
    autocomplete_fields = ('author', 'story')
    # Ответы формы подачи — жюри и модератору видны,
    # автор их повторно не редактирует. Кто, куда, что и когда подал —
    # тоже: заявка, переписанная на другого автора или другую работу,
    # несла бы чужие ответы о возрасте и AI-помощи.
    readonly_fields = ('contest', 'author', 'story', 'submitted_on',
                       'ai_declaration', 'age_confirmed', 'rules_confirmed')

    def has_add_permission(self, request):
        """Заявку подаёт автор: заведённая здесь несла бы ответы о возрасте
        и AI-помощи, которых он не давал."""
        return False

    def save_model(self, request, obj, form, change):
        """Решение по заявке автор узнаёт от платформы, а не проверками
        страницы конкурса.

        Уведомление — на **смену** статуса, а не на каждое сохранение:
        поправленный комментарий жюри не повод сообщать «өтінімің
        қабылданды» второй раз. Тот же приём, что у `StoryAdmin`, где
        ручная правка статуса работы разбирается по `form.changed_data`.
        """
        decided = change and 'status' in form.changed_data
        super().save_model(request, obj, form, change)
        if decided:
            notify_submission_decided(obj)
