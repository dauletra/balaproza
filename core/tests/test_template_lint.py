"""Проверки шаблонов — ловят конструкции, которые молча не работают.

Общий знаменатель: ошибка не падает, не пишет в консоль и не видна при ревью.
Тег, разорванный переносом строки, перестаёт быть тегом и утекает на страницу
видимым текстом. Alpine-директива вне `x-data` остаётся мёртвым атрибутом, и
кнопка просто ничего не делает. И то и другое заметно только на живом сайте.
"""

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from core.tests.base import TestCase, login_as

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

        login_as(self.client)

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


class TabRolesPromiseAPanel(TestCase):
    """`role="tab"` без `role="tabpanel"` на той же странице — сломанное обещание.

    Роль `tab` говорит скринридеру: рядом есть панель, связанная через
    `aria-controls`, и сегменты переключаются стрелками без перезагрузки.
    `components/segmented_control.html` носил `role="tablist"` и `role="tab"`,
    а был обычной навигацией по `?tab=` с полным перезапросом страницы:
    NVDA объявлял «вкладка 1 из 4», стрелка не делала ничего.

    Лint общий, а не про профиль: настоящий `tablist` в проекте появиться
    может — но только вместе с панелью.
    """

    def test_no_tab_role_without_a_tabpanel(self):
        from django.urls import reverse
        from core.tests.test_urls_smoke import PUBLIC_URLS

        login_as(self.client)

        offenders = []
        for name, kwargs, label in PUBLIC_URLS:
            html = self.client.get(reverse(name, kwargs=kwargs)).content.decode()
            if 'role="tab"' in html and 'role="tabpanel"' not in html:
                offenders.append(label)

        self.assertFalse(
            offenders,
            'role="tab" обещает панель, которой на странице нет. Для навигации '
            'по URL нужен <nav> + aria-current="page", а не роли табов:\n  '
            + '\n  '.join(offenders),
        )


class IconIncludesAreIsolated(unittest.TestCase):
    """`components/icon.html` подключается только с `only`.

    `{% include … with … %}` наследует весь родительский контекст. У кнопки,
    бейджа и пилюли есть параметр `label`, и он молча доезжал до иконки —
    та превращалась в `<svg role="img" aria-label="…">` с той же подписью,
    что и стоящий рядом текст. Скринридер читал её дважды.

    Ни один вызов в проекте не передаёт `label` иконке осознанно, так что
    все такие имена были результатом утечки.
    """

    def test_every_icon_include_carries_only(self):
        offenders = []
        for path in _templates():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if 'include "components/icon.html"' not in line:
                    continue
                for fragment in line.split('include "components/icon.html"')[1:]:
                    tag = fragment.split("%}", 1)[0]
                    if " only" not in tag:
                        rel = path.relative_to(TEMPLATES_DIR.parent)
                        offenders.append(f"{rel}:{number}  {line.strip()[:70]}")

        self.assertFalse(
            offenders,
            "icon.html без `only` — родительский `label` утечёт в иконку и "
            "скринридер прочитает подпись дважды:\n" + "\n".join(offenders),
        )


class GenericElementsCarryNoAriaLabel(TestCase):
    """`aria-label` на `<span>`/`<div>` без роли не озвучивается.

    У обоих роль `generic`, а имя из `aria-label` ARIA разрешает выставлять
    только элементам с ролью, поддерживающей именование. Скринридеры такой
    атрибут игнорируют: подпись видна в разметке, в озвучке её нет.

    Так молча пропадали два места. Точка «оқылмаған» на уведомлении —
    единственный признак непрочитанного для незрячего — и счётчик ұнату в
    списке глав, где цифра вдобавок стояла под `aria-hidden`, то есть
    строка не озвучивалась целиком. То же правило уже записано для
    `stat_pill` в CLAUDE.md: подпись идёт `sr-only`, а не `aria-label`.

    Проверка по отрендеренному DOM: `role` может приезжать из включаемого
    компонента, а не стоять в том же файле.
    """

    GENERIC = {'span', 'div'}

    class _Scan(HTMLParser):
        def __init__(self, generic):
            super().__init__(convert_charrefs=True)
            self.generic = generic
            self.offenders = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag in self.generic and attrs.get('aria-label') and not attrs.get('role'):
                self.offenders.append((tag, attrs['aria-label']))

    def test_no_aria_label_on_a_roleless_generic(self):
        from django.urls import reverse
        from core.tests.test_urls_smoke import PUBLIC_URLS

        login_as(self.client)

        offenders = []
        for name, kwargs, label in PUBLIC_URLS:
            response = self.client.get(reverse(name, kwargs=kwargs))
            parser = self._Scan(self.GENERIC)
            parser.feed(response.content.decode())
            for tag, text in parser.offenders:
                offenders.append(f'{label}: <{tag} aria-label="{text}">')

        self.assertFalse(
            sorted(set(offenders)),
            'aria-label на элементе с ролью generic не озвучивается — подпись '
            'есть в разметке и отсутствует в озвучке. Вынеси её в <span '
            'class="sr-only">, а сам элемент пометь aria-hidden:\n  '
            + '\n  '.join(sorted(set(offenders))),
        )


