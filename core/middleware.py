"""Гейт онбординга: один редирect из `telegram_callback`
не проверяется повторно ни на одном другом маршруте, и обход всей учётной
записи «без анкеты и согласия» сводился к любому прямому переходу на
другой URL. Middleware закрывает калитку на каждом запросе, а не только
на первом ответе после входа.
"""

from urllib.parse import urlencode

from django.conf import settings
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
    'decline_onboarding',
    'signup_success',
    'legal_moderation',
    'legal_publishing',
    'legal_about',
    'legal_terms',
    'legal_privacy',
    'robots_txt',
    'sitemap',
})

# Раздел модерации — по той же причине, что и админка ниже: это
# инструмент сотрудника, а не участие в портале, и у заведённого
# `createsuperuser` согласия нет по построению. Без исключения ссылка
# «Модерация» из шапки админки уводила его на анкету, где рядом стоит
# «Тіркеуден бас тарту» — удаление вошедшего каскадом. Постороннему
# раздел всё равно отвечает 404 (`moderator_only`), так что исключение
# ничего не открывает. Полноту списка против `core/urls.py` держит
# `test_auth.TheModerationSectionIsNotGated`.
_MODERATION_URL_NAMES = frozenset({
    'moderation_queue',
    'moderation_detail',
    'moderation_claim',
    'moderation_decide',
    'moderation_comments',
    'moderation_comment_decide',
    'moderation_reports',
    'moderation_report_resolve',
    'moderation_summary',
})

_EXEMPT_PATH_PREFIXES = ('/static/', '/media/', '/__debug__/')


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
        # Админка — по адресу из настроек, а не литералом `/admin/`:
        # префикс настраивается (`DJANGO_ADMIN_PATH`), и записанный
        # константой он совпал бы с маршрутом только при умолчании.
        # Сменили адрес в проде — и человек из админки уезжает на анкету
        # портала, причём именно тот, у кого согласия нет по построению:
        # `createsuperuser` его не проставляет.
        #
        # Читается в момент запроса, а не при импорте: модулем выше это
        # было бы неизменяемым на весь процесс, то есть непроверяемым
        # тестом с другим адресом.
        if request.path.startswith(f'/{settings.ADMIN_PATH}/'):
            return False
        try:
            match = resolve(request.path)
        except Resolver404:
            return False
        return (match.url_name not in _EXEMPT_URL_NAMES
                and match.url_name not in _MODERATION_URL_NAMES)
