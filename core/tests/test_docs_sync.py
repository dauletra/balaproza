"""Страж синхронизации ТЗ с кодом (docs/15 §15.4).

Документацию нельзя проверить на правдивость целиком, но можно проверить
её проверяемую часть: имена файлов, токенов, хелперов и счётчики. Ровно на
этих вещах ТЗ и разъехалось с кодом — три месяца оно описывало токены
«--teal», компонент `CatalogControls` и хелперы с сигнатурами, которых нет.

Тесты здесь того же рода, что `test_template_lint`: они не проверяют
требование, а держат исполняемым правило, которое иначе живёт только
в тексте и потому не соблюдается.

Что НЕ проверяется и проверено быть не может: соответствие описания
поведению. Если FR говорит «кнопка синяя», а она бирюзовая — это ловится
только глазами.
"""

import re
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
DOCS = BASE / 'docs'
TEMPLATES = BASE / 'templates'


def _docs():
    """Все .md в docs/, кроме README (он про структуру, а не про код)."""
    return sorted(p for p in DOCS.glob('*.md'))


def _text(p):
    return p.read_text(encoding='utf-8')


def _code_spans(text):
    """Содержимое всех `…` в тексте."""
    return re.findall(r'`([^`\n]+)`', text)


class TestCounters(unittest.TestCase):
    """Счётчики в README.md, CLAUDE.md и AGENTS.md — цифры, которые устаревают тише всего.

    Они устарели дважды: «315 тестов в 12 файлах» при фактических 397 в 15,
    и «~55 компонентов» при 50.

    `AGENTS.md` — дословная копия `CLAUDE.md` для другого агента, и как
    ручная копия он и отстал: девять DEC и «315 тестов в 12 файлах» при
    фактических 729 в 16. Проверка одна на оба файла ровно потому, что
    расходятся они молча.
    """

    MIRRORS = ('CLAUDE.md', 'AGENTS.md')

    def _actual_tests(self):
        files = sorted((BASE / 'core' / 'tests').glob('test_*.py'))
        total = sum(len(re.findall(r'\n\s+def test_', _text(f))) for f in files)
        return total, len(files)

    def test_test_counts_match_readme_and_claude_md(self):
        total, files = self._actual_tests()
        for name in ('README.md',) + self.MIRRORS:
            body = _text(BASE / name)
            claimed = re.findall(r'(\d+)\s+тест\w*\s+в\s+(\d+)\s+файл', body)
            claimed += [(m[0], m[1]) for m in re.findall(r'все\s+(\d+)\s+тест\w*()', body)]
            self.assertTrue(
                claimed,
                f'{name}: не нашёл упоминания количества тестов — '
                f'формат ожидается «N тестов в M файлах» или «все N тестов»',
            )
            for n, m in claimed:
                self.assertEqual(
                    int(n), total,
                    f'{name}: заявлено {n} тестов, фактически {total}. '
                    f'Обнови счётчик.',
                )
                if m:
                    self.assertEqual(
                        int(m), files,
                        f'{name}: заявлено {m} тест-файлов, фактически {files}.',
                    )

    def test_component_count_matches_claude_md(self):
        actual = len(list((TEMPLATES / 'components').glob('*.html')))
        for name in self.MIRRORS:
            body = _text(BASE / name)
            claimed = re.search(r'(\d+)\s+атом\w*\s+и\s+composites', body)
            self.assertIsNotNone(
                claimed, f'{name}: не нашёл счётчик компонентов «N атомов и composites»')
            self.assertEqual(
                int(claimed.group(1)), actual,
                f'{name}: заявлено {claimed.group(1)} компонентов, фактически {actual}.',
            )

    def test_agents_md_still_mirrors_claude_md(self):
        """Две редакции одного текста расходятся молча — здесь они сверяются.

        Отличаться разрешено ровно шапке: заголовок, имя агента и абзац
        о том, что файл — копия. Всё, что ниже «## Текущий фокус», обязано
        совпадать символ в символ.
        """
        marker = '## Текущий фокус'
        bodies = []
        for name in self.MIRRORS:
            text = _text(BASE / name)
            self.assertIn(marker, text, f'{name}: не нашёл «{marker}»')
            bodies.append(text[text.index(marker):])
        self.assertEqual(
            bodies[0], bodies[1],
            'CLAUDE.md и AGENTS.md разошлись ниже шапки. Правишь один — '
            'переписывай второй тем же коммитом: правила у агентов общие, '
            'а прошлая копия отстала на девять DEC незамеченной.',
        )


