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
from django.contrib import messages
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
    (FR-AUTH-01). Уже заведённый аккаунт логинится сразу и уходит на `next`;
    первый визит аккаунт ещё не заводит — подтверждённый `telegram_id` ждёт
    анкету в сессии (`pending_telegram_id`), а не в базе, чтобы отказ от
    регистрации не оставлял недозаполненную запись (см. `onboarding`,
    `decline_onboarding`)."""
    params = {k: v for k, v in request.GET.items() if k in _TELEGRAM_FIELDS}
    reason = verify_telegram_auth(params, settings.TELEGRAM_BOT_TOKEN)
    if reason:
        logger.warning('Telegram-кіру қабылданбады: %s', reason)
        return render(request, 'pages/auth/login.html', {
            **_telegram_login_context(request),
            'error': _SIGN_IN_FAILED,
        })

    telegram_id = int(params['id'])
    next_url = _safe_next(request)

    user = data.find_telegram_user(telegram_id)
    if user is None:
        request.session['pending_telegram_id'] = telegram_id
        return redirect(f"{reverse('core:onboarding')}?{urlencode({'next': next_url})}")

    auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
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
    автора не должен спрашивать те же поля снова.

    Две разные заготовки аккаунта могут оказаться тут, и обе — законные:
    уже вошедший без анкеты (`login_as_newcomer(onboarded=False)` в тестах,
    возможен и в проде — например, недоведённая до конца прошлая попытка)
    заполняет `request.user`; первый визит по Telegram — анонимный,
    `pending_telegram_id` ждёт в сессии (см. `telegram_callback`), и
    аккаунт заводится только на валидном сабмите, не раньше."""
    pending_id = None
    if request.user.is_authenticated:
        if request.user.terms_accepted_at:
            return redirect('core:profile_me')
        user = request.user
    else:
        pending_id = request.session.get('pending_telegram_id')
        if not pending_id:
            return redirect(f"{reverse('core:login')}?{urlencode({'next': _safe_next(request)})}")
        user = None

    if request.method == 'POST':
        form = OnboardingForm(request.POST)
        if form.is_valid():
            if user is None:
                user, _ = data.get_or_create_telegram_user(pending_id)
                auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                del request.session['pending_telegram_id']
            data.complete_onboarding(
                user,
                pen_name=form.cleaned_data['pen_name'],
                bio=form.cleaned_data['bio'],
                birth_date=form.cleaned_data['birth_date'],
                gender=form.cleaned_data['gender'],
            )
            return redirect('core:signup_success')
    else:
        form = OnboardingForm()

    return render(request, 'pages/auth/onboarding.html', {'form': form})


@require_POST
def decline_onboarding(request):
    """«Тіркеуден бас тарту» — единственный выход с гейтованной анкеты.
    Закрывает обе заготовки из `onboarding` по-разному: у анонимной
    (`pending_telegram_id`) в базе ничего нет, стереть нечего, кроме ключа
    сессии; у уже вошедшей без анкеты аккаунт уже существует — тот же приём,
    что у `delete_account` (`user` захвачен до `logout()`, который подменяет
    `request.user` на `AnonymousUser`)."""
    if request.user.is_authenticated:
        user = request.user
        auth_logout(request)
        user.delete()
    else:
        request.session.pop('pending_telegram_id', None)
    messages.info(request, 'Тіркеу тоқтатылды.')
    return redirect('core:home')


def signup_success(request):
    return render(request, 'pages/auth/signup_success.html')
