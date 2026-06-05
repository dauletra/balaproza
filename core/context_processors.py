from . import stub_data


def auth_state(request):
    """Гость ↔ авторизованный для шаблонов (используется header/mobile-nav/right-rail).
    Никаких моделей: только session-флаг, выставленный в core.views.login_view.
    """
    is_in = bool(request.session.get('signed_in'))
    username = request.session.get('user_username', '') if is_in else ''
    return {
        'signed_in': is_in,
        'current_user_name': request.session.get('user_name', ''),
        'current_user_username': username,
        'unread_notifications': stub_data.unread_count_for_user(username) if is_in else 0,
    }


def site_links(request):
    """Глобально доступные внешние ссылки (FR-LINKS-06): «Авторлар мектебі».
    Используется в footer и любых страницах без явного контекста.
    """
    return {'school_links_global': stub_data.SCHOOL_LINKS}


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
