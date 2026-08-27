"""Правовые и информационные страницы — пока стабы.

Контент готовит контент-менеджер; страницы существуют, чтобы ссылки в
подвале не вели в пустоту (FR-AUTH-05).
"""

from django.shortcuts import render

# ───────────────────── LEGAL/INFO — статичные правовые стабы ──────────────
# Stub-контент. Финальный текст готовит контент-менеджер. Используются для
# того чтобы footer-ссылки не вели в пустоту (FR-AUTH-05, docs/ui.md).
_LEGAL_PAGES = {
    'moderation_rules': {
        'title':    'Модерация ережелері',
        'subtitle': 'Қандай шығармалар платформаға жіберіледі және не үшін шеттетіледі.',
        'body':     '',  # заполнится контентщиком
    },
    'publishing_terms': {
        'title':    'Жариялау шарттары',
        'subtitle': 'Авторлық құқық, мазмұнға қойылатын талаптар, лицензия.',
        'body':     '',
    },
    'about': {
        'title':    'Проект туралы',
        'subtitle': 'Balaproza — жас прозаиктерге арналған қазақ тіліндегі әдеби алаң.',
        'body':     '',
    },
    'terms': {
        'title':    'Пайдалану ережелері',
        'subtitle': 'Сервистің жалпы шарттары.',
        'body':     '',
    },
    'privacy': {
        'title':    'Құпиялылық саясаты',
        'subtitle': 'Дербес деректерді жинау, сақтау және өңдеу туралы.',
        'body':     '',
    },
}


def _legal(key):
    page = _LEGAL_PAGES[key]
    def view(request):
        return render(request, 'pages/legal.html', {
            'page_title':    page['title'],
            'page_subtitle': page['subtitle'],
            'page_body':     page['body'],
            'last_updated':  None,
        })
    view.__name__ = f'legal_{key}'
    return view


legal_moderation_rules = _legal('moderation_rules')


legal_publishing_terms = _legal('publishing_terms')


legal_about            = _legal('about')


legal_terms            = _legal('terms')


legal_privacy          = _legal('privacy')
