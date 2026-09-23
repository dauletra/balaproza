"""Политика конфиденциальности против модели.

Расхождение между этим текстом и базой случалось дважды, и оба раза
одинаково: поле удаляли миграцией, а обещание про него оставалось. Сперва
пропали настоящее имя и фото из Telegram — текст их обещал. Потом
следом из базы ушли возраст и пол — текст обещал и их, уже после того,
как раздел объявили переписанным по факту.

Ловить это чтением не выходит: политику читают раз в полгода, а поля
уходят между делом. Поэтому здесь список полей `User` объявлен **явно**,
и тест сверяет его с моделью в обе стороны. Поле ушло — тест падает и
называет его: значит, прежде чем вычеркнуть строку отсюда, кто-то
обязан посмотреть, не обещает ли его текст. Поле появилось — тест падает
тоже: новое поле у пользователя детской площадки не должно заводиться
молча.

Чего этот файл **не** проверяет: что прозу читали. Текст «жынысың
сақталмайды» содержит слово «жынысың», и запрет на слова отличить
обещание от его отрицания не может. Тест держит дверь, за которой стоит
человек, а не заменяет его.
"""

from django.test import TestCase
from django.urls import reverse

from core.domain.story import RECENT_VIEWS_DAYS
from core.models import User


# ── Что о пользователе хранится и где об этом сказано ─────────────────────
#
# Ключ — имя поля `User`, значение — то, чем политика его называет.
# Значение ищется на странице как подстрока: точной формулировке тест не
# судья, а вот пропасть целиком поле не должно.
PERSONAL_FIELDS = {
    'pen_name':         'авторлық ат',
    'username':         '@username',
    'bio':              'өзің туралы',
    'avatar':           'аватар',
    'telegram_id':      'Telegram ID',
    # Три семьи Telegram-уведомлений политика описывает вместе, одним
    # абзацем: человеку важно, что выбор есть и где он лежит, а не имена
    # трёх колонок.
    'telegram_push':    'Telegram-хабарлама',
    'push_moderation':  'Telegram-хабарлама',
    'push_response':    'Telegram-хабарлама',
    'push_new_chapter': 'Telegram-хабарлама',
}

# Поля, о которых политике сказать нечего, и почему.
HOUSEKEEPING_FIELDS = {
    'id':                'ключ строки',
    'password':          'входа по паролю нет — у всех он нерабочий',
    'last_login':        'служебная отметка django.contrib.auth',
    'is_active':         'служебный флаг',
    'is_staff':          'роль модератора, а не данные о человеке',
    'is_superuser':      'роль, а не данные о человеке',
    'date_joined':       'момент регистрации, виден самому человеку',
    'email':             'не спрашивается ни одной формой портала',
    'followers':         'счётчик подписчиков — производное от подписок',
    'terms_accepted_at': 'акт согласия; про само согласие говорит онбординг',
}


class PrivacyPolicyMatchesTheModel(TestCase):
    """Текст обещает ровно то, что хранит база."""

    def setUp(self):
        super().setUp()
        self.body = self.client.get(
            reverse('core:legal_privacy')).content.decode()

    @staticmethod
    def _model_fields() -> set:
        return {f.name for f in User._meta.get_fields()
                if getattr(f, 'concrete', False)}

    def test_every_field_of_the_user_is_classified(self):
        """Дверь, ради которой весь файл.

        Поле ушло из модели, а строка осталась здесь — значит где-то
        осталось и обещание. Поле появилось, а строки нет — значит о нём
        не решили, персональное оно или служебное.
        """
        declared = set(PERSONAL_FIELDS) | set(HOUSEKEEPING_FIELDS)
        actual = self._model_fields()

        self.assertEqual(
            declared - actual, set(),
            'поля больше нет у модели — проверь, не обещает ли его '
            'политика конфиденциальности, и убери строку отсюда')
        self.assertEqual(
            actual - declared, set(),
            'у пользователя новое поле — реши, персональное оно или '
            'служебное, и если персональное, скажи о нём в политике')

    def test_the_policy_names_every_personal_field(self):
        for field, phrase in PERSONAL_FIELDS.items():
            with self.subTest(field=field):
                self.assertIn(
                    phrase, self.body,
                    f'политика молчит о поле `{field}`')

    def test_the_policy_names_what_it_knows_about_reading(self):
        """Второе направление того же расхождения.

        «Мы это не показываем» и «мы это не храним» — разные утверждения.
        Полка, закладка и журнал оқылым посторонним не видны, но
        хранятся, и молчать о них политика не вправе.
        """
        for phrase in ('кітапхана', 'бөлімде тоқтадың', 'оқылым'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.body)

    def test_the_stated_retention_matches_the_window_in_code(self):
        """Срок жизни журнала назван человеку словами, а считается
        константой. Разойтись им нельзя: сдвиньте окно — и текст начнёт
        обещать не тот срок, ровно как было с датой рождения."""
        self.assertEqual(RECENT_VIEWS_DAYS, 14,
                         'окно журнала оқылым сдвинулось — в политике '
                         'написано «екі апта», поправь текст вместе с ним')
        self.assertIn('екі апта', self.body)

    # Проверки «канал для формальных обращений — ролевой, а не личный»
    # здесь намеренно нет: адрес пока личный, и это решение, а не
    # недосмотр (домена ещё нет). Тест, написанный вперёд решения, был бы
    # красным по плану, а красный по плану тест перестают читать.
    # Пункт живёт открытым в LAUNCH.md (домен и ролевая почта).


class ContactsLiveInOnePlace(TestCase):
    """Почта и каналы платформы — `core/domain/contacts.py`, и оттуда их
    берут правовые тексты, подвал и страница после регистрации. Литерал
    почты в подвале пережил бы замену личного адреса ролевым."""

    def test_the_footer_carries_the_same_address_as_the_policy(self):
        from core.domain.contacts import CONTACT_EMAIL, social_links
        page = self.client.get(reverse('core:home')).content.decode()
        self.assertIn(f'mailto:{CONTACT_EMAIL}', page)
        for link in social_links():
            with self.subTest(channel=link['label']):
                self.assertIn(f'href="{link["url"]}"', page)
        policy = self.client.get(reverse('core:legal_privacy')).content.decode()
        self.assertIn(CONTACT_EMAIL, policy)

    def test_a_channel_without_an_address_is_not_drawn(self):
        from core.domain.contacts import SOCIAL_CHANNELS, social_links
        shown = {link['label'] for link in social_links()}
        for _, label, url in SOCIAL_CHANNELS:
            with self.subTest(channel=label):
                self.assertEqual(label in shown, bool(url))
