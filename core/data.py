"""Единственная дверь к данным для views, контекст-процессоров и фильтров.

Ф14 меняет то, откуда берутся произведения, но не то, что показывает
страница. Чтобы это было правдой, читающая сторона не должна знать про
хранилище: она обращается сюда, а этот модуль решает, кто отвечает —
`stub_data` сегодня или менеджеры моделей завтра. Без такого шва каждый
этап миграции переписывал бы `views.py` заново, и отличить «сломалась
модель» от «сломался вызов» было бы нечем.

Импорты сгруппированы по разделам продукта и **перечислены поимённо**:
список — карта того, откуда сейчас берётся каждая часть продукта.
`import *` такой картины не даёт.

**Стаба здесь больше нет.** Все разделы читают модели; `core/stub_data.py`
остался единственным источником для `seed_demo`, который перекладывает
корпус в базу, и уйдёт вместе с переездом литералов в саму команду
(docs/19 §19.4, этап 11). Держит `core/tests/test_data_facade.py`.
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
    status_after_moderation,
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

# ── Кабинет автора, профиль, библиотека ──────────────────────────────────
from .queries.author import (
    can_submit_for_review,
    in_library,
    library_of,
    missing_for_review,
    my_stories_of,
    public_stats,
    public_stories_of,
    publish_checklist,
    reader_stats,
    story_by_slug_for_author,
    top_stories_of,
    writer_attention,
    writer_stats,
)

# ── Произведение: главы, отклик, комментарии, подборки ───────────────────
from .queries.library import reading_progress_of
from .queries.story import (
    all_collections,
    book_of_week,
    chapter_of,
    chapters_of,
    collection_by_slug,
    collections_of,
    comments_of,
    comments_of_chapter,
    poll_of,
    reaction_breakdown,
    reactions_of,
)

# ── Теги (docs/11) ───────────────────────────────────────────────────────
from .queries.tags import (
    accepted_tags_json,
    all_tags,
    blocked_tag_patterns_list,
    is_blocked,
    popular_tags,
    tag_by_slug,
    tags_of,
    trending_tags,
)

# ── Награды, подписки, уведомления, витрины портала ──────────────────────
from .queries.profile import (
    AWARDS,
    achievements_of,
    author_by_username,
    award_catalog,
    contest_awards_of,
    followers_of,
    following_of,
    is_following,
    new_authors,
    next_read_tier,
    notifications_for_user,
    portal_stats,
    read_ladder,
    read_tier,
    reads_total,
    unread_count_for_user,
    winning_stories_of,
)

# ── Конкурсы (DEC-45, DEC-46) ────────────────────────────────────────────
from .queries.contests import (
    accepting_contests,
    all_contests,
    busy_contest_of,
    can_withdraw,
    common_rules,
    contest_by_slug,
    contest_history,
    finished_contests,
    has_submission,
    hero_contest,
    open_contests,
    submission_candidates,
    submission_checklist,
    submissions_of,
)

# ── Ссылки «Авторлар мектебі» (DEC-22) ───────────────────────────────────
from .queries.site import school_links
