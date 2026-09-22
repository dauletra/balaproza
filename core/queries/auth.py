"""Вход и онбординг."""

from django.utils import timezone
from django.utils.crypto import get_random_string

from ..models import User


def _unique_username() -> str:
    """`id` + 6 случайных цифр — как `_unique_story_slug`
    (`core/queries/write.py`), но без исходного текста: username при
    первом входе не несёт ни telegram_id, ни имени — его правят
    вручную потом, отдельной задачей."""
    while True:
        candidate = f'id{get_random_string(6, allowed_chars="0123456789")}'
        if not User.objects.filter(username=candidate).exists():
            return candidate


def find_telegram_user(telegram_id: int) -> User | None:
    """Найти по `telegram_id`, не заводя нового — для callback: пока анкета
    не отправлена, аккаунт заводить рано (отказ от регистрации иначе
    оставлял бы недозаполненную запись)."""
    return User.objects.filter(telegram_id=telegram_id).first()


def get_or_create_telegram_user(telegram_id: int) -> tuple[User, bool]:
    """Найти по `telegram_id` или завести нового.

    Аккаунт заводит первая авторизация — точнее, её завершение анкетой
    (`onboarding`). Второй элемент — правда ли создан только что."""
    return User.objects.get_or_create(
        telegram_id=telegram_id, defaults={'username': _unique_username()})


def complete_onboarding(user: User, *, pen_name: str, bio: str) -> User:
    """Онбординг после первого входа. `terms_accepted_at` —
    акт согласия; его дата и делает регистрацию завершённой,
 отдельного флага нет.

    Полей два. Возраст и пол не спрашиваются вовсе (D4/D5): ни то, ни
    другое нигде не использовалось, а на детской площадке каждое поле —
    обязательство."""
    user.pen_name = pen_name
    user.bio = bio
    user.terms_accepted_at = timezone.now()
    user.save(update_fields=['pen_name', 'bio', 'terms_accepted_at'])
    return user
