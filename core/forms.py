"""Формы записи: что вправе прийти из браузера.

**Форма проверяет, `core.data` пишет.** `form.save()` здесь не зовут —
сохранение идёт через фасад, а форма отдаёт `cleaned_data`. Иначе у записи
стало бы две двери, и та, что через форму, обходила бы слой данных.

Тексты ошибок — на «сен» и говорят, что сделать (docs/ui.md).
"""

import re

from django import forms
from django.utils import timezone

from .domain.catalog import AUDIENCE_ORDER
from .domain.contests import AI_DECLARATIONS, eligibility_line
from .domain.story import CHAPTER_BODY_MAX, COMMENT_MAX, MAX_DRAFT_STORIES
from .models import Chapter, Genre, Story, User

# Лимит аннотации (BR-16). У поля модели его нет — это `TextField`, — и
# счётчик в шаблоне до этого был единственным местом, где число называлось.
ANNOTATION_MAX = 500

# Границы опроса (BR-POLL-02). Верхняя — не «пока столько влезло»: список
# длиннее читателю уже не выбор, а анкета. Нижняя — условие смысла: вопрос
# с одним вариантом выбора не предлагает.
POLL_OPTIONS_MIN = 2
POLL_OPTIONS_MAX = 4
POLL_OPTION_MAX_LEN = 80


def _within_chapter_limit(body: str) -> str:
    """Потолок объёма главы одной проверкой на две формы.

    До него предел был один — настройка Django на размер тела запроса, и
    текст, в него не влезший, отвергался ошибкой уровня фреймворка:
    автор видел не «слишком длинно», а сломанную отправку.
    """
    if len(body) > CHAPTER_BODY_MAX:
        raise forms.ValidationError(
            f'Бөлім тым ұзын — {CHAPTER_BODY_MAX // 1000} мың таңбадан '
            f'аспасын. Оны бірнеше бөлімге бөл.')
    return body


class PollOptionsWidget(forms.TextInput):
    """Один `name` — несколько полей ввода.

    Варианты приходят повторяющимся `poll_option`, и достать их все можно
    только `getlist`: обычный виджет вернул бы последний. Раньше это делал
    view прямым `request.POST.getlist`, то есть в обход формы — и сказать
    об ошибке было нечем.
    """

    def value_from_datadict(self, data, files, name):
        getlist = getattr(data, 'getlist', None)
        return getlist(name) if getlist else data.get(name) or []


class PollOptionsField(forms.Field):
    """Список вариантов опроса. Пустые строки — не ввод, а незаполненные
    поля: их четыре всегда, а заполняют обычно два."""

    widget = PollOptionsWidget

    def clean(self, value):
        options = [t.strip() for t in (value or []) if t and t.strip()]
        if len(options) > POLL_OPTIONS_MAX:
            raise forms.ValidationError(
                f'Нұсқа тым көп — ең көбі {POLL_OPTIONS_MAX}.')
        if any(len(t) > POLL_OPTION_MAX_LEN for t in options):
            raise forms.ValidationError(
                f'Нұсқа тым ұзын — {POLL_OPTION_MAX_LEN} таңбадан аспасын.')
        return options


def _genre_field(*, required: bool, message: str):
    """Жанр приходит **слагом**, а не номером строки: это его адрес во всём
    остальном продукте, и форма не должна быть единственным местом, где у
    жанра другой ключ."""
    return forms.ModelChoiceField(
        queryset=Genre.objects.all(), to_field_name='slug', required=required,
        error_messages={'required': message, 'invalid_choice': message})


class NewStoryForm(forms.ModelForm):
    """Создание произведения — три поля (FR-WRITE-01). Статуса здесь нет:
    новая работа всегда черновик (BR-10), и форма сообщает это строкой."""

    genre_primary = _genre_field(required=True, message='Негізгі жанрды таңда.')

    class Meta:
        model = Story
        fields = ('title', 'format')
        error_messages = {
            'title':  {'required': 'Атауын жаз.'},
            'format': {'required': 'Форматты таңда.',
                       'invalid_choice': 'Форматты таңда.'},
        }

    def __init__(self, *args, author=None, **kwargs):
        self.author = author
        super().__init__(*args, **kwargs)

    def clean(self):
        """Потолок пустых черновиков (BR-88, M2 в AUDIT-WRITE-FLOW): ничем
        не ограниченное создание заводило горы работ без единой публикации
        — 25 POST подряд давали 25 работ. Считаются только `NotPublished`:
        работа, дошедшая до модерации или до читателя, потолка не держит."""
        cleaned = super().clean()
        if self.author is not None and Story.objects.filter(
                author=self.author, status='NotPublished').count() >= MAX_DRAFT_STORIES:
            raise forms.ValidationError(
                f'Аяқталмаған жобалар тым көп ({MAX_DRAFT_STORIES}) — '
                'алдымен біреуін жариялап немесе өшір.')
        return cleaned


