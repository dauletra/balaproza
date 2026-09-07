"""Вход и онбординг (FR-AUTH-*, NFR-25)."""

from django.utils import timezone
from django.utils.crypto import get_random_string

from ..models import User


def _unique_username() -> str:
    """`id` + 6 случайных цифр — как `_unique_story_slug`
    (`core/queries/write.py`), но без исходного текста: username при
    первом входе не несёт ни telegram_id, ни имени (BR-90) — его правят
    вручную потом, отдельной задачей."""
    while True:
        candidate = f'id{get_random_string(6, allowed_chars="0123456789")}'
        if not User.objects.filter(username=candidate).exists():
            return candidate


def get_or_create_telegram_user(telegram_id: int) -> tuple[User, bool]:
    """Найти по `telegram_id` или завести нового (FR-AUTH-03: аккаунт
    заводит первая авторизация). Второй элемент — правда ли создан
    только что, им решается, вести ли на онбординг."""
    return User.objects.get_or_create(
        telegram_id=telegram_id, defaults={'username': _unique_username()})


def complete_onboarding(user: User, *, name: str, bio: str, age, gender: str) -> User:
    """Онбординг после первого входа (FR-AUTH-04). `terms_accepted_at` —
    акт согласия (FR-AUTH-05); его дата и делает регистрацию завершённой
    (BR-90), отдельного флага нет."""
    user.name = name
    user.bio = bio
    user.age = age
    user.gender = gender
    user.terms_accepted_at = timezone.now()
    user.save(update_fields=['name', 'bio', 'age', 'gender', 'terms_accepted_at'])
    return user
