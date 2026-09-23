"""Модели портала: поля, Meta, инварианты и мутации.

Производное не хранится. Колонка заводится, только если
значение нельзя вывести (акт человека) или агрегат по логу слишком дорог, —
и тогда рядом стоит её пересчёт.

Подписи собирает `templatetags/qazaqnovel`, выдачу — `managers.py`.

Пакет разложен по разделам продукта: `people`, `catalog`, `story`,
`social`, `moderation`, `contests`, `site`. Снаружи модели берут отсюда —
`from core.models import Story`, — а не из файла раздела: раскладка —
дело пакета. Связь с моделью из соседнего файла пишется строкой
`'core.X'`, а не классом: так файлы не импортируют друг друга по кругу,
а миграция видит ту же связь. Функции путей загрузки отдаются отсюда же —
`0001_initial` ссылается на них как на `core.models.<имя>`.
"""

from .people import Follow, User, user_avatar_path
from .catalog import (
    BlockedTagPattern,
    BookOfWeek,
    Collection,
    CollectionItem,
    Genre,
    StoryTag,
    Tag,
)
from .story import (
    Chapter,
    ChapterPoll,
    ChapterReaction,
    ChapterReactionVote,
    ChapterRevision,
    PollOption,
    PollVote,
    Story,
    StoryView,
    story_cover_path,
)
from .social import CommentLike, LibraryEntry, Notification, ReadingProgress, StoryComment
from .moderation import ModerationClaim, ModerationDecision, Report
from .contests import (
    AwardGrant,
    Contest,
    ContestAward,
    ContestCondition,
    JuryMember,
    Submission,
    TimelineStage,
    award_image_path,
    contest_poster_path,
)
from .site import PortalDay, SchoolLink
