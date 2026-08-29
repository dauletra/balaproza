"""Единственная дверь к данным для views, контекст-процессоров и фильтров.

Читающая сторона не знает про хранилище: она обращается сюда, а этот
модуль решает, кто отвечает — правила из `core/domain`, записи из
`core/queries`.

Импорты сгруппированы по разделам продукта и **перечислены поимённо**:
список — карта того, откуда берётся каждая часть продукта.
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
    CATALOG_KIND_FILTERS,
    CATALOG_LENGTH_FILTERS,
    CATALOG_PRESETS,
    CATALOG_SORTS,
    CATALOG_STATUS_FILTERS,
    NEW_AUTHOR_DAYS,
    PUBLIC_STATUSES,
    STORY_AUDIENCES,
    STORY_BADGES,
)
from .domain.contests import (
    AI_DECLARATIONS,
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
from .domain.profile import GENDERS, GENDER_LABELS
from .domain.story import (
    PUBLISH_CHECKLIST,
    REACTIONS,
    REACTIONS_BY_SLUG,
    STORY_FORMATS,
    STORY_STATUSES,
    Reaction,
    status_after_moderation,
)
from .domain.slugs import slugify_kz
from .domain.tags import TAG_STATUSES

# ── Каталог, поиск, жанры: уже на моделях ────────────────────────────────
from .queries.catalog import (
    all_authors,
    all_genres,
    filter_catalog,
    genre_by_slug,
    public_stories,
    related_stories,
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
from .queries.library import (
    move_to_shelf,
    reading_progress_of,
    record_reading_progress,
    toggle_library_entry,
)
from .queries.story import (
    add_comment,
    all_collections,
    book_of_week,
    cast_poll_vote,
    chapter_among,
    chapter_of,
    chapters_of,
    collection_by_slug,
    collections_of,
    comment_of,
    comments_of,
    comments_of_chapter,
    delete_comment,
    poll_for,
    poll_of,
    reactions_of,
    record_story_view,
    recount_recent_views,
    toggle_chapter_reaction,
    toggle_comment_like,
    top_level_comment_of,
)

# ── Теги (docs/ui.md) ───────────────────────────────────────────────────────
from .queries.tags import (
    accepted_tags_json,
    all_tags,
    blocked_tag_patterns_list,
    is_blocked,
    popular_tags,
    resolve_story_tags,
    tag_by_slug,
    tags_of,
    trending_tags,
)

# ── Запись: произведение, глава, опрос ───────────────────────────────────
from .queries.write import (
    create_story,
    save_chapter,
    save_chapter_poll,
    submit_story_for_review,
    update_story_settings,
)

# ── Награды, подписки, уведомления, витрины портала ──────────────────────
from .queries.profile import (
    AWARDS,
    achievements_of,
    author_by_username,
    award_catalog,
    contest_awards_of,
    followers_count_of,
    followers_of,
    following_count_of,
    following_of,
    is_following,
    mark_all_notifications_read,
    mark_notification_read,
    new_authors,
    notifications_for_user,
    portal_stats,
    read_ladder,
    read_tier,
    reads_total,
    toggle_follow,
    unread_count_for_user,
    update_profile,
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
    contest_participants,
    create_submission,
    finished_contests,
    has_submission,
    hero_contest,
    home_contests,
    open_contests,
    submission_candidates,
    submission_checklist,
    submissions_of,
    withdraw_submission,
)

# ── Ссылки «Авторлар мектебі» (DEC-22) ───────────────────────────────────
from .queries.site import school_links
