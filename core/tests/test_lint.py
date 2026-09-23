"""Каркас разметки: конструкции, которые молча не работают.

Общий знаменатель — **ошибка не видна ни при ревью, ни на зелёной
суите**. Тег, разорванный переносом, перестаёт быть тегом и утекает на
страницу текстом. Alpine-директива вне `x-data` остаётся мёртвым
атрибутом: кнопка выглядит как кнопка, нажимается как кнопка и не делает
ничего. Имя компонента, которого нет в `components.js`, не ошибка для
браузера — просто ничего не происходит.

Ни одна из этих проверок не про требование — все про то, что разметка
делает не то, что написано в ней глазами.

Доступность — в `test_lint_a11y.py`, раскладка — в `test_lint_layout.py`.
Общие пути шаблонов и статики объявлены здесь: оба файла берут их
отсюда, чтобы «где лежат шаблоны» не оказалось записано трижды.
"""

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from django.urls import reverse

from core import data
from core.tests.base import TestCase, login_as


_ROOT = Path(__file__).resolve().parent.parent.parent

TEMPLATES_DIR = _ROOT / "templates"
STATIC_DIR = _ROOT / "static"
STATIC_SRC_DIR = _ROOT / "static_src"


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


class NumbersUseTheProjectFilters(unittest.TestCase):
    """`stringformat` не форматирует число — он только делает из него строку.

    Разряды портала ставят `compact_count` (читателю) и `spaced` (автору),
    и оба уже возвращают строку, то есть годятся для `add:` без посредника.
    А `stringformat` в той же позиции выводит число сплошняком: шапка
    произведения показывала «12482 оқылым» строкой ниже «12,5 мың реакция»
    — два разных вида одной величины на одном экране.

    Одно применение остаётся законным и здесь не запрещается:
    `{% with chap=N|stringformat:"d" %}` для сборки адреса
    `?chapter=N#chapter-N`. Там нужна именно голая цифра — разряд с
    неразрывным пробелом сломал бы ссылку.
    """

    # `"s"` не делает вообще ничего, кроме `str()`; `"d"`, воткнутый прямо
    # в `add:`, — это отображаемое число, а не адрес.
    BANNED = (
        (re.compile(r'stringformat:"s"'), 'stringformat:"s"'),
        (re.compile(r'stringformat:"d"\|add:'), 'stringformat:"d"|add:'),
    )

    def test_metrics_do_not_go_through_stringformat(self):
        offenders = []
        for path in _templates():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for pattern, shown in self.BANNED:
                    if pattern.search(line):
                        rel = path.relative_to(TEMPLATES_DIR.parent)
                        offenders.append(f"{rel}:{number}  {shown}")

        self.assertFalse(
            offenders,
            "Число выводится через stringformat — разрядов не будет. "
            "Читателю `compact_count`, автору `spaced`:\n" + "\n".join(offenders),
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
        from core.tests.test_smoke import PUBLIC_URLS

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


class NamedComponentsAreRegistered(unittest.TestCase):
    """`x-data="имя(...)"` без `Alpine.data('имя')` — мёртвое поддерево.

    Компоненты живут в `static/js/`, а зовут их из разметки по имени, и
    связь между двумя файлами держится только на совпадении строки.
    Промах даёт не поломку, а тишину: Alpine не находит имя, поддерево
    не инициализируется, и элемент выглядит рабочим — та же порода
    ошибки, что и директива вне `x-data` (класс выше).

    Объектный литерал (`x-data="{ open: false }"`) регистрации не требует
    и сюда не попадает: состояние из одного слова читается там же, где
    используется, и имя ему только развело бы его по двум файлам.
    """

    ROOT = Path(__file__).resolve().parent.parent.parent

    # `x-data="storyReader()"`, `x-data="tagInput({…"` — имя и открывающая скобка.
    CALL = re.compile(r'x-data="([A-Za-z_]\w*)\s*\(')

    def _registered(self):
        names = set()
        for path in (self.ROOT / "static" / "js").glob("*.js"):
            names |= set(re.findall(r"Alpine\.data\(\s*'(\w+)'",
                                    path.read_text(encoding="utf-8")))
        return names

    def test_every_named_component_exists_in_static_js(self):
        registered = self._registered()
        self.assertTrue(registered, "в static/js/ не найдено ни одного Alpine.data")

        offenders = []
        for path in _templates():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for name in self.CALL.findall(line):
                    if name not in registered:
                        rel = path.relative_to(TEMPLATES_DIR.parent)
                        offenders.append(f"{rel}:{number}  {name}()")

        self.assertFalse(
            offenders,
            "x-data зовёт компонент, которого нет в static/js/ — поддерево "
            "не поднимется, и элемент останется мёртвым:\n  "
            + "\n  ".join(offenders),
        )

    def test_no_component_is_registered_and_never_used(self):
        """Обратная сторона: компонент, которого никто не зовёт, — мёртвый вес."""
        used = set()
        for path in _templates():
            used |= set(self.CALL.findall(path.read_text(encoding="utf-8")))
        self.assertEqual(self._registered() - used, set())


class IconNamesExistInSprite(TestCase):
    """Имя иконки, которого нет в спрайте, рендерит пустой `<use>`.

    Пустой квадрат в консоль не пишет и в вёрстке почти не виден. Раньше
    все имена были литералами в шаблонах и проверялись глазами при ревью;
    с достижениями они приходят из данных, где опечатку
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
        ids = self._award_ids()
        for a in data.all_authors():
            for ach in data.achievements_of(a):
                with self.subTest(author=a.username, art=ach["art"]):
                    self.assertIn(ach["art"], ids)

    def test_every_read_tier_has_art(self):
        ids = self._award_ids()
        for art, _ in data.READ_TIER_ART.values():
            with self.subTest(art=art):
                self.assertIn(art, ids)

    def test_award_sprite_has_no_orphan_symbols(self):
        """Символ, на который никто не ссылается, — мёртвый вес на странице."""
        used = {a[0] for a in data.READ_TIER_ART.values()}
        for author in data.all_authors():
            used |= {x["art"] for x in data.achievements_of(author)}
        self.assertEqual(self._award_ids() - used, set())

    def test_template_icon_literals_exist(self):
        import re
        ids = self._sprite_ids()
        for path in _templates():
            body = path.read_text(encoding="utf-8")
            for name in re.findall(r'icon\.html" with name="([a-z0-9-]+)"', body):
                with self.subTest(template=path.name, icon=name):
                    self.assertIn(name, ids)


class MoneyFormatting(TestCase):
    """`stringformat:"d"` печатал «500000» сплошняком — всюду фильтр `spaced`."""

    def test_prize_is_spaced_on_every_surface(self):
        for url in ('/', '/contests/', '/contests/bolashak-mektebi/'):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                if '₸' in html:
                    self.assertNotIn('500000', html)

    def test_no_template_still_uses_raw_stringformat_for_money(self):
        for path in TEMPLATES_DIR.rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(template=path.name):
                self.assertNotIn('prize_kzt|stringformat:"d"', text)


class PlatformDoesNotNameItsAudience(TestCase):
    """Продукт не объявляет, для кого он.

    Аудитория — внутренняя информация: платформой пользуются и школьники,
    и студенты колледжей и вузов. Пока возрастной ценз был правилом
    платформы, «14-18» стояло в подсказке поля на
    регистрации и в редактировании профиля — то есть каждый, кто доходил
    до формы, читал, что здесь для 14-18 лет, ещё не увидев ни одного
    конкурса.

    **Возрастная вилка законна ровно в одном месте — на странице
    конкретного конкурса**, где это его собственное условие.
    Поэтому маршруты конкурсов из проверки исключены, а все остальные
    обязаны молчать.

    Проверка идёт и по отрендеренному HTML, и по исходникам шаблонов:
    первое ловит текст, попавший на экран, второе — вилку, вписанную
    литералом вместо `domain.contests.eligibility_line`.
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
        from core.tests.test_smoke import PUBLIC_URLS
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
                    f'не платформа')

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
                    f'литералом — она должна приходить из '
                    f'`domain.contests.eligibility_line`')


