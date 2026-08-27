"""View-слой, разложенный по разделам продукта.

Один файл на 1 262 строки вырос до предела, за которым в нём перестают
ориентироваться: чтобы поправить конкурсы, приходилось прокручивать мимо
каталога, профиля и правовых стабов. Модули названы кодами разделов,
которыми размечены и `core/urls.py`, и карта требований в docs/14 — так
«FR-CONT-04» приводит в `views/contests.py` без поиска по проекту.

Имена собраны здесь потому, что `core/urls.py` знает `views.home`, а не
`views.home.home`: пакет обязан выглядеть снаружи ровно тем модулем,
которым был. Перечислены поимённо — `import *` не даёт карты того, что
где живёт, а список маршрутов рядом читается как оглавление.

Сборки ссылок здесь нет вовсе: «данные из queries плюс URL» — это
`core/links.py`, и половина прежнего файла была именно ею.

Одна тонкость имён: у трёх модулей есть одноимённая view (`catalog`,
`library`, `notifications`), и после сборки здесь атрибут пакета — это
**функция**, а не подмодуль. За константой модуля надо ходить полным
путём: `from core.views.catalog import PAGE_SIZE`, а не
`from core.views import catalog`.
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
from .notifications import notifications
from .profile import (
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
