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

from .api import search_index_json
from .auth import (
    DEMO_USERNAME,
    login_view,
    logout_view,
    signup,
    signup_success,
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
from .profile import (
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
    library_toggle,
    poll_vote,
    story_detail,
)
from .write import (
    chapter_editor,
    delete_story,
    manage_story,
    my_stories,
    new_story,
    story_settings,
)
