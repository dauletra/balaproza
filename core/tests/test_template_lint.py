"""Проверки шаблонов — ловят конструкции, которые молча не работают.

Общий знаменатель: ошибка не падает, не пишет в консоль и не видна при ревью.
Тег, разорванный переносом строки, перестаёт быть тегом и утекает на страницу
видимым текстом. Alpine-директива вне `x-data` остаётся мёртвым атрибутом, и
кнопка просто ничего не делает. И то и другое заметно только на живом сайте.
"""

import unittest
from html.parser import HTMLParser
from pathlib import Path

from django.test import TestCase

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


def _templates():
    return sorted(TEMPLATES_DIR.rglob("*.html"))


class TemplateCommentSyntax(unittest.TestCase):

    def test_no_multiline_hash_comments(self):
        """`{# … #}` — только однострочный.

        Django закрывает такой комментарий на первом же `#}` в той же строке;
        всё, что перенесено ниже, попадает в разметку как обычный текст.
        Для многострочных пояснений есть `{% comment %}…{% endcomment %}`.
        """
        offenders = []
        for path in _templates():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "{#" not in line:
                    continue
                if "#}" not in line.split("{#", 1)[1]:
                    rel = path.relative_to(TEMPLATES_DIR.parent)
                    offenders.append(f"{rel}:{number}  {line.strip()[:60]}")

        self.assertFalse(
            offenders,
            "Многострочный {# #} — хвост утечёт на страницу. "
            "Используй {% comment %}…{% endcomment %}:\n" + "\n".join(offenders),
        )


class TemplateTagSyntax(unittest.TestCase):

    def test_no_multiline_template_tags(self):
        """`{% … %}` тоже не переживает перенос строки (CLAUDE.md).

        Чаще всего ломается `{% include … with … %}` с длинным списком
        параметров: он выводится на страницу как plain-текст.
        """
        offenders = []
        for path in _templates():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "{%" not in line:
                    continue
                if "%}" not in line.split("{%", 1)[1]:
                    rel = path.relative_to(TEMPLATES_DIR.parent)
                    offenders.append(f"{rel}:{number}  {line.strip()[:60]}")

        self.assertFalse(
            offenders,
            "Тег {% %} разорван переносом строки — Django выведет его текстом:\n"
            + "\n".join(offenders),
        )


class AlpineDirectivesAreInScope(TestCase):
    """`@click` без `x-data` в предках — кнопка, которая ничего не делает.

    Alpine 3 инициализирует только поддеревья, найденные по `x-data`: элементы
    вне такого корня он не обходит вовсе. Директива на них остаётся мёртвым
    атрибутом — ни ошибки в консоли, ни визуального отличия. Кнопка выглядит
    как кнопка, нажимается как кнопка и не делает ничего.

    Так молча не работали кнопка сүзгі каталога, «Іздеу ашу» на 404, обе
    кнопки удаления произведения и семь форм с `@submit.prevent` — последние
    вдобавок уходили настоящим POST вместо демо-тоста.

    Проверка идёт по отрендеренному HTML, а не по исходникам: предок с
    `x-data` часто лежит в другом файле, за `{% include %}` или `{% extends %}`.
    """

    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
            'link', 'meta', 'source', 'track', 'wbr'}

    class _Scan(HTMLParser):
        def __init__(self, void):
            super().__init__(convert_charrefs=True)
            self.void = void
            self.stack = []       # [(tag, внутри ли x-data-корня)]
            self.orphans = []

        @staticmethod
        def _directives(attrs):
            return [k for k, _ in attrs
                    if k.startswith('x-') or k.startswith('@') or k.startswith(':')]

        def handle_starttag(self, tag, attrs):
            is_root = 'x-data' in [k for k, _ in attrs]
            inside = any(scoped for _, scoped in self.stack)
            found = self._directives(attrs)
            if found and not is_root and not inside:
                self.orphans.append((tag, found))
            if tag not in self.void:
                self.stack.append((tag, is_root or inside))

        def handle_endtag(self, tag):
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    return

    def _orphans(self, html):
        parser = self._Scan(self.VOID)
        parser.feed(html)
        return parser.orphans

    def test_no_directive_outside_an_x_data_root(self):
        from django.urls import reverse
        from core.tests.test_urls_smoke import PUBLIC_URLS

        session = self.client.session
        session['signed_in'] = True
        session['user_name'] = 'Айдана'
        session['user_username'] = 'aidana'
        session.save()

        offenders = []
        for name, kwargs, label in PUBLIC_URLS:
            response = self.client.get(reverse(name, kwargs=kwargs))
            for tag, directives in self._orphans(response.content.decode()):
                offenders.append(f'{label}: <{tag} {" ".join(directives)}>')

        self.assertFalse(
            offenders,
            'Alpine-директива вне поддерева с x-data — обработчик не навесится, '
            'элемент останется мёртвым без единой ошибки в консоли. '
            'Добавь пустой x-data на сам элемент или на его контейнер:\n  '
            + '\n  '.join(offenders),
        )