class IconLabelsDoNotDuplicateText(TestCase):
    """Озвученная иконка не должна повторять текст, рядом с которым стоит.

    Дублирование ловим по отрендеренному DOM, а не по исходникам: подпись
    может доехать до иконки любым путём — через `include`, через `{% with %}`,
    через контекст-процессор. Правило одно: если у `<svg role="img">` имя
    совпадает с текстом его контейнера, это имя лишнее.
    """

    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
            'link', 'meta', 'source', 'track', 'wbr'}

    class _Scan(HTMLParser):
        def __init__(self, void):
            super().__init__(convert_charrefs=True)
            self.void = void
            self.stack = []        # [[tag, [текст], [подписи икон]]]
            self.duplicates = []

        def handle_starttag(self, tag, attrs):
            flat = dict(attrs)
            if tag == 'svg' and flat.get('role') == 'img' and flat.get('aria-label'):
                if self.stack:
                    self.stack[-1][2].append(flat['aria-label'])
            if tag not in self.void:
                self.stack.append([tag, [], []])

        def handle_data(self, data):
            if self.stack:
                self.stack[-1][1].append(data)

        def handle_endtag(self, tag):
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] != tag:
                    continue
                closed = self.stack[i]
                del self.stack[i:]
                text = " ".join("".join(closed[1]).split())
                for label in closed[2]:
                    if text and " ".join(label.split()) == text:
                        self.duplicates.append((closed[0], label))
                if self.stack:
                    self.stack[-1][1].append(text)
                return

    def test_no_icon_repeats_its_neighbours_text(self):
        from django.urls import reverse
        from core.tests.test_urls_smoke import PUBLIC_URLS

        login_as(self.client)

        offenders = []
        for name, kwargs, label in PUBLIC_URLS:
            parser = self._Scan(self.VOID)
            parser.feed(self.client.get(reverse(name, kwargs=kwargs)).content.decode())
            for tag, dup in parser.duplicates:
                offenders.append(f'{label}: <{tag}> — иконка повторяет «{dup}»')

        self.assertFalse(
            offenders,
            "Иконка озвучена тем же текстом, что и её контейнер — подпись "
            "прозвучит дважды. Убери label у иконки (обычно это утечка "
            "контекста, лечится `only`):\n  " + "\n  ".join(sorted(set(offenders))),
        )


class IconNamesExistInSprite(unittest.TestCase):
    """Имя иконки, которого нет в спрайте, рендерит пустой `<use>`.

    Пустой квадрат в консоль не пишет и в вёрстке почти не виден. Раньше
    все имена были литералами в шаблонах и проверялись глазами при ревью;
    с достижениями (FR-PROF-06) они приходят из `stub_data`, где опечатку
    заметить уже негде.
    """

    def _sprite_ids(self):
        body = (TEMPLATES_DIR / "components" / "icons" / "_sprite.html").read_text(
            encoding="utf-8")
        import re
        return {m.removeprefix("icon-")
                for m in re.findall(r'<symbol id="([a-z0-9-]+)"', body)}

    def _award_ids(self):
        body = (TEMPLATES_DIR / "components" / "awards" / "_sprite.html").read_text(
            encoding="utf-8")
        import re
        return {m.removeprefix("award-")
                for m in re.findall(r'<symbol id="(award-[a-z0-9-]+)"', body)}

    def test_award_art_exists_in_sprite(self):
        """Слаг иллюстрации приходит из данных — опечатку заметить негде."""
        from core import stub_data
        ids = self._award_ids()
        for a in stub_data.AUTHORS:
            for ach in stub_data.achievements_of(a.username):
                with self.subTest(author=a.username, art=ach["art"]):
                    self.assertIn(ach["art"], ids)

    def test_every_read_tier_has_art(self):
        from core import stub_data
        ids = self._award_ids()
        for art, _ in stub_data.READ_TIER_ART.values():
            with self.subTest(art=art):
                self.assertIn(art, ids)

    def test_award_sprite_has_no_orphan_symbols(self):
        """Символ, на который никто не ссылается, — мёртвый вес на странице."""
        from core import stub_data
        used = {a[0] for a in stub_data.READ_TIER_ART.values()}
        for author in stub_data.AUTHORS:
            used |= {x["art"] for x in stub_data.achievements_of(author.username)}
        self.assertEqual(self._award_ids() - used, set())

    def test_template_icon_literals_exist(self):
        import re
        ids = self._sprite_ids()
        for path in _templates():
            body = path.read_text(encoding="utf-8")
            for name in re.findall(r'icon\.html" with name="([a-z0-9-]+)"', body):
                with self.subTest(template=path.name, icon=name):
                    self.assertIn(name, ids)


