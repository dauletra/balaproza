"""`sitemap.xml` (DEC-?, чек-лист README п. 9): что краулеру можно
индексировать. Раздел `/write/`, `/moderation/`, `/me/`, `/auth/`,
`/notifications/`, `/api/` сюда не входит — им закрыт вход и через
`robots.txt` (`core/views/seo.py`).
"""

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from . import data


class StoryListSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        # `data.sitemap_stories()` — не `public_stories()`: карточные
        # аннотации каталога тут не нужны, только слаг и дата правки.
        return data.sitemap_stories()

    def location(self, obj):
        return reverse('core:story_detail', kwargs={'slug': obj.slug})

    def lastmod(self, obj):
        return obj.updated_at


class StaticViewSitemap(Sitemap):
    changefreq = 'monthly'

    # (имя маршрута, приоритет) — главная и каталог выше стабов и легала.
    _PAGES = (
        ('core:home', 1.0),
        ('core:catalog', 0.8),
        ('core:genre_index', 0.6),
        ('core:collections', 0.6),
        ('core:contest_list', 0.6),
        ('core:legal_about', 0.3),
        ('core:legal_terms', 0.3),
        ('core:legal_privacy', 0.3),
        ('core:legal_moderation', 0.3),
        ('core:legal_publishing', 0.3),
    )

    def items(self):
        return self._PAGES

    def location(self, item):
        name, _priority = item
        return reverse(name)

    def priority(self, item):
        _name, priority = item
        return priority
