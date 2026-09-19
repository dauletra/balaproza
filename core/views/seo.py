"""`robots.txt` (чек-лист README, п. 9). Вьюха, а не статический файл: строка
`Sitemap:` требует абсолютный адрес, а домен известен только запросу.
"""

from django.conf import settings
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
    # Админка тоже. Её адрес настраиваемый (`ADMIN_PATH`), и вписать его
    # сюда литералом значило бы закрыть от краулера не тот путь, а
    # настоящий назвать в открытую нигде и не закрыть.
    lines.append(f'Disallow: /{settings.ADMIN_PATH}/')
    lines += [f'Disallow: {path}' for path in _DISALLOWED]
    lines.append('Allow: /')
    lines.append('')
    lines.append(f'Sitemap: {request.build_absolute_uri(reverse("sitemap"))}')
    return HttpResponse('\n'.join(lines), content_type='text/plain')
