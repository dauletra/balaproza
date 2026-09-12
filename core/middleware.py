"""Гейт онбординга (BR-90, DEC-85): один редирect из `telegram_callback`
не проверяется повторно ни на одном другом маршруте, и обход всей учётной
записи «без анкеты и согласия» сводился к любому прямому переходу на
другой URL. Middleware закрывает калитку на каждом запросе, а не только
на первом ответе после входа.
"""

from urllib.parse import urlencode

from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse

# Разрешено без завершённого онбординга: сам вход/выход и его шаги, тексты
# согласия (на них ссылается форма онбординга) и служебные адреса без
# пользовательских данных. Список — по имени маршрута, не по префиксу пути,
# чтобы редактирование `core/urls.py` не расходилось с этим списком молча.
_EXEMPT_URL_NAMES = frozenset({
    'login',
    'logout',
    'telegram_callback',
    'onboarding',
    'signup_success',
    'legal_moderation',
    'legal_publishing',
    'legal_about',
    'legal_terms',
    'legal_privacy',
    'robots_txt',
    'sitemap',
})

_EXEMPT_PATH_PREFIXES = ('/admin/', '/static/', '/media/', '/__debug__/')


class OnboardingGuardMiddleware:
    """Залогинен, но `terms_accepted_at` пуст — везде, кроме списка выше,
    уводит на `/auth/onboarding/?next=<куда шёл>`."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._needs_onboarding(request):
            next_url = request.get_full_path()
            return redirect(f"{reverse('core:onboarding')}?{urlencode({'next': next_url})}")
        return self.get_response(request)

    @staticmethod
    def _needs_onboarding(request) -> bool:
        user = request.user
        if not user.is_authenticated or user.terms_accepted_at:
            return False
        if request.path.startswith(_EXEMPT_PATH_PREFIXES):
            return False
        try:
            match = resolve(request.path)
        except Resolver404:
            return False
        return match.url_name not in _EXEMPT_URL_NAMES
