from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    # HOME
    path('', views.home, name='home'),

    # AUTH
    path('auth/login/', views.login_view, name='login'),
    path('auth/logout/', views.logout_view, name='logout'),
    path('auth/signup/', views.signup, name='signup'),
    path('auth/signup/success/', views.signup_success, name='signup_success'),

    # CAT — каталог и поиск (DEC-27: search/genre/tag — единый catalog-движок)
    path('catalog/', views.catalog, name='catalog'),
    path('search/', views.search_results, name='search_results'),
    path('genres/', views.genre_index, name='genre_index'),
    path('genres/<slug:slug>/', views.genre_detail, name='genre_detail'),
    path('tag/<slug:slug>/', views.tag_detail, name='tag_detail'),
    path('collections/', views.collections, name='collections'),
    path('collections/<slug:slug>/', views.collection_detail, name='collection_detail'),

    # STORY — произведение и чтение
    path('story/<slug:slug>/', views.story_detail, name='story_detail'),
    path('story/<slug:slug>/read/', views.story_read, name='story_read'),
    path('story/<slug:slug>/read/<int:chapter>/', views.story_read_chapter, name='story_read_chapter'),

    # WRITE — авторский кабинет
    path('write/', views.my_stories, name='my_stories'),
    path('write/new/', views.new_story, name='new_story'),
    path('write/<slug:slug>/', views.manage_story, name='manage_story'),
    path('write/<slug:slug>/settings/', views.story_settings, name='story_settings'),
    path('write/<slug:slug>/chapter/new/', views.chapter_editor, name='chapter_new'),
    path('write/<slug:slug>/chapter/<int:chapter>/edit/', views.chapter_editor, name='chapter_edit'),

    # PROF — профиль
    path('me/', views.profile_me, name='profile_me'),
    path('me/edit/', views.profile_me_edit, name='profile_me_edit'),
    path('u/<str:username>/', views.profile_other, name='profile_other'),

    # LIB — библиотека
    path('library/', views.library, name='library'),

    # NOTIF — уведомления
    path('notifications/', views.notifications, name='notifications'),

    # CONT — конкурсы
    # ВАЖНО: my-submissions ДОЛЖЕН идти до <slug:slug>, иначе Django смэтчит
    # 'my-submissions' как slug конкурса.
    path('contests/', views.contest_list, name='contest_list'),
    path('contests/my-submissions/', views.my_submissions, name='my_submissions'),
    path('contests/<slug:slug>/', views.contest_detail, name='contest_detail'),
    path('contests/<slug:slug>/submit/', views.contest_submit, name='contest_submit'),

    # API — внутренние JSON-эндпоинты (search popup и др.)
    path('api/search-index.json', views.search_index_json, name='api_search_index'),

    # LEGAL/INFO — статичные стабы для footer-ссылок (DEC-22, FR-AUTH-05)
    path('rules/moderation/', views.legal_moderation_rules, name='legal_moderation'),
    path('rules/publishing/', views.legal_publishing_terms, name='legal_publishing'),
    path('about/',            views.legal_about,            name='legal_about'),
    path('terms/',            views.legal_terms,            name='legal_terms'),
    path('privacy/',          views.legal_privacy,          name='legal_privacy'),

    # DESIGN — внутренние страницы (только при DEBUG=True)
    path('_design/tokens/', views.design_tokens, name='design_tokens'),
    path('_design/components/', views.design_components, name='design_components'),
    path('_design/states/', views.design_states, name='design_states'),
]
