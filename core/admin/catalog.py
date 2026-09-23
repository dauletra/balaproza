"""Справочники каталога: жанры, теги с их путём, стоп-слова, подборки и
книга недели."""

import re
from functools import cache

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.db.models import Count
from django.shortcuts import render

from .. import data
from ..models import (
    BlockedTagPattern,
    BookOfWeek,
    Collection,
    CollectionItem,
    Genre,
    StoryTag,
    Tag,
)


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
    иконка необязательна, у подборки — обязательна.

    У того, кто только смотрит, полей в форме нет вовсе — все они только
    на чтение, — и подменять нечего."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields.get('icon')
        if field is None:
            return
        choices = [(name, name) for name in _sprite_icons()]
        if not field.required:
            choices.insert(0, ('', '—'))
        self.fields['icon'] = forms.ChoiceField(
            label=field.label, required=field.required, choices=choices,
            help_text='Сайттағы иконкалар жиынтығынан.')


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

    list_display = ('name', 'slug', 'status', 'usage', 'created_at')
    list_filter = ('status',)
    search_fields = ('name', 'slug')
    readonly_fields = ('status',)
    actions = ('accept', 'reject')

    def has_delete_permission(self, request, obj=None):
        return False

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

    # Решение по тегу — правка: у того, кто только смотрит, действий нет.
    @admin.action(description='Қабылдау (accepted)',
                  permissions=('change',))
    def accept(self, request, queryset):
        tags = list(queryset)
        updated = data.accept_tags(tags)
        self._log(request, tags, 'Қабылданды.')
        self.message_user(request, f'{updated} тег қабылданды.')

    @admin.action(description='Қабылдамау (rejected)',
                  permissions=('change',))
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
