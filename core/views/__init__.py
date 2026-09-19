"""View-слой, разложенный по разделам продукта.

Модули названы кодами разделов, которыми размечены и `core/urls.py`, и
требования в docs/spec.md: «FR-CONT-04» приводит в `views/contests.py` без
поиска по проекту. Имена собраны здесь поимённо — `core/urls.py` знает
`views.home`, а не `views.home.home`.

Тонкость: у трёх модулей есть одноимённая view (`catalog`, `library`,
`notifications`), и после сборки атрибут пакета — **функция**, а не
подмодуль. За константой модуля надо ходить полным путём:
`from core.views.catalog import PAGE_SIZE`.
"""

from .api import search_suggest
from .auth import (
    decline_onboarding,
    login_view,
    logout_view,
    onboarding,
    signup_success,
    telegram_callback,
)
from .catalog import (
    catalog,
    collection_detail,
    collections,
    genre_detail,
    genre_index,
    search_results,
    tag_detail,
)
from .contests import (
    PICKER_SEARCH_FROM,
    contest_detail,
    contest_list,
    contest_submit,
    contest_withdraw,
    my_submissions,
)
from .design import design_components, design_states, design_tokens
from .home import home
from .moderation import (
    held_comment_decide,
    held_comments_queue,
    moderation_claim,
    moderation_decide,
    moderation_detail,
    moderation_queue,
    portal_summary,
    report_resolve,
    reports_queue,
)
from .legal import (
    legal_about,
    legal_moderation_rules,
    legal_privacy,
    legal_publishing_terms,
    legal_terms,
)
from .library import library
from .notifications import (
    notification_open,
    notifications,
    notifications_read_all,
)
from .seo import robots_txt
from .profile import (
    delete_account,
    export_texts,
    follow_toggle,
    profile_me,
    profile_me_edit,
    profile_other,
    profile_people,
)
from .story import (
    chapter_react,
    comment_create,
    comment_delete,
    comment_like,
    comment_report,
    library_toggle,
    poll_vote,
    story_detail,
    story_report,
)
from .write import (
    chapter_autosave,
    chapter_delete,
    chapter_editor,
    chapter_move,
    delete_story,
    manage_story,
    my_stories,
    new_story,
    story_settings,
)
