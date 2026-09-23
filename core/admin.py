"""Админка — редакционный инструмент: справочники, теги, конкурсы.

Решение по работе принимается не здесь, а в разделе `/moderation/`:
там рядом с кнопками лежит то, по чему решают. Админка отвечает за
остальное — провести тег по его пути, собрать конкурс со всем составом,
загрузить файлы в `media/`.

**Чего здесь нет намеренно.** Библиотека, прогресс чтения и подписки —
личные записи читателя, и список чужих полок в админке был бы витриной
персональных данных. Уведомления — только на чтение: их пишет событие.

Требования к инструменту — `docs/spec.md`, раздел «Админка».
"""

import re
from functools import cache

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.actions import delete_selected
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.db.models import Count, Exists, OuterRef
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


admin.site.site_header = 'Qazaqnovel · редакция'
admin.site.site_title = 'Qazaqnovel'
admin.site.index_title = 'Редакциялық құрал'

# Казахский перевод Django подписывает групповое удаление прошедшим
# временем — «Таңдалған … өшірілді», «выбранные удалены», — и пункт
# меню читается как отчёт о сделанном, а не как действие.
delete_selected.short_description = 'Таңдалғандарды өшіру'

# Подсказка к полям, которые пересчитываются по строкам: правка руками
# исчезла бы наутро, поэтому они только на чтение.
_RECOUNTED = ('Бұл сандар жолдардан есептеледі және тәулік сайын қайта '
              'саналады — қолмен түзету келесі таңда өшер еді.')


@cache
def _sprite_icons() -> tuple[str, ...]:
    """Имена символов спрайта. Иконка жанра и подборки приходит из данных,
    и опечатка в ней рисует пустой квадрат, которого никто не заметит, —
    поэтому поле выбирает из спрайта, а не принимает текст."""
    sprite = settings.BASE_DIR / 'templates' / 'components' / 'icons' / '_sprite.html'
    return tuple(sorted(
        m.removeprefix('icon-')
        for m in re.findall(r'<symbol id="([a-z0-9-]+)"',
                            sprite.read_text(encoding='utf-8'))))