class StorySettingsForm(forms.ModelForm):
    """Баптаулар произведения (FR-WRITE-04).

    Три правила, которые нельзя обойти прямым POST'ом: статус выбирает
    только публичный сериал (BR-10a, BR-11), одночастная форма не даётся
    работе с несколькими главами, обложка обязана быть растром (BR-46).

    Работа приходит **аргументом `story`, а не `instance=`**: `ModelForm`
    разложил бы `cleaned_data` по экземпляру ещё до `is_valid()`, а тот же
    экземпляр уходит в `update_story_settings` — «не меняем» из
    `clean_status` доехало бы до базы пустым статусом.
    """

    # Не поля модели: теги приходят строкой из `tag_input` и резолвятся
    # слоем данных (pending → accepted, BR-TAG-03), жанры — слагами.
    tags = forms.CharField(required=False)
    # Явное снятие обложки (BR-86) — третье состояние рядом с «новый файл»
    # и «пусто значит не меняем»: без него убрать обложку, не заменив её
    # другой, было нельзя вовсе.
    remove_cover = forms.BooleanField(required=False)
    genre_primary = _genre_field(required=True, message='Негізгі жанрды таңда.')
    genre_secondary = _genre_field(required=False, message='Жанрды таңда.')
    # Объявлено полем, а не правкой `max_length` у готового: валидатор длины
    # собирается при создании поля, и выставленный после атрибут не
    # проверяет ничего.
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
        """Радио статуса рендерится только публичному сериалу (BR-10a). POST
        мимо интерфейса не должен уметь больше: чужое значение не ошибка
        формы, а «не меняем» — так же, как пустое."""
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

    Опрос здесь, а не отдельной формой, потому что сохраняется одним
    действием автора — и потому же одной транзакцией (`data.save_chapter`).

    Лимиты опроса теперь проверяет форма, а не слой данных. Раньше вопрос
    с одним вариантом молча не сохранялся: автор получал «Жоба сақталды» —
    про главу правду, про опрос ложь. Молчание было возможно ровно потому,
    что варианты приходили мимо формы и сказать о них было нечем.
    """

    poll_question = forms.CharField(
        required=False, max_length=120,
        error_messages={'max_length': 'Сұрақ тым ұзын — 120 таңбадан аспасын.'})
    poll_option = PollOptionsField(required=False)

    class Meta:
        model = Chapter
        fields = ('title', 'body')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Пустая глава не сохраняется: у неё нет ни имени, ни текста, а
        # «Жоба сақталды» на пустом экране — обещание, которого нет.
        self.fields['body'].required = True
        self.fields['title'].error_messages['required'] = 'Бөлім атауын жаз.'
        self.fields['body'].error_messages['required'] = 'Бөлім мәтінін жаз.'

    def clean_body(self):
        body = self.cleaned_data.get('body', '')
        if not body.strip():
            raise forms.ValidationError('Бөлім мәтінін жаз.')
        return _within_chapter_limit(body)

    def clean(self):
        """Вопрос и варианты существуют только вместе (BR-POLL-02).

        Ошибка вешается на `poll_question` — на поле, которое автор видит
        первым в свёрнутом блоке опроса: сообщение под ним объясняет, что
        доделать, а не просто сообщает, что что-то не так.
        """
        cleaned = super().clean()
        question = (cleaned.get('poll_question') or '').strip()
        options = cleaned.get('poll_option') or []

        if question and len(options) < POLL_OPTIONS_MIN:
            self.add_error('poll_question',
                           f'Сұраққа кемінде {POLL_OPTIONS_MIN} нұсқа жаз — '
                           f'біреуімен таңдау болмайды.')
        elif options and not question:
            self.add_error('poll_question',
                           'Нұсқалар жазылған — сұрақтың өзін де жаз.')
        return cleaned

    @property
    def poll_options(self) -> list:
        return self.cleaned_data.get('poll_option') or []


class ChapterAutosaveForm(forms.ModelForm):
    """Автосохранение главы (BR-78) — те же два поля, но без обязательных.

    Посреди набора пустой заголовок и пустой текст нормальны: автор ещё
    пишет, и требовать от него законченности каждые три секунды нельзя.
    Проверяются только пределы, которые есть и в базе, — длина заголовка
    и потолок объёма; остальное решается при осознанном сохранении,
    `ChapterForm`.
    """

    class Meta:
        model = Chapter
        fields = ('title', 'body')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('title', 'body'):
            self.fields[name].required = False

    def clean_body(self):
        # Потолок тот же, что у осознанного сохранения: иначе
        # автосохранение молча отдавало бы 400 на тексте, который форма
        # рядом принимает, и редактор показывал бы «сақталмады» без
        # объяснения.
        return _within_chapter_limit(self.cleaned_data.get('body', ''))


_USERNAME_RE = re.compile(r'^[a-z0-9_]{3,30}$')


def _validate_birth_date(birth_date):
    """Общая проверка для `OnboardingForm` и `ProfileForm`: не из будущего
    и не старше разумного (DEC-82). Ценз конкурса эта дата не решает
    (BR-48) — только подсказка форме подачи, откуда она уже приходит
    отдельным чекбоксом."""
    if birth_date is None:
        return birth_date
    today = timezone.localdate()
    if birth_date > today:
        raise forms.ValidationError('Туған күнің болашақта бола алмайды.')
    if today.year - birth_date.year > 120:
        raise forms.ValidationError('Туған күніңді дұрыс жаз.')
    return birth_date


class ProfileForm(forms.ModelForm):
    """Редактирование своего профиля (FR-PROF-05). `birth_date` и `gender` —
    самодекларация (DEC-24); пустой `avatar` значит «не меняем»."""

    # Явное снятие аватара (BR-86) — см. `remove_cover` у `StorySettingsForm`.
    remove_avatar = forms.BooleanField(required=False)

    # Вне Meta.fields (BR-91): `username` у модели `blank=False`, и
    # автосинхронизация `ModelForm._post_clean()` уронила бы
    # `instance.full_clean()` на пустом значении раньше, чем форма решит,
    # что пусто значит «не меняем», — тот же класс проблемы, что развели
    # `remove_avatar` отдельным полем. Здесь пусто значить не может: поле
    # всегда предзаполнено текущим ником, очистка — осознанное действие.
    username = forms.CharField(required=True, max_length=30, error_messages={
        'required': 'Никті жаз.'})

    # Семьи Telegram-уведомлений. Полями формы, а не через `Meta.fields`:
    # у модели они `blank=False` с дефолтом `True`, и `ModelForm` сделал бы
    # их обязательными — снятая галка не отправляется браузером вовсе, то
    # есть «выключить» означало бы «форма невалидна». `required=False` —
    # ровно это и лечит: пусто значит «не хочу».
    push_moderation = forms.BooleanField(required=False)
    push_response = forms.BooleanField(required=False)
    push_new_chapter = forms.BooleanField(required=False)

    class Meta:
        model = User
        fields = ('pen_name', 'bio', 'birth_date', 'gender', 'avatar')
        error_messages = {
            'pen_name':   {'required':   'Авторлық атыңды жаз.',
                           'max_length': 'Авторлық атың тым ұзын — 60 таңбадан аспасын.'},
            'bio':        {'max_length': 'Өзің туралы мәтін тым ұзын — 200 таңбадан аспасын.'},
            'gender':     {'invalid_choice': 'Жынысын дұрыс таңда.'},
            'birth_date': {'invalid': 'Туған күніңді дұрыс жаз.'},
        }

    def __init__(self, *args, current_user=None, **kwargs):
        # `current_user` — не Django-шный `instance=`: связать форму с
        # инстансом означало бы, что `FileField.clean()` на несменённом
        # аватаре тихо подставляет **текущий** файл вместо пустоты (Django
        # так помогает `ClearableFileInput`), и `update_profile` перестаёт
        # отличать «не меняли» от «отправили тот же файл заново» — ровно
        # то состояние, в котором `remove_avatar` перестаёт работать.
        # Нужен только pk для исключения себя из проверки уникальности ника.
        self._exclude_pk = current_user.pk if current_user else None
        super().__init__(*args, **kwargs)
        self.fields['pen_name'].required = True
        self.fields['avatar'].required = False
        self.fields['bio'].required = False
        self.fields['birth_date'].required = False
        self.fields['gender'].required = False

    def clean_birth_date(self):
        return _validate_birth_date(self.cleaned_data.get('birth_date'))

    def clean_username(self):
        value = self.cleaned_data['username'].strip().lower()
        if not _USERNAME_RE.match(value):
            raise forms.ValidationError(
                'Ник тек кіші әріп, сан және «_» болуы керек, 3–30 таңба.')
        # Исключаем себя — иначе пересохранение без изменения ника всегда
        # било бы «ник занят», найдя самого владельца.
        if User.objects.exclude(pk=self._exclude_pk).filter(username=value).exists():
            raise forms.ValidationError('Бұл ник бос емес — басқасын таңда.')
        return value


class OnboardingForm(forms.ModelForm):
    """Онбординг после первого Telegram-входа (FR-AUTH-04). `pen_name`
    обязателен здесь же (DEC-82): пока его нет, читателю показывают
    `@id<цифры>`, и разумно закрыть это в первом же контакте, а не
    рассчитывать, что автор сам дойдёт до `/me/edit/`.

    `gender` и `birth_date` тоже обязательны здесь (DEC-84, отменяет
    необязательность DEC-24 для первого контакта) — единственная точка,
    где эти поля вообще спрашиваются; на `/me/edit/` `birth_date` после
    сохранения больше не редактируется (`update_profile`)."""

    agree_rules = forms.BooleanField(required=True, error_messages={
        'required': 'Жариялау ережелерімен келісу қажет.'})
    agree_privacy = forms.BooleanField(required=True, error_messages={
        'required': 'Құпиялылық саясатымен келісу қажет.'})

    class Meta:
        model = User
        fields = ('pen_name', 'bio', 'birth_date', 'gender')
        error_messages = {
            'pen_name':   {'required':   'Авторлық атыңды жаз.',
                           'max_length': 'Авторлық атың тым ұзын — 60 таңбадан аспасын.'},
            'bio':        {'max_length': 'Өзің туралы мәтін тым ұзын — 200 таңбадан аспасын.'},
            'gender':     {'required': 'Жынысыңды таңда.',
                           'invalid_choice': 'Жынысын дұрыс таңда.'},
            'birth_date': {'required': 'Туған күніңді жаз.',
                           'invalid': 'Туған күніңді дұрыс жаз.'},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['pen_name'].required = True
        self.fields['bio'].required = False
        self.fields['birth_date'].required = True
        self.fields['gender'].required = True

    def clean_birth_date(self):
        return _validate_birth_date(self.cleaned_data.get('birth_date'))


class SubmissionForm(forms.Form):
    """Подача работы на конкурс (FR-CONT-04, BR-22…25).

    **Форма ничего не отклоняет по содержанию работы** (BR-24): рядом с
    кандидатом стоит заметка, а решение принимает человек. Проверяется
    только то, без чего заявки не существует: выбрана ли работа, отвечена
    ли AI-декларация (DEC-21), подтверждены ли возраст и правила.

    Список работ приходит извне — второго правила отбора здесь быть не
    должно.
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
            contest is not None
            and eligibility_line(contest.min_age, contest.max_age))

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
    """Комментарий или ответ на него (FR-STORY-05, BR-30). Уровень
    вложенности держит не форма, а резолв родителя: ответ на ответ не
    находится вовсе."""

    text = forms.CharField(
        strip=True, max_length=COMMENT_MAX,
        error_messages={
            'required': 'Пікір мәтінін жаз.',
            'max_length': f'Пікір тым ұзын — {COMMENT_MAX} таңбадан аспасын.',
        })
    parent = forms.CharField(required=False)
    chapter = forms.IntegerField(required=False)
