"""Формы записи: что вправе прийти из браузера.

До этого каждое поле разбиралось руками — `request.POST.get(...)`, свой
список `errors`, свой `RASTER_ONLY` рядом с ним. Три следствия, каждое
проверяемое: лимиты полей жили в модели и повторялись в шаблоне, а в
проверке не участвовали вовсе; валидаторы `FileField` не срабатывали, потому
что вне `ModelForm` их никто не зовёт (SVG отсекался ручным вызовом в двух
местах из трёх); а сообщение об ошибке зависело от того, вспомнил ли автор
кода написать `if`.

Разделение труда осталось прежним: **форма проверяет, `core.data` пишет.**
`form.save()` здесь не зовут — сохранение идёт через фасад, как и всё
остальное, а форма отдаёт `cleaned_data`. Иначе у записи стало бы две двери,
и та, что через форму, обходила бы правила слоя данных.

Тексты ошибок — на «сен» и говорят, что сделать (docs/ui.md).
"""

from django import forms

from .domain.catalog import AUDIENCE_ORDER
from .domain.contests import AI_DECLARATIONS
from .models import Chapter, Genre, Story, User

# Лимит аннотации (BR-16). У поля модели его нет — это `TextField`, — и
# счётчик в шаблоне до этого был единственным местом, где число называлось.
ANNOTATION_MAX = 500


def _genre_field(*, required: bool, message: str):
    """Жанр приходит **слагом**, а не номером строки.

    Это адрес жанра во всём остальном продукте — `/genres/<slug>/`, ось
    каталога, чип на карточке, — и форма не должна быть единственным местом,
    где у него другой ключ. `to_field_name` избавляет и от ручного резолва
    `genre_by_slug` перед проверкой.
    """
    return forms.ModelChoiceField(
        queryset=Genre.objects.all(), to_field_name='slug', required=required,
        error_messages={'required': message, 'invalid_choice': message})


class NewStoryForm(forms.ModelForm):
    """Создание произведения — три поля (FR-WRITE-01).

    Статуса здесь нет и быть не может: новая работа всегда черновик (BR-10),
    и форма сообщает это строкой, а не предлагает выбрать.
    """

    genre_primary = _genre_field(required=True, message='Негізгі жанрды таңда.')

    class Meta:
        model = Story
        fields = ('title', 'format')
        error_messages = {
            'title':  {'required': 'Атауын жаз.'},
            'format': {'required': 'Форматты таңда.',
                       'invalid_choice': 'Форматты таңда.'},
        }


class StorySettingsForm(forms.ModelForm):
    """Баптаулар произведения (FR-WRITE-04).

    Три правила, которые нельзя обойти прямым POST'ом:
    статус выбирает только публичный сериал (BR-10a, BR-11), одночастная
    форма не даётся работе с несколькими написанными главами, а обложка
    обязана быть растром (BR-46) — последнее теперь делает сам валидатор
    поля, а не ручной вызов рядом с ним.

    Работа приходит **аргументом `story`, а не `instance=`**. `ModelForm`
    раскладывает `cleaned_data` по переданному экземпляру ещё до того, как
    вызывающая сторона решит, что с формой делать, — а этот же экземпляр
    уходит в `update_story_settings`. «Не меняем» из `clean_status` так
    доехало бы до базы как пустой статус, стерев `NotPublished`.
    """

    # Не поля модели: теги приходят строкой из `tag_input` и резолвятся
    # слоем данных (pending → accepted, BR-TAG-03), жанры — слагами.
    tags = forms.CharField(required=False)
    genre_primary = _genre_field(required=True, message='Негізгі жанрды таңда.')
    genre_secondary = _genre_field(required=False, message='Жанрды таңда.')
    # Объявлено полем, а не правкой `max_length` у готового: валидатор длины
    # собирается при создании поля, и выставленный после него атрибут ничего
    # не проверяет — аннотация любой длины сохранялась молча.
    annotation = forms.CharField(
        required=False, max_length=ANNOTATION_MAX, widget=forms.Textarea,
        error_messages={'max_length':
                        f'Аннотация тым ұзын — {ANNOTATION_MAX} таңбадан аспасын.'})

    class Meta:
        model = Story
        fields = ('title', 'annotation', 'format', 'audience', 'status', 'cover')
        error_messages = {
            'title':  {'required': 'Атауын жаз.'},
            'format': {'required': 'Форматты таңда.',
                       'invalid_choice': 'Форматты таңда.'},
        }

    def __init__(self, *args, story=None, **kwargs):
        self.story = story
        super().__init__(*args, **kwargs)
        self.fields['cover'].required = False
        # Статус приходит радио-кнопкой, которой у большинства работ нет:
        # пустая строка значит «не меняем» (`update_story_settings`).
        self.fields['status'].required = False
        self.fields['audience'].required = False

    def clean_audience(self):
        audience = self.cleaned_data.get('audience', '')
        if audience and audience not in AUDIENCE_ORDER:
            raise forms.ValidationError('Жас белгісі дұрыс емес.')
        return audience

    def clean_status(self):
        """Радио статуса рендерится только публичному сериалу (BR-10a).

        POST мимо интерфейса не должен уметь больше, чем интерфейс: чужое
        значение не ошибка формы, а просто «не меняем» — так же, как пустое.
        """
        status = self.cleaned_data.get('status', '')
        story = self.story
        allowed = (('OnProcess', 'Completed')
                   if story is not None and story.is_public and story.is_serial
                   else ())
        return status if status in allowed else ''

    def clean(self):
        """Второй жанр не выбирают тем же самым — тихо снимаем, а не ругаем:
        это не то, ради чего форму стоит возвращать с ошибкой."""
        cleaned = super().clean()
        if cleaned.get('genre_secondary') == cleaned.get('genre_primary'):
            cleaned['genre_secondary'] = None
        return cleaned

    def clean_format(self):
        fmt = self.cleaned_data.get('format', '')
        if (fmt == 'single' and self.story is not None
                and self.story.chapter_set.count() > 1):
            raise forms.ValidationError(
                'Бірнеше бөлімі жазылған жұмысты бір бөлімді пішінге '
                'ауыстыруға болмайды.')
        return fmt

    @property
    def tag_names(self) -> list:
        return self.cleaned_data.get('tags', '').split(',')


