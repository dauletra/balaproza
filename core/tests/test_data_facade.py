"""Шов Ф14: одна дверь к данным и домен, не знающий о хранилище.

Замена стаба на модели держится на двух правилах, которых не видно в
самом коде — их видно только в том, чего в коде нет. Правило, живущее
исключительно в тексте, не соблюдается: `stub_data` расползся по views
ровно так же, как раньше расползались хардкоженные URL каталога.

1. Читающая сторона обращается к `core.data`, а не к `core.stub_data`.
   Иначе каждый этап миграции переписывает `views.py` заново.
2. `core.domain` не знает ни про стаб, ни про модели. Иначе на Ф14
   получится цикл импортов, а константы нельзя будет использовать в
   миграциях и админке.
"""

import ast
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent

# Кому можно знать про `stub_data`: самому стабу, фасаду и тестам. Тесты —
# потому что стаб-корпус пока и есть предмет проверки; на этапе сида это
# место займёт seed-команда.
STUB_IMPORTERS_ALLOWED = {'stub_data.py', 'data.py'}


def _sources():
    """Все модули приложения, кроме тестов и миграций."""
    for path in sorted(CORE.rglob('*.py')):
        parts = path.relative_to(CORE).parts
        if parts[0] in {'tests', 'migrations'} or path.name == '__pycache__':
            continue
        yield path


def _toplevel_names(path):
    """Имена, определённые в модуле на верхнем уровне (без импортов)."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names += [t.id for t in node.targets if isinstance(t, ast.Name)]
    return [n for n in names if not n.startswith('_')]


class OnlyTheFacadeTouchesTheStub(unittest.TestCase):

    def test_no_module_imports_stub_data_directly(self):
        offenders = []
        for path in _sources():
            if path.name in STUB_IMPORTERS_ALLOWED:
                continue
            text = path.read_text(encoding='utf-8')
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith('#'):
                    continue
                if 'stub_data' in stripped and ('import' in stripped):
                    offenders.append(f'{path.relative_to(CORE)}: {stripped}')
        self.assertEqual(
            [], offenders,
            'Импорт `stub_data` мимо фасада `core.data`:\n  ' + '\n  '.join(offenders)
            + '\n\nЧитающая сторона обязана ходить через `core.data` — иначе '
              'каждый этап Ф14 переписывает вызовы заново.',
        )


class DomainKnowsNothingAboutStorage(unittest.TestCase):

    def test_domain_imports_neither_stub_nor_models_nor_facade(self):
        forbidden = ('stub_data', 'core.data', 'from .data', 'models')
        offenders = []
        for path in sorted((CORE / 'domain').glob('*.py')):
            for line in path.read_text(encoding='utf-8').splitlines():
                stripped = line.strip()
                if not stripped.startswith(('import ', 'from ')):
                    continue
                if any(f in stripped for f in forbidden):
                    offenders.append(f'{path.name}: {stripped}')
        self.assertEqual(
            [], offenders,
            'core/domain знает о хранилище:\n  ' + '\n  '.join(offenders)
            + '\n\nДомен — это правила, а не записи. Импорт хранилища сюда '
              'закрывает дорогу к использованию констант в миграциях и админке.',
        )

    def test_every_domain_name_is_reachable_through_the_facade(self):
        from core import data

        missing = []
        for path in sorted((CORE / 'domain').glob('*.py')):
            if path.name == '__init__.py':
                continue
            for name in _toplevel_names(path):
                if not hasattr(data, name):
                    missing.append(f'{path.name}: {name}')
        self.assertEqual(
            [], missing,
            'Домен определяет то, чего нет в фасаде:\n  ' + '\n  '.join(missing)
            + '\n\nДверь одна: если правило нельзя достать через `core.data`, '
              'его достанут через прямой импорт, и шва снова не станет.',
        )
