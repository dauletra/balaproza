"""`robots.txt` (чек-лист README, п. 9). Вьюха, а не статический файл: строка
`Sitemap:` требует абсолютный адрес, а домен известен только запросу.
"""

from django.http import HttpResponse
from django.urls import reverse

# Разделы без публичного смысла для краулера — те же, что закрыты входом
# или ролью (`core/urls.py`): кабинет автора, модерация, профиль-настройки,
# вход, уведомления, внутренние JSON-эндпоинты.
_DISALLOWED = (
    '/write/',
    '/moderation/',
    '/auth/',
    '/me/',
    '/notifications/',
    '/api/',
)


def robots_txt(request):
    lines = ['User-agent: *']
    lines += [f'Disallow: {path}' for path in _DISALLOWED]
    lines.append('Allow: /')
    lines.append('')
    lines.append(f'Sitemap: {request.build_absolute_uri(reverse("sitemap"))}')
    return HttpResponse('\n'.join(lines), content_type='text/plain')
