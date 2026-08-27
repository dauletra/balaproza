from . import data


def auth_state(request):
    """Гость ↔ авторизованный для шаблонов (используется header/mobile-nav/right-rail).

    Отвечает `request.user`, а не session-флаг: вход настоящий.
    Имена в контексте оставлены прежними — `signed_in` рядом
    с `user.is_authenticated` выглядит вторым источником, но это один и тот
    же ответ под привычным для шаблонов именем, и переименование тронуло бы
    двадцать один файл разметки ради нуля изменений на экране.

    `current_user_name` — как платформа обращается к самому человеку, и это
    не `public_name`. Читателю автор известен под лақап аты («aidana»), а
    приветствие «Қайта қош келдің» адресовано ему самому — там уместно имя,
    которым его зовут. Настоящее имя видит только он сам (BR-73): в чужом
    профиле его нет.
    """
    user = getattr(request, 'user', None)
    is_in = bool(user and user.is_authenticated)
    username = user.username if is_in else ''
    return {
        'signed_in': is_in,
        'current_user_name': user.get_short_name() if is_in else '',
        'current_user_username': username,
        'unread_notifications': data.unread_count_for_user(user if is_in else None),
    }


def site_links(request):
    """Глобально доступные внешние ссылки (FR-LINKS-06): «Авторлар мектебі».
    Используется в footer и любых страницах без явного контекста.
    """
    return {'school_links_global': data.school_links()}


def nav_state(request):
    """Активный пункт навигации — по префиксу пути. Покрывает основные разделы."""
    p = request.path
    if p == '/' or p.startswith('/?'):
        active = 'home'
    elif p.startswith('/library'):
        active = 'library'
    elif p.startswith('/write'):
        active = 'write'
    elif p.startswith('/notifications'):
        active = 'notifications'
    elif p.startswith('/me') or p.startswith('/u/'):
        active = 'profile'
    elif p.startswith('/contests'):
        active = 'contests'
    elif p.startswith('/catalog') or p.startswith('/genres') or p.startswith('/collections') or p.startswith('/search'):
        active = 'catalog'
    elif p.startswith('/story'):
        active = 'story'
    elif p.startswith('/auth'):
        active = 'auth'
    else:
        active = ''
    return {'nav_active': active}
