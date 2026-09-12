"""Вход, выход и онбординг (FR-AUTH-*, NFR-25).

Провайдер личности — Telegram Login Widget, redirect-режим: кнопка ведёт
на Telegram, тот подписывает данные пользователя и редиректит браузер на
`telegram_callback` с параметрами в query string. Проверка подписи —
`domain.telegram.verify_telegram_auth`, чистая функция без Django;
здесь только её вызов и то, что вокруг: логин сессии, онбординг.
"""

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .. import data
from ..domain.telegram import verify_telegram_auth
from ..forms import OnboardingForm
from .common import _safe_next

logger = logging.getLogger(__name__)

# Поля, которые действительно шлёт Telegram (документация Login Widget).
# `request.GET` может нести и наше собственное `next` — оно не входит в
# подписанные данные, и если пропустить его в проверку подписи, hash
# никогда не совпадёт: Telegram подписывал данные без него.
_TELEGRAM_FIELDS = ('id', 'first_name', 'last_name', 'username', 'photo_url',
                    'auth_date', 'hash')

# Что видит человек при неудачном входе. Причина — в лог, не на страницу.
_SIGN_IN_FAILED = 'Кіру сәтсіз аяқталды. Сәл кейінірек қайта көр.'


def _telegram_login_context(request) -> dict:
    """Данные для кнопки виджета: куда слать (с сохранённым `next`) и чей
    бот. Пустой `TELEGRAM_BOT_USERNAME` — только в dev без бота (шаблон
    показывает заглушку вместо виджета)."""
    next_url = request.GET.get('next', '')
    auth_url = request.build_absolute_uri(reverse('core:telegram_callback'))
    if next_url:
        auth_url = f'{auth_url}?{urlencode({"next": next_url})}'
    return {
        'telegram_bot_username': settings.TELEGRAM_BOT_USERNAME,
        'telegram_auth_url':     auth_url,
        'next':                  next_url,
    }


def login_view(request):
    """Уже вошедшему тут делать нечего (тот же виджет предложил бы
    войти ещё раз) — уводим на `next`, если он безопасный, иначе в
    профиль. Тот же приём, что у `onboarding` для завершённого
    автора."""
    if request.user.is_authenticated:
        return redirect(_safe_next(request, fallback_url=reverse('core:profile_me')))
    return render(request, 'pages/auth/login.html', _telegram_login_context(request))


def telegram_callback(request):
    """Куда Telegram редиректит после согласия пользователя. `id` — telegram_id
    (FR-AUTH-01); первый вход заводит аккаунт (FR-AUTH-03) и ведёт на
    онбординг, повторный — сразу на `next`."""
    params = {k: v for k, v in request.GET.items() if k in _TELEGRAM_FIELDS}
    reason = verify_telegram_auth(params, settings.TELEGRAM_BOT_TOKEN)
    if reason:
        logger.warning('Telegram-кіру қабылданбады: %s', reason)
        return render(request, 'pages/auth/login.html', {
            **_telegram_login_context(request),
            'error': _SIGN_IN_FAILED,
        })

    user, created = data.get_or_create_telegram_user(int(params['id']))
    auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')

    next_url = _safe_next(request)
    if created:
        return redirect(f"{reverse('core:onboarding')}?{urlencode({'next': next_url})}")
    return redirect(next_url)


@require_POST
def logout_view(request):
    # Без проверки «а вошёл ли»: `logout` на анонимном запросе — no-op,
    # и выход обязан оставаться идемпотентным.
    auth_logout(request)
    return redirect('core:home')


def onboarding(request):
    """Онбординг после первого входа (FR-AUTH-03/04/05/06). Завершённость —
    `terms_accepted_at` (BR-90): повторный заход сюда уже онбордившегося
    автора не должен спрашивать те же поля снова."""
    if not request.user.is_authenticated:
        return redirect(f"{reverse('core:login')}?{urlencode({'next': _safe_next(request)})}")
    if request.user.terms_accepted_at:
        return redirect('core:profile_me')

    if request.method == 'POST':
        form = OnboardingForm(request.POST)
        if form.is_valid():
            data.complete_onboarding(
                request.user,
                pen_name=form.cleaned_data['pen_name'],
                bio=form.cleaned_data['bio'],
                birth_date=form.cleaned_data['birth_date'],
                gender=form.cleaned_data['gender'],
            )
            return redirect('core:signup_success')
    else:
        form = OnboardingForm()

    return render(request, 'pages/auth/onboarding.html', {'form': form})


def signup_success(request):
    return render(request, 'pages/auth/signup_success.html')
