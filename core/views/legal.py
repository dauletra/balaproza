"""Правовые и информационные страницы.

Сам текст — в [`core/legal_texts.py`](../legal_texts.py), вместе с историей
того, почему он привязан к модели тестом. Здесь только пять одинаковых
вью: страницы различаются содержимым, а не устройством.
"""

from django.shortcuts import render

from ..legal_texts import LEGAL_PAGES


def _legal(key):
    page = LEGAL_PAGES[key]
    def view(request):
        return render(request, 'pages/legal.html', {
            'page_title':    page['title'],
            'page_subtitle': page['subtitle'],
            'page_body':     page['body'],
            'last_updated':  page['last_updated'],
        })
    view.__name__ = f'legal_{key}'
    return view


legal_moderation_rules = _legal('moderation_rules')


legal_publishing_terms = _legal('publishing_terms')


legal_about            = _legal('about')


legal_terms            = _legal('terms')


legal_privacy          = _legal('privacy')
