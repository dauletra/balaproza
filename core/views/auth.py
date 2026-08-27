"""Вход, выход и регистрация (FR-AUTH-*).

Сессия настоящая: `django.contrib.auth` кладёт в неё пользователя, а
отвечает на «кто это» база через `request.user`. Флага `signed_in` рядом
больше нет — два источника ответа на один вопрос рано или поздно
расходятся, и тогда страница считает гостем того, кто вошёл.

Чего здесь пока нет — **провайдера личности**. Вход на портал идёт через
Telegram (FR-AUTH-01), а проверка подписи Login Widget (NFR-25) требует
бота и его токена: их заводят при деплое (README). До тех пор
кнопка «Сайтқа кіру» подписывает в демо-аккаунт — тот самый, чьими
работами наполнен корпус. Подобрать пароль к нему нельзя: у сидовых
пользователей его нет вовсе (`set_unusable_password`).
"""

import logging

from django.contrib.auth import login as auth_login, logout as auth_logout
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from ..models import User
from .common import _safe_next

logger = logging.getLogger(__name__)

# Кого подписывает демо-кнопка входа. Ровно один аккаунт и ровно на время,
# пока нет Telegram: у `aidana` есть работы во всех четырёх статусах, и
# только под ней проверяются кабинет, профиль и библиотека.
DEMO_USERNAME = 'aidana'


def _sign_in_demo_user(request) -> bool:
    """Подписать в демо-аккаунт. False — если его нет в базе.

    `backend` передаётся явно: пользователь взят запросом, а не через
    `authenticate()`, и Django неоткуда узнать, кто за него отвечает.
    """
    user = User.objects.filter(username=DEMO_USERNAME, is_active=True).first()
    if user is None:
        logger.warning(
            'Демо-вход невозможен: пользователя %r нет в базе. '
            'Корпус кладёт команда `manage.py seed_demo`.', DEMO_USERNAME)
        return False
    auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return True


# Что видит человек, когда демо-аккаунта нет. Причину — в лог, не на
# страницу: «выполните seed_demo» адресовано не тому, кто это читает.
_SIGN_IN_FAILED = 'Кіру уақытша мүмкін емес. Сәл кейінірек қайта көр.'


def login_view(request):
    if request.method == 'POST' and _sign_in_demo_user(request):
        return HttpResponseRedirect(_safe_next(request))
    return render(request, 'pages/auth/login.html', {
        'next': request.POST.get('next') or request.GET.get('next', ''),
        'error': _SIGN_IN_FAILED if request.method == 'POST' else '',
    })


@require_POST
def logout_view(request):
    # Без проверки «а вошёл ли»: `logout` на анонимном запросе — no-op,
    # и выход обязан оставаться идемпотентным.
    auth_logout(request)
    return redirect('core:home')


def signup(request):
    """Регистрация — та же дверь, что и вход (FR-AUTH-03).

    Форма свёрстана, но ничего не записывает: профиль заводится при первой
    авторизации через Telegram, а до неё придуманный ник некуда сохранять —
    аккаунт создаётся не здесь. Поля формы поэтому не читаются, а не
    читаются наполовину: `name` уезжал в сессию под видом имени автора и
    показывался в приветствии человеку, которого в базе не существовало.
    """
    if request.method == 'POST' and _sign_in_demo_user(request):
        return redirect('core:signup_success')
    return render(request, 'pages/auth/signup.html', {
        'error': _SIGN_IN_FAILED if request.method == 'POST' else '',
    })


def signup_success(request):
    return render(request, 'pages/auth/signup_success.html')
