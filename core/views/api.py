"""Внутренние JSON-эндпоинты."""

from django.http import JsonResponse

from .. import data


def search_suggest(request):
    """Подсказки быстрого поиска (Cmd+K): до пяти работ, авторов, тегов.

    Раньше здесь лежала выгрузка **всего индекса** одним документом, а
    фильтровал его браузер. На демо-корпусе это выглядело остроумно: один
    запрос, дальше поиск без сети. На настоящем каталоге тот же приём
    означает, что в телефон подростка при первом нажатии Cmd+K уезжают
    все работы, все авторы и все теги портала.

    Кэша здесь нет и не нужно: выборка ограничена пятью строками и идёт
    по триграммным индексам, а кэшировать пришлось бы по каждому запросу
    отдельно. Заодно ушло отставание: до этого работа, опубликованная
    только что, не находилась пять минут — ровно столько жил индекс.
    """
    found = data.search_suggestions(request.GET.get('q', ''))
    return JsonResponse({
        'stories': [
            {
                'slug':   s.slug,
                'title':  s.title,
                'author': s.author.public_name if s.author else '',
                # Обложки лежат в /media/; пусто — карточка рисует плашку.
                'cover':  s.cover.url if s.cover else '',
            }
            for s in found['stories']
        ],
        'authors': [
            {'username': a.username, 'name': a.public_name}
            for a in found['authors']
        ],
        'tags': [
            {'slug': t.slug, 'name': t.name, 'usage_count': t.usage_count}
            for t in found['tags']
        ],
    })