class LegalPagesSpeakToPeople(TestCase):
    """Страница правил — текст для подростка, а не выписка из требований.

    В ней было семь внутренних кодов требований и отсылка в
    `docs/spec.md` — то есть читателя правил отправляли в исходники.
    Плюс три незакрытых плейсхолдера, один из них ровно там, где
    человеку объясняют, как забрать свои данные.

    Глазами это не ловится: страницы длинные, по-казахски, и открывают их
    редко. Поэтому числом.
    """

    # Коды требований и ссылки в репозиторий. `DEC-` тоже: решение —
    # внутренняя бухгалтерия проекта.
    _INTERNAL = re.compile(r'\b(?:FR|BR|NFR|DEC)-[A-Z0-9]|docs/|\.md\b')
    # Незакрытая заготовка. Квадратная скобка в живом тексте не нужна
    # вовсе, а как признак «здесь ещё не дописано» — надёжна.
    _PLACEHOLDER = re.compile(r'\[[^\]]*\]')

    _PAGES = ('legal_moderation', 'legal_publishing', 'legal_about',
              'legal_terms', 'legal_privacy')

    def test_no_internal_codes_and_no_placeholders_reach_the_reader(self):
        for name in self._PAGES:
            with self.subTest(page=name):
                body = self.client.get(
                    reverse(f'core:{name}')).content.decode()
                # Сперва выбрасываем `<style>`/`<script>` целиком, вместе
                # с содержимым: в инлайн-стиле `base.html` живёт селектор
                # `[x-cloak]`, и он ловится как незакрытая заготовка.
                # Потом уже теги — иначе классы вроде `xl:hidden` тоже
                # считались бы текстом страницы.
                text = re.sub(r'<(script|style)\b.*?</\1>', ' ', body,
                              flags=re.S)
                text = re.sub(r'<[^>]+>', ' ', text)

                self.assertIsNone(self._INTERNAL.search(text),
                                  'внутренний код в тексте для читателя')
                self.assertIsNone(self._PLACEHOLDER.search(text),
                                  'незакрытая заготовка в тексте')

    def test_the_reader_is_told_where_to_write(self):
        """Правила, не называющие канал связи, отвечают на «что делать,
        если» словами «никуда»."""
        for name in ('legal_moderation', 'legal_about', 'legal_privacy'):
            with self.subTest(page=name):
                body = self.client.get(reverse(f'core:{name}')).content.decode()
                self.assertTrue('@qazaqnovel' in body or '@' in body,
                                'на странице нет ни одного канала связи')