class TestReferencedPathsExist(unittest.TestCase):
    """Любой путь к файлу, упомянутый в ТЗ, должен существовать.

    Это ловит ссылки на удалённые файлы (`catalog_controls.html`,
    `sidebar.html`, `search_results.html`) и опечатки в именах партиалов.
    Пути к шаблонам в ТЗ пишутся относительно templates/, поэтому
    проверяем оба варианта.
    """

    EXT = ('.html', '.py', '.css', '.json', '.txt', '.toml')

    # Пути-примеры, которых нет и не должно быть на диске.
    ALLOWED_MISSING = {
        'core/story_texts/<story-slug>/<chapter-number>.txt',
        'static/css/output.css',          # gitignored, появляется после npm run build
        'static/css/output.css.map',
        'local_settings.py',
    }

    def test_every_referenced_file_exists(self):
        missing = []
        for doc in _docs():
            for span in _code_spans(_text(doc)):
                span = span.strip()
                if '/' not in span or not span.endswith(self.EXT):
                    continue
                if span.startswith('/'):
                    continue  # URL маршрута, а не путь к файлу
                if span in self.ALLOWED_MISSING or '<' in span or '*' in span:
                    continue
                if (BASE / span).exists() or (TEMPLATES / span).exists():
                    continue
                missing.append(f'{doc.name}: {span}')
        self.assertEqual(
            [], missing,
            'ТЗ ссылается на несуществующие файлы:\n  ' + '\n  '.join(missing),
        )


class TestDesignTokens(unittest.TestCase):
    """Каждый токен, названный в ТЗ, объявлен в @theme.

    Именно эта проверка поймала бы главное расхождение дизайн-системы:
    docs/02 три месяца описывал «--teal», «--slate-900» и «--promo-bg»,
    тогда как Tailwind v4 требует префикс `--color-` и в input.css лежали
    `--color-brand`, `--color-slate-900`, `--color-promo-bg`.
    """

    # Проверяются ВСЕ `--*` в код-спанах, а не только те, что уже несут верный
    # префикс. Иначе проверка пропускала бы ровно тот случай, ради которого
    # написана: `--teal` не начинается с `--color-` и молча прошёл бы мимо.
    #
    # Флаги CLI выглядят так же, поэтому перечислены явно. Список короткий и
    # растёт медленно; пропускать всё «похожее на флаг» по маске нельзя —
    # в такую маску провалится и опечатка в имени токена.
    CLI_FLAGS = {
        '--minify', '--watch', '--deploy', '--noinput',
        '--no-dev', '--group', '--no-verify', '--stat',
    }

    def test_tokens_named_in_docs_exist_in_input_css(self):
        css = _text(BASE / 'static_src' / 'input.css')
        declared = set(re.findall(r'(--[a-z0-9-]+)\s*:', css))
        unknown = []
        for doc in _docs():
            for span in _code_spans(_text(doc)):
                for token in re.findall(r'--[a-z0-9-]+', span):
                    if token.endswith('-'):
                        continue  # назван как префикс («--color-*»), а не как токен
                    if token in self.CLI_FLAGS or token in declared:
                        continue
                    unknown.append(f'{doc.name}: {token}')
        self.assertEqual(
            [], sorted(set(unknown)),
            'ТЗ называет CSS-переменные, которых нет в static_src/input.css:\n  '
            + '\n  '.join(sorted(set(unknown)))
            + '\n(флаг CLI — добавь в CLI_FLAGS; устаревший токен, упомянутый '
              'как история, — пиши без обратных кавычек)',
        )


