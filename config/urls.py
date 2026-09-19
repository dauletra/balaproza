"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from core.sitemaps import (
    AuthorSitemap,
    CollectionSitemap,
    ContestSitemap,
    GenreSitemap,
    StaticViewSitemap,
    StoryListSitemap,
    TagSitemap,
)

_sitemaps = {
    'stories':     StoryListSitemap,
    'authors':     AuthorSitemap,
    'genres':      GenreSitemap,
    'tags':        TagSitemap,
    'collections': CollectionSitemap,
    'contests':    ContestSitemap,
    'pages':       StaticViewSitemap,
}

urlpatterns = [
    # Адрес админки — из настроек (`ADMIN_PATH`), умолчание прежнее.
    # Имена маршрутов от этого не зависят: `reverse('admin:…')` работает
    # при любом префиксе, и тесты его не знают.
    path(f'{settings.ADMIN_PATH}/', admin.site.urls),
    path('sitemap.xml', sitemap, {'sitemaps': _sitemaps}, name='sitemap'),
    path('', include('core.urls', namespace='core')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if 'debug_toolbar' in settings.INSTALLED_APPS:
    urlpatterns += [path('__debug__/', include('debug_toolbar.urls'))]