class RequirementCodesDoNotComeBack(unittest.TestCase):
    """Код требования в коде — ссылка в никуда.

    Их было 1246 в 185 файлах: `DEC-31`, `BR-79`, `FR-PROF-08` и ещё
    390 уникальных. Ни один не определён нигде — реестр решений и
    нумерованные модули документации удалены ещё при слиянии `docs/` в
    три файла. То есть комментарий отсылал к документу, которого нет уже
    несколько итераций, и это хуже, чем отсутствие ссылки: по ней идут
    искать.

    Ровно это правило уже применили один раз — к правовым страницам
    (`LegalPagesSpeakToPeople` выше), и довод там был тот же: пометка
    правила должна жить там, где правило объяснено словами.

    Проверка стоит здесь, а не в ревью, потому что коды возвращаются
    по памяти: они короткие, привычные и выглядят как знание о проекте.
    """

    _CODE = re.compile(r'\b(?:DEC|BR|FR|NFR)-[A-Z]*-?\d')
    _SUFFIXES = ('.py', '.html', '.js', '.css')

    def test_no_file_mentions_a_requirement_code(self):
        # Сам этот файл — единственное исключение: образец кода в нём
        # живёт по делу.
        myself = Path(__file__).resolve()
        roots = (TEMPLATES_DIR, STATIC_SRC_DIR, myself.parent.parent)

        offenders = []
        for root in roots:
            for path in root.rglob('*'):
                if (path.suffix not in self._SUFFIXES
                        or '__pycache__' in path.parts
                        or path.resolve() == myself):
                    continue
                for number, line in enumerate(
                        path.read_text(encoding='utf-8').splitlines(), 1):
                    if self._CODE.search(line):
                        offenders.append(
                            f'{path.name}:{number}: {line.strip()[:70]}')

        self.assertEqual(offenders, [],
                         'коды требований ведут в никуда — реестра, на который '
                         'они ссылались, в docs/ больше нет:\n'
                         + '\n'.join(offenders[:20]))

    # Только то, что выглядит ссылкой: путь со слэшем или имя плана
    # прописными. Иначе под правило попадает имя файла выгрузки, которое
    # тест собирает сам.
    _DOC = re.compile(r'\b(?:[\w.-]+/[\w./-]+\.md|[A-Z][A-Z-]+\.md)\b')

    def test_no_file_points_at_a_document_that_is_gone(self):
        """Та же беда крупнее: ссылка на удалённый файл плана.

        `AUDIT-WRITE-FLOW.md` упоминался 45 раз спустя долгое время
        после того, как был удалён; закрытые планы удаляются регулярно,
        а ссылки на них остаются в комментариях.
        """
        myself = Path(__file__).resolve()
        offenders = []
        for root in (TEMPLATES_DIR, STATIC_SRC_DIR, myself.parent.parent):
            for path in root.rglob('*'):
                if (path.suffix not in self._SUFFIXES
                        or '__pycache__' in path.parts
                        or path.resolve() == myself):
                    continue
                text = path.read_text(encoding='utf-8')
                for number, line in enumerate(text.splitlines(), 1):
                    for name in self._DOC.findall(line):
                        # Путь бывает и относительным — из шаблона в
                        # `docs/` через `../..`.
                        bases = (_ROOT, path.parent, _ROOT / 'docs')
                        if any((base / name).resolve().exists() for base in bases):
                            continue
                        offenders.append(f'{path.name}:{number}: {name}')

        self.assertEqual(offenders, [],
                         'ссылка на документ, которого нет:\n'
                         + '\n'.join(offenders[:20]))


class NoLinkLeadsNowhere(unittest.TestCase):
    """Ссылка `href="#"` — обещание, за которым ничего нет.

    Такими были четыре иконки соцсетей в подвале каждой страницы и те же
    четыре на странице после регистрации под словами «Сұрағың бар ма?
    Жаз:» — с `target="_blank"` они открывали новую вкладку с той же
    страницей. Адреса каналов живут в `core/domain/contacts.py`, и канал
    без адреса не рисуется."""

    LINK = re.compile(r'<a\b[^>]*\bhref="#"', re.S)

    def test_no_anchor_points_at_an_empty_fragment(self):
        for path in _templates():
            with self.subTest(template=path.name):
                self.assertIsNone(self.LINK.search(path.read_text(encoding='utf-8')))