class ChapterForm(forms.ModelForm):
    """Редактор главы (FR-WRITE-05) вместе с необязательным опросом.

    Опрос живёт здесь, а не отдельной формой, потому что сохраняется одним
    действием автора: он пишет главу и тут же спрашивает читателя. Лимиты
    опроса — BR-POLL-02, и режет их слой данных: вопрос без двух вариантов
    не опрос, а не ошибка ввода.
    """

    poll_question = forms.CharField(required=False, max_length=120)
    poll_option = forms.CharField(required=False)

    class Meta:
        model = Chapter
        fields = ('title', 'body')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Пустая глава не сохраняется: у неё нет ни имени, ни текста, а
        # «Жоба сақталды» на пустом экране — обещание, которого нет.
        self.fields['body'].required = True
        for name in ('title', 'body'):
            self.fields[name].error_messages['required'] = 'Атауын және мәтінін жаз.'

    def clean_body(self):
        body = self.cleaned_data.get('body', '')
        if not body.strip():
            raise forms.ValidationError('Атауын және мәтінін жаз.')
        return body


class ProfileForm(forms.ModelForm):
    """Редактирование своего профиля (FR-PROF-05).

    `age` и `gender` — самодекларация (DEC-24), без верификации. Пустой
    `avatar` значит «не меняем»: автор не переизбирает файл при каждом
    сохранении.
    """

    class Meta:
        model = User
        fields = ('pen_name', 'name', 'bio', 'age', 'gender', 'avatar')
        error_messages = {
            'pen_name': {'required':   'Авторлық атыңды жаз.',
                         'max_length': 'Авторлық атың тым ұзын — 60 таңбадан аспасын.'},
            'name':     {'required':   'Ресми атыңды жаз.',
                         'max_length': 'Ресми атың тым ұзын — 120 таңбадан аспасын.'},
            'bio':      {'max_length': 'Өзің туралы мәтін тым ұзын — 200 таңбадан аспасын.'},
            'gender':   {'invalid_choice': 'Жынысын дұрыс таңда.'},
            'age':      {'invalid': 'Жасын дұрыс жаз.'},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['pen_name'].required = True
        self.fields['name'].required = True
        self.fields['avatar'].required = False
        self.fields['bio'].required = False
        self.fields['age'].required = False
        self.fields['gender'].required = False

    def clean_age(self):
        age = self.cleaned_data.get('age')
        if age is not None and not (1 <= age <= 120):
            raise forms.ValidationError('Жасын дұрыс жаз.')
        return age


class SubmissionForm(forms.Form):
    """Подача работы на конкурс (FR-CONT-04, BR-22…25).

    **Форма ничего не отклоняет по содержанию работы** (BR-24): короткий
    текст, длинный и занятый другим конкурсом выбираются и отправляются
    свободно — рядом с ними стоит заметка, а решение принимает человек.
    Проверяется только то, без чего заявки не существует: выбрана ли работа,
    отвечена ли AI-декларация (DEC-21), подтверждены ли возраст и правила.

    Список работ приходит извне: это те же публичные работы автора, что
    рендерит страница, и второго правила отбора здесь быть не должно.
    """

    story_slug = forms.CharField(error_messages={'required': 'Шығарманы таңда.'})
    ai_used = forms.ChoiceField(
        choices=[(k, k) for k in AI_DECLARATIONS],
        error_messages={'required':       'AI-декларацияға жауап бер.',
                        'invalid_choice': 'AI-декларацияға жауап бер.'})
    confirm_age = forms.BooleanField(
        required=False, error_messages={'required': 'Жас талабына сай екеніңді раста.'})
    confirm_rules = forms.BooleanField(
        required=True,
        error_messages={'required': 'Байқау ережелерімен келісуді раста.'})

    def __init__(self, *args, candidates=None, contest=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.candidates = candidates or {}
        self.contest = contest
        # Возраст подтверждается только там, где конкурс называет вилку
        # (BR-48): у конкурса без ценза чекбокса нет вовсе.
        self.fields['confirm_age'].required = bool(
            contest is not None and contest.eligibility_line)

    def clean_story_slug(self):
        slug = self.cleaned_data['story_slug']
        if slug not in self.candidates:
            raise forms.ValidationError('Шығарманы таңда.')
        return slug

    def clean(self):
        cleaned = super().clean()
        if self.contest is not None and not self.contest.is_accepting:
            raise forms.ValidationError('Өтінім қабылдау аяқталды.')
        return cleaned

    @property
    def story(self):
        return self.candidates.get(self.cleaned_data.get('story_slug'))


class CommentForm(forms.Form):
    """Комментарий или ответ на него (FR-STORY-05, BR-30).

    Уровень вложенности держит не форма, а резолв родителя
    (`top_level_comment_of`): ответ на ответ не находится вовсе.
    """

    text = forms.CharField(error_messages={'required': 'Пікір мәтінін жаз.'},
                           strip=True)
    parent = forms.CharField(required=False)
    chapter = forms.IntegerField(required=False)
