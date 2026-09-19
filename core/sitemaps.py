"""`sitemap.xml` (чек-лист README п. 9): что краулеру можно индексировать.

Раздел `/write/`, `/moderation/`, `/me/`, `/auth/`, `/notifications/`,
`/api/` сюда не входит — им закрыт вход и через `robots.txt`
(`core/views/seo.py`).

Долго карта состояла из произведений и десятка статических страниц, и
этого мало: людей на литературный портал приводят из поиска не названия
конкретных работ, которых никто не знает, а **жанр, тег, подборка и имя
автора**. Ровно те страницы, ради которых сайт и собран серверным
рендерингом, краулеру не назывались.
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


class AuthorSitemap(Sitemap):
    """Профили авторов — **только с публичной работой**.

    Пустой профиль в поиске работает против платформы: человек приходит
    по запросу с именем и попадает на страницу, где читать нечего. Тот же
    отбор, что у ряда «Жаңа авторлар» на главной.
    """

    changefreq = 'weekly'
    priority = 0.5

    def items(self):
        return data.sitemap_authors()

    def location(self, obj):
        return reverse('core:profile_other', kwargs={'username': obj.username})


class GenreSitemap(Sitemap):
    """Двенадцать жанровых страниц. Меняются реже всего — сам справочник
    закрыт, — но в поиске это самые общие запросы раздела."""

    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return data.sitemap_genres()

    def location(self, obj):
        return reverse('core:genre_detail', kwargs={'slug': obj.slug})


class TagSitemap(Sitemap):
    """Принятые теги. Именно они и есть длинный хвост: «мектеп»,
    «фэнтези», «бірінші махаббат» — то, что люди набирают в поиске,
    а не название конкретной работы."""

    changefreq = 'weekly'
    priority = 0.4

    def items(self):
        return data.sitemap_tags()

    def location(self, obj):
        return reverse('core:tag_detail', kwargs={'slug': obj.slug})


class CollectionSitemap(Sitemap):
    """Жинақтар — редакционные подборки, первичный вход в чтение."""

    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return data.sitemap_collections()

    def location(self, obj):
        return reverse('core:collection_detail', kwargs={'slug': obj.slug})


class ContestSitemap(Sitemap):
    """Конкурсы, включая завершённые: страница прошлогоднего выпуска
    остаётся живой ссылкой — на ней победители и другие выпуски."""

    changefreq = 'weekly'
    priority = 0.5

    def items(self):
        return data.sitemap_contests()

    def location(self, obj):
        return reverse('core:contest_detail', kwargs={'slug': obj.slug})


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