class PlatformDoesNotNameItsAudience(TestCase):
    """Продукт не объявляет, для кого он (DEC-47, BR-48).

    Аудитория — внутренняя информация: платформой пользуются и школьники,
    и студенты колледжей и вузов. Пока возрастной ценз был правилом
    платформы (прежнее BR-20), «14-18» стояло в подсказке поля на
    регистрации и в редактировании профиля — то есть каждый, кто доходил
    до формы, читал, что здесь для 14-18 лет, ещё не увидев ни одного
    конкурса.

    **Возрастная вилка законна ровно в одном месте — на странице
    конкретного конкурса**, где это его собственное условие (BR-48).
    Поэтому маршруты конкурсов из проверки исключены, а все остальные
    обязаны молчать.

    Проверка идёт и по отрендеренному HTML, и по исходникам шаблонов:
    первое ловит текст, попавший на экран, второе — вилку, вписанную
    литералом вместо `Contest.eligibility_line`.
    """

    # «14-18 жас», «14–18 жас», «10-18 лет» — вилка рядом со словом о возрасте.
    AGE_BRACKET = re.compile(r'\d{1,2}\s*[-–—]\s*\d{1,2}\s*(жас|лет|года|жыл)')

    # Слова, которыми продукт назвал бы свою аудиторию как целое.
    AUDIENCE_WORDS = ('оқушыларға арналған платформа', 'жасөспірімдерге арналған платформа')

    @staticmethod
    def _platform_urls():
        """Все публичные маршруты, кроме конкурсных.

        У конкурса своя вилка — она обязана быть видна, иначе автор не
        узнает, подавать ли ему.
        """
        from core.tests.test_urls_smoke import PUBLIC_URLS
        return [(n, kw, label) for n, kw, label in PUBLIC_URLS
                if not n.startswith('core:contest')]

    def test_rendered_pages_name_no_age_bracket(self):
        from django.urls import reverse
        for name, kwargs, label in self._platform_urls():
            with self.subTest(page=label):
                html = self.client.get(reverse(name, kwargs=kwargs)).content.decode()
                found = self.AGE_BRACKET.search(html)
                self.assertIsNone(
                    found,
                    f'{label}: страница называет возрастную вилку '
                    f'«{found.group(0) if found else ""}». Ценз ставит конкурс, '
                    f'не платформа (BR-48)')

    def test_rendered_pages_do_not_declare_the_audience(self):
        from django.urls import reverse
        for name, kwargs, label in self._platform_urls():
            with self.subTest(page=label):
                html = self.client.get(reverse(name, kwargs=kwargs)).content.decode().lower()
                for word in self.AUDIENCE_WORDS:
                    self.assertNotIn(word, html, f'{label}: продукт объявляет аудиторию')

    def test_no_template_hardcodes_an_age_bracket(self):
        """Вилка приходит из данных конкурса, а не вписывается в шаблон."""
        for path in _templates():
            body = path.read_text(encoding='utf-8')
            # Комментарии объясняют правило и потому называют старую строку.
            body = re.sub(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', '',
                          body, flags=re.S)
            body = re.sub(r'\{#.*?#\}', '', body, flags=re.S)
            with self.subTest(template=path.name):
                found = self.AGE_BRACKET.search(body)
                self.assertIsNone(
                    found,
                    f'{path.name}: вилка «{found.group(0) if found else ""}» вписана '
                    f'литералом — она должна приходить из `Contest.eligibility_line`')