class _IconChoiceForm(forms.ModelForm):
    """Поле `icon` — выбор из спрайта. `required` берётся у модели: у жанра
    иконка необязательна, у подборки — обязательна."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields['icon']
        choices = [(name, name) for name in _sprite_icons()]
        if not field.required:
            choices.insert(0, ('', '—'))
        self.fields['icon'] = forms.ChoiceField(
            label=field.label, required=field.required, choices=choices,
            help_text='Сайттағы иконкалар жиынтығынан.')


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


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    form = _IconChoiceForm
    list_display = ('name', 'position', 'slug', 'hue', 'icon')
    list_editable = ('position',)
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('position',)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    """Путь тега: pending → accepted | rejected. Действия
    групповые: модерация тегов — просмотр списка новых имён разом.

    Отказ спрашивает причину и уходит через `reject_tags`, а не через
    `queryset.update()`: решение о теге это ещё и снятие его с работ, и
    весть автору — порознь они оставляли обещание автору
    выполненным наполовину. Промежуточная страница — та же механика, что
    у решения по работе: форма списка текста не передаёт.

    Статус в карточке только на чтение по той же причине: выбранный там
    `rejected` отклонил бы тег без снятия с работ и без вести автору.

    Удаления нет вовсе. Удалённый тег молча слетает со всех работ — тот же
    отказ без вести, — а отклонённое имя, удалённое из таблицы, снова
    свободно: автор введёт его ещё раз, и оно придёт на проверку заново.
    """

    def has_delete_permission(self, request, obj=None):
        return False

    list_display = ('name', 'slug', 'status', 'usage', 'created_at')
    list_filter = ('status',)
    search_fields = ('name', 'slug')
    readonly_fields = ('status',)
    actions = ('accept', 'reject')

    def get_queryset(self, request):
        # Число работ — аннотацией, а не `COUNT` на каждую строку списка.
        # Не `Tag.usage_count`: тот считает публичные, а отказ снимает тег
        # и с черновиков.
        return super().get_queryset(request).annotate(
            linked_works=Count('storytag'))

    @admin.display(description='жұмыстарда', ordering='linked_works')
    def usage(self, obj):
        """Скольких работ коснётся решение. Число тут не украшение: отказ
        снимает тег со всех разом, и знать об этом надо до нажатия."""
        return obj.linked_works

    def _log(self, request, tags, message):
        """Решение по тегу — в историю админки, как правка карточки.
        Действие списка сам Django не журналирует, и без этой строки на
        вопрос «кто отклонил тег» ответа не было бы нигде: своего акта,
        как `ModerationDecision` у работы, у тега нет."""
        for tag in tags:
            self.log_change(request, tag, message)

    @admin.action(description='Қабылдау (accepted)')
    def accept(self, request, queryset):
        tags = list(queryset)
        updated = data.accept_tags(tags)
        self._log(request, tags, 'Қабылданды.')
        self.message_user(request, f'{updated} тег қабылданды.')

    @admin.action(description='Қабылдамау (rejected)')
    def reject(self, request, queryset):
        """Причина обязательна: «нельзя» без «почему»
        автор исправить не может."""
        error = ''
        if 'apply' in request.POST:
            reason = (request.POST.get('reason') or '').strip()
            if not reason:
                error = 'Себепті жазу керек: онсыз автор неге екенін білмейді.'
            else:
                tags = list(queryset)
                changed, told = data.reject_tags(tags, reason)
                self._log(request, tags, f'Қабылданбады: {reason}')
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
    """Область видна в списке: образец под теги, случайно поставленный на
    комментарии, подвешивает ленту, и заметить это надо до жалоб."""

    list_display = ('pattern', 'scope', 'note')
    list_filter = ('scope',)
    search_fields = ('pattern', 'note')


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


class _PublicStoryForm(forms.ModelForm):
    """Витрина ставит только то, что читатель может открыть.

    Проверяется выбранное сейчас, а не всё подряд: работа, которую сняли
    с публикации уже после того, как её поставили, форму не роняет —
    витрина её и так не покажет (`all_collections`, `book_of_week`), а
    редактор обязан иметь возможность сохранить остальное."""

    def clean_story(self):
        story = self.cleaned_data['story']
        if 'story' in self.changed_data and not story.is_public:
            raise forms.ValidationError(
                'Бұл шығарма жарияланбаған — оқырман оны аша алмайды.')
        return story


class CollectionItemInline(admin.TabularInline):
    """Состав подборки. Порядок редакционный: первые три идут на обложку,
    поэтому инлайн сортируется по `position`, а не по порядку вставки."""

    model = CollectionItem
    form = _PublicStoryForm
    extra = 1
    ordering = ('position',)
    autocomplete_fields = ('story',)


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    """Жинақ — редакционная кураторская работа. Пользовательских
    подборок нет: личное хранение — это «Кітапхана»."""

    form = _IconChoiceForm
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

    form = _PublicStoryForm
    list_display = ('published_on', 'story')
    list_select_related = ('story',)
    autocomplete_fields = ('story',)


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


@admin.register(SchoolLink)
class SchoolLinkAdmin(admin.ModelAdmin):
    list_display = ('title', 'channel', 'subtitle', 'position')
    list_editable = ('position',)


@admin.register(ModerationDecision)
class ModerationDecisionAdmin(admin.ModelAdmin):
    """Журнал решений — только на чтение. Акт человека не правится
    задним числом: исправленный, он рассказывал бы о решении, которого
    никто не принимал, — то же правило, что у `Notification`."""

    list_display = ('story', 'outcome', 'moderator', 'chapters', 'decided_at')
    list_filter = ('outcome',)
    list_select_related = ('story', 'moderator')
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
