"""Внутренние JSON-эндпоинты."""

from django.core.cache import cache
from django.http import JsonResponse

from .. import data
from ..queries.site import REFERENCE_TTL

_SEARCH_INDEX_KEY = 'api:search_index'


def search_index_json(request):
    """JSON-индекс для search_popup (Cmd+K). Lazy-fetch — данные приходят
    только при первом открытии popup, не в каждом HTML.

    Кэш **с ограниченным сроком**, а не на всю жизнь процесса. Прежняя
    модульная переменная заполнялась один раз и не инвалидировалась
    никогда: модератор принимал тег, автор публиковал работу, а Cmd+K
    отдавал вчерашний индекс до перезапуска — и у каждого воркера
    gunicorn свой, то есть разный. Пять минут — та же граница, что у
    остальных справочников.
    """
    index = cache.get(_SEARCH_INDEX_KEY)
    if index is None:
        index = {
            'stories': [
                {
                    'slug':   s.slug,
                    'title':  s.title,
                    'author': s.author.public_name if s.author else '',
                    # Обложки лежат в /media/
                    'cover':  s.cover.url if s.cover else '',
                }
                # Тот же набор, что и в каталоге: `public_stories` уже режет
                # по `PUBLIC_STATUSES` — по литералу 'Published' отсюда
                # выпали бы все сериалы (DEC-37).
                for s in data.public_stories()
            ],
            'authors': [
                {'username': a.username, 'name': a.public_name}
                for a in data.all_authors()
            ],
            # docs/11 Phase 3: теги в Cmd+K (только accepted)
            'tags': [
                {'slug': t.slug, 'name': t.name, 'usage_count': t.usage_count}
                for t in data.all_tags() if t.status == 'accepted'
            ],
        }
        cache.set(_SEARCH_INDEX_KEY, index, REFERENCE_TTL)
    return JsonResponse(index)