class TestStubDataContract(unittest.TestCase):
    """Хелперы, перечисленные в docs/12 §12.3, существуют в stub_data.

    Модуль 12 объявлен «implementation contract» для Ф14. Контракт,
    называющий несуществующие функции, хуже отсутствующего: по нему
    напишут вызовы, которых не с чем связывать.
    """

    def test_helpers_from_contract_exist(self):
        stub = _text(BASE / 'core' / 'stub_data.py')
        defined = set(re.findall(r'^def (\w+)', stub, re.M))
        contract = _text(DOCS / '12-domain-model-contract.md')
        section = contract.split('## 12.3')[1].split('## 12.4')[0]
        cited = set(re.findall(r'`(\w+)\(', section))
        missing = sorted(cited - defined)
        self.assertEqual(
            [], missing,
            'docs/12 §12.3 называет хелперы, которых нет в core/stub_data.py:\n  '
            + '\n  '.join(missing),
        )


class TestDecisionsAreDefined(unittest.TestCase):
    """Каждое решение DEC-NN, на которое ссылаются, определено в docs/10.

    Реестр решений — единственный источник; ссылка на несуществующий DEC
    означает либо опечатку, либо решение, принятое мимо реестра.
    """

    def test_every_cited_dec_is_in_the_registry(self):
        registry = _text(DOCS / '10-resolved-decisions.md')
        defined = set(re.findall(r'DEC-(\d+)\*{0,2}\s*\|', registry))
        defined |= set(re.findall(r'\*\*DEC-(\d+)\*\*', registry))

        cited = {}
        for doc in _docs() + [BASE / 'CLAUDE.md']:
            for num in re.findall(r'DEC-(\d+)', _text(doc)):
                cited.setdefault(num, set()).add(doc.name)

        unknown = sorted(
            f'DEC-{n} (упомянут в {", ".join(sorted(src))})'
            for n, src in cited.items() if n not in defined
        )
        self.assertEqual(
            [], unknown,
            'Ссылки на решения, которых нет в реестре docs/10:\n  '
            + '\n  '.join(unknown),
        )


class TestStatusLabels(unittest.TestCase):
    """Тексты статусов в ТЗ совпадают с components/status_badge.html.

    Расхождение было в трёх из пяти: ТЗ несло «Жарияланбаған», «Тексеруде»
    и «Жарияланған», а компонент рендерил «Жоба», «Модерацияда»
    и «Жарияланды» — смена тона (docs/16) до ТЗ не дошла.

    Статусы видит автор на каждом своём произведении, и собирать их
    вручную запрещено (BR-10), поэтому источник один — компонент.
    """

    # Тексты статусов держат ровно два модуля: 08 (BR-10 — статусная модель)
    # и 16 §16.3 (канонический словарь). 04 и 13 ссылаются на них, а не
    # повторяют — четыре копии одного списка и дали расхождение в трёх из пяти.
    DOCS_WITH_TABLE = ('08-business-rules.md', '16-content-voice.md')

    def test_labels_match_the_component(self):
        badge = _text(TEMPLATES / 'components' / 'status_badge.html')
        labels = re.findall(r'label="([^"]+)"', badge)
        self.assertEqual(
            5, len(labels),
            f'status_badge.html: ожидалось 5 статусов (BR-10), найдено {len(labels)}',
        )
        for name in self.DOCS_WITH_TABLE:
            body = _text(DOCS / name)
            for label in labels:
                self.assertIn(
                    label, body,
                    f'{name}: нет текста статуса «{label}» из status_badge.html. '
                    f'Канонический словарь — docs/16 §16.3.',
                )


class TestDocsAreStamped(unittest.TestCase):
    """У каждого модуля ТЗ есть шапка с датой и коммитом сверки.

    Без неё невозможно понять, что устарело, не читая git log — а именно
    так расхождения и накопились незамеченными.
    """

    def test_every_doc_has_a_version_stamp(self):
        unstamped = [
            p.name for p in _docs()
            if 'Сверен с кодом' not in '\n'.join(_text(p).split('\n')[:8])
        ]
        self.assertEqual(
            [], unstamped,
            'Модули ТЗ без шапки «Обновлён / Сверен с кодом»:\n  '
            + '\n  '.join(unstamped),
        )
