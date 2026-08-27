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

    # STORY — произведение (чтение глав происходит inline через ?chapter=N)
    path('story/<slug:slug>/', views.story_detail, name='story_detail'),
    path('story/<slug:slug>/comment/', views.comment_create, name='comment_create'),
    path('story/<slug:slug>/library/', views.library_toggle, name='library_toggle'),
    path('u/<str:username>/follow/', views.follow_toggle, name='follow_toggle'),
    path('story/<slug:slug>/comment/<int:comment_id>/delete/',
        views.comment_delete, name='comment_delete'),
    path('story/<slug:slug>/comment/<int:comment_id>/like/',
        views.comment_like, name='comment_like'),
    path('story/<slug:slug>/chapter/<int:chapter>/react/',
        views.chapter_react, name='chapter_react'),
    path('story/<slug:slug>/chapter/<int:chapter>/poll/vote/',
        views.poll_vote, name='poll_vote'),

    # WRITE — авторский кабинет
    path('write/', views.my_stories, name='my_stories'),
    path('write/new/', views.new_story, name='new_story'),
    path('write/<slug:slug>/', views.manage_story, name='manage_story'),
    path('write/<slug:slug>/settings/', views.story_settings, name='story_settings'),
    path('write/<slug:slug>/chapter/new/', views.chapter_editor, name='chapter_new'),
    path('write/<slug:slug>/chapter/<int:chapter>/edit/', views.chapter_editor, name='chapter_edit'),
    path('write/<slug:slug>/delete/', views.delete_story, name='delete_story'),

    # PROF — профиль
    path('me/', views.profile_me, name='profile_me'),
    path('me/edit/', views.profile_me_edit, name='profile_me_edit'),
    path('u/<str:username>/', views.profile_other, name='profile_other'),
    # Люди автора (FR-PROF-10). Один маршрут на оба списка: страницы
    # различаются набором, а не устройством. Неизвестный `kind` — 404 во
    # view, а не молчаливый фолбэк: `/u/aidana/garbage/` не должен отдавать
    # подписчиков под чужим заголовком.
    path('u/<str:username>/<str:kind>/', views.profile_people, name='profile_people'),

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
    path('contests/<slug:slug>/withdraw/', views.contest_withdraw, name='contest_withdraw'),

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
