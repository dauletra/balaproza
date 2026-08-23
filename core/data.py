"""Единственная дверь к данным для views, контекст-процессоров и фильтров.

Ф14 меняет то, откуда берутся произведения, но не то, что показывает
страница. Чтобы это было правдой, читающая сторона не должна знать про
хранилище: она обращается сюда, а этот модуль решает, кто отвечает —
`stub_data` сегодня или менеджеры моделей завтра. Без такого шва каждый
этап миграции переписывал бы `views.py` заново, и отличить «сломалась
модель» от «сломался вызов» было бы нечем.

Импорты сгруппированы по разделам продукта и **перечислены поимённо** —
это не педантизм: по мере Ф14 строки будут переезжать из `stub_data` в
модули запросов по одной, и список показывает, что уже переведено, а что
ещё нет. `import *` такой картины не даёт.

Правило: **никто, кроме этого модуля, не импортирует `stub_data`**.
Держит `core/tests/test_data_facade.py`.
"""

# ── Домен: правила, которые переживут замену хранилища ───────────────────
from .domain.awards import (
    AWARD_TIERS,
    READ_TIER_ART,
    READ_TIERS,
    next_tier_for,
    tier_for,
)
from .domain.catalog import (
    AUDIENCE_ORDER,
    BADGE_LABELS,
    CATALOG_AUDIENCE_FILTERS,
    CATALOG_AUTHOR_FILTERS,
    CATALOG_BADGE_FILTERS,
    CATALOG_DEFAULT_SORT,
    CATALOG_FORMAT_FILTERS,
    CATALOG_KIND_FILTERS,
    CATALOG_LENGTH_FILTERS,
    CATALOG_PRESETS,
    CATALOG_SORTS,
    CATALOG_STATUS_FILTERS,
    KIND_PREDICATES,
    NEW_AUTHOR_FOLLOWERS,
    PUBLIC_STATUSES,
    STORY_AUDIENCES,
    STORY_BADGES,
)
from .domain.contests import (
    CONTEST_PHASE_BADGE,
    CONTEST_PHASE_LABELS,
    CONTEST_PHASES,
    CONTEST_RESULT_LABELS,
    PUBLIC_CONTEST_RESULTS,
    SUBMISSION_NOTES,
    SUBMISSION_STATUSES,
)
from .domain.formatting import (
    KK_MONTHS_SHORT,
    kk_ago,
    kk_date,
    kk_period,
    kk_updated,
    spaced_number,
)
from .domain.library import LIBRARY_KINDS
from .domain.notifications import (
    MODERATION_OUTCOME_LABELS,
    MODERATION_OUTCOMES,
    NOTIF_BUCKET_LABELS,
    NOTIF_BUCKETS,
    NOTIF_KINDS,
)
from .domain.story import (
    PUBLISH_CHECKLIST,
    REACTIONS,
    REACTIONS_BY_SLUG,
    STORY_FORMATS,
    STORY_STATUSES,
    Reaction,
)
from .domain.tags import TAG_STATUSES

# ── Каталог, поиск, жанры: уже на моделях ────────────────────────────────
from .queries.catalog import (
    all_authors,
    all_genres,
    apply_catalog_filters,
    catalog_base,
    filter_catalog,
    genre_by_slug,
    is_new_author,
    public_stories,
    related_stories,
    search_authors,
    search_stories,
    stories_by_genre,
    story_by_slug,
)

# ── Справочники: теги (жанры уже выше, из моделей) ───────────────────────
from .stub_data import (
    BLOCKED_TAG_PATTERNS,
    TAGS,
    TAGS_BY_SLUG,
    accepted_tags_json,
    blocked_tag_patterns_list,
    is_blocked,
    popular_tags,
    tag_by_slug,
    tags_of,
    trending_tags,
)

# ── Произведение, главы, отклик ──────────────────────────────────────────
from .stub_data import (
    BOOK_OF_WEEK,
    COLLECTIONS,
    COLLECTIONS_BY_SLUG,
    chapter_of,
    chapters_of,
    collections_of,
    comments_of,
    comments_of_chapter,
    poll_of,
    reaction_breakdown,
    reactions_of,
)

# ── Автор: кабинет, профиль, публичные счётчики ──────────────────────────
from .stub_data import (
    can_submit_for_review,
    missing_for_review,
    my_stories_of,
    new_authors,
    portal_stats,
    public_stats,
    public_stories_of,
    publish_checklist,
    reader_stats,
    top_stories_of,
    writer_attention,
    writer_stats,
)

# ── Библиотека, чтение, подписки ─────────────────────────────────────────
from .stub_data import (
    SAMPLE_PROGRESS,
    followers_of,
    following_of,
    in_library,
    is_following,
    library_of,
)

# ── Награды (FR-PROF-06, DEC-41, DEC-46) ─────────────────────────────────
from .stub_data import (
    AWARDS,
    achievements_of,
    award_catalog,
    contest_awards_of,
    next_read_tier,
    read_ladder,
    read_tier,
    reads_total,
    winning_stories_of,
)

# ── Уведомления ──────────────────────────────────────────────────────────
from .stub_data import (
    notifications_for_user,
    unread_count_for_user,
)

# ── Конкурсы (DEC-45, DEC-46) ────────────────────────────────────────────
from .stub_data import (
    ACCEPTING_CONTESTS,
    CONTESTS,
    CONTESTS_BY_SLUG,
    FINISHED_CONTESTS,
    HERO_CONTEST,
    OPEN_CONTESTS,
    busy_contest_of,
    can_withdraw,
    common_rules,
    contest_history,
    has_submission,
    submission_candidates,
    submission_checklist,
    submissions_of,
)

# ── Ссылки «Авторлар мектебі» (DEC-22) ───────────────────────────────────
from .stub_data import SCHOOL_LINKS

# ── Стаб-специфичное: источник для сида и остатки непереключённых страниц ─
# `STORIES_BY_SLUG` ещё держит страницу произведения — она переключается
# своим шагом. Остальное читает `seed_demo`, раскладывая корпус по
# моделям, плюс витрина состояний `/_design/states/`, которой нужно по
# одному экземпляру каждого объекта.
from .stub_data import (  # noqa: F401
    AUTHORS,
    AUTHORS_BY_USERNAME,
    AWARD_GRANTS,
    COMMENTS_BY_STORY,
    FOLLOWING,
    LIBRARY_BY_USER,
    NOTIFICATIONS_BY_USER,
    POLLS_BY_CHAPTER,
    STORIES,
    STORIES_BY_SLUG,
    SUBMISSIONS_BY_USER,
)
