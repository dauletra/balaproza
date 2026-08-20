"""Статические проверки шаблонов — ловят конструкции, которые Django молча
рендерит как текст вместо того, чтобы обработать.

Обе проверки здесь про один и тот же класс ошибок: тег, разорванный переносом
строки, перестаёт быть тегом и утекает на страницу видимым текстом. Глазами при
ревью это не ловится — на странице появляется абзац из комментария или куска
`{% include %}`, и заметен он только на живом сайте.
"""

import unittest
from pathlib import Path

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
