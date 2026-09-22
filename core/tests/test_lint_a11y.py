"""Доступность разметки: то, чего не видно, пока не попробуешь.

Проверки здесь ловят один и тот же род ошибки — **роль объявлена, а
поведения роли нет**. `aria-modal` без ловушки фокуса: `Tab` уводит в
страницу позади, ту самую, которую диалог перекрывает. `role="tab"` без
панели: скринридер обещает содержимое, которого нет. `aria-label` на
`<span>` без роли не озвучивается вовсе, а на кнопке рядом с текстом —
озвучивается дважды.

Отдельно — движение и размер: `prefers-reduced-motion` для того, кому
анимация не украшение, и нижняя граница кнопки для пальца.
"""


import unittest
from html.parser import HTMLParser

from django.urls import reverse

from core import data
from core.tests.base import TestCase, login_as
# Пути объявлены в `test_lint`, а не здесь: «где лежат шаблоны» не
# должно быть записано в трёх файлах.
from core.tests.test_lint import (
    STATIC_DIR,
    STATIC_SRC_DIR,
    TEMPLATES_DIR,
    _templates,
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
        from core.tests.test_smoke import PUBLIC_URLS

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
        from core.tests.test_smoke import PUBLIC_URLS

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
        from core.tests.test_smoke import PUBLIC_URLS

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


class EveryDialogManagesItsFocus(unittest.TestCase):
    """Роли и `aria-modal` у диалогов стояли с первого дня, Escape
    закрывал — а фокус оставался за диалогом. Для того, кто ходит с
    клавиатуры, это и есть разница между «диалог открылся» и «ничего не
    произошло»: читается страница позади, Tab уводит в неё же, а после
    закрытия непонятно, где ты.

    Требования обещали focus-trap с самого начала. Здесь проверяется, что
    обещание не разошлось с кодом снова: диалог обязан пользоваться общим
    механизмом, а не заводить свой пятый обработчик Tab.
    """

    #: Компоненты, которым позволено объявлять `aria-modal`.
    TRAPPED = ('modal(', 'searchPopup(')

    def test_no_dialog_without_a_component_that_traps_focus(self):
        for path in _templates():
            markup = path.read_text(encoding='utf-8')
            if 'aria-modal' not in markup:
                continue
            with self.subTest(template=path.name):
                self.assertTrue(
                    any(name in markup for name in self.TRAPPED),
                    'диалог не пользуется компонентом с ловушкой фокуса')

    def test_the_trap_lives_in_one_place(self):
        source = (STATIC_DIR / 'js' / 'components.js').read_text(encoding='utf-8')

        self.assertIn('function withFocusTrap(', source)
        # Ровно один обработчик Tab на весь портал: пять копий разошлись
        # бы в первой же правке.
        self.assertEqual(source.count("event.key === 'Tab'"), 1)

    def test_both_dialog_components_use_it(self):
        source = (STATIC_DIR / 'js' / 'components.js').read_text(encoding='utf-8')

        self.assertEqual(source.count('withFocusTrap({'), 2)
        self.assertEqual(source.count('this.watchFocus();'), 2)


class TheKeyboardMaySkipTheHeader(unittest.TestCase):
    """Шапка — логотип, поиск, четыре раздела, колокольчик и меню — шла
    заново на каждой странице, прежде чем человек с клавиатуры добирался
    до текста. Обход навигации стоит одной ссылки и в требованиях
    доступности стоит первым пунктом."""

    def test_the_skip_link_is_first_and_leads_to_the_content(self):
        markup = (TEMPLATES_DIR / 'base.html').read_text(encoding='utf-8')
        body = markup.index('<body')

        self.assertLess(markup.index('href="#main"'), markup.index('<header')
                        if '<header' in markup else len(markup))
        self.assertLess(body, markup.index('href="#main"'))
        self.assertIn('id="main"', markup)

    def test_it_is_hidden_until_focused(self):
        """Видимая всегда, она заняла бы место у первого экрана ради
        того, чем пользуются с клавиатуры."""
        markup = (TEMPLATES_DIR / 'base.html').read_text(encoding='utf-8')
        link = markup[markup.index('href="#main"'):]

        self.assertIn('sr-only', link[:400])
        self.assertIn('focus:not-sr-only', link[:400])

    def test_the_target_can_take_focus(self):
        """Без `tabindex` переход по якорю прокручивает страницу, но
        фокус оставляет на ссылке — следующий Tab возвращает в шапку."""
        markup = (TEMPLATES_DIR / 'base.html').read_text(encoding='utf-8')

        self.assertIn('id="main" tabindex="-1"', markup)


class MovementIsOptional(unittest.TestCase):
    """Скелетоны пульсируют, карточки на ховере приподнимаются, модалки и
    тосты въезжают переходами. Для человека с вестибулярными нарушениями
    это причина закрыть вкладку, и выключить это было нечем: в стилях не
    было ни одного упоминания системной настройки.

    Проверяется источник, а не собранный `output.css`: тот пересобирается
    командой, которую запускает человек, и в репозитории его нет.
    """

    def setUp(self):
        self.css = (STATIC_SRC_DIR / 'input.css').read_text(encoding='utf-8')

    def test_the_system_setting_is_honoured(self):
        self.assertIn('@media (prefers-reduced-motion: reduce)', self.css)

    def test_it_shortens_motion_instead_of_forbidding_it(self):
        """`animation: none` оставил бы `x-transition` без события
        `transitionend`, на котором Alpine снимает `display`, — и модалка
        осталась бы полупрозрачной навсегда. Поэтому длительность
        сводится к мгновенной, а не к нулю."""
        block = self.css[self.css.index('@media (prefers-reduced-motion'):]

        self.assertIn('animation-duration: 0.01ms', block)
        self.assertIn('transition-duration: 0.01ms', block)
        self.assertNotIn('animation: none', block)
