"""Шов Ф14: одна дверь к данным и домен, не знающий о хранилище.

Три правила, которых не видно в самом коде — их видно только в том, чего
в коде нет. Правило, живущее исключительно в тексте, не соблюдается:
`stub_data` в своё время расползся по views ровно так же, как раньше
расползались хардкоженные URL каталога.

1. Читающая сторона обращается к `core.data`. Дверь одна: иначе каждая
   замена хранилища переписывает `views.py` заново.
2. `core.domain` не знает ни про модели, ни про фасад. Иначе получается
   цикл импортов, а константы нельзя использовать в миграциях и админке.
3. Демо-корпус (`_corpus.py`) читают только сид и его тест. Стаб ушёл, но
   литералы никуда не делись, и правило то же: приложение отвечает из
   базы, а не из литералов рядом с ней.
"""

import ast
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent

# Кому можно знать про демо-корпус. Сид — потому что он и есть конвертер
# из литералов в таблицы; его тест — потому что перевод проверяют, сверяя
# обе стороны. Остальным нельзя: страница, читающая корпус, показывала бы
# не то, что лежит в базе, и расхождение увидел бы только пользователь.
CORPUS_READERS_ALLOWED = {'_corpus.py', 'seed_demo.py', 'test_seed.py',
                          # Сам сторож: правило в нём написано словами.
                          'test_data_facade.py'}


def _sources():
    """Все модули приложения, кроме миграций.

    Тесты входят: правило «корпус читает только сид» касается и их —
    тест, сверяющий страницу с литералом, сторожит копию того, что
    показывают, а не саму выдачу.
    """
    for path in sorted(CORE.rglob('*.py')):
        parts = path.relative_to(CORE).parts
        if parts[0] == 'migrations' or path.name == '__pycache__':
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


class OnlyTheSeedReadsTheCorpus(unittest.TestCase):

    def test_no_module_imports_the_corpus(self):
        offenders = []
        for path in _sources():
            if path.name in CORPUS_READERS_ALLOWED:
                continue
            for line in path.read_text(encoding='utf-8').splitlines():
                stripped = line.strip()
                if stripped.startswith('#'):
                    continue
                if '_corpus' in stripped and 'import' in stripped:
                    offenders.append(f'{path.relative_to(CORE)}: {stripped}')
        self.assertEqual(
            [], offenders,
            'Демо-корпус читают мимо сида:\n  ' + '\n  '.join(offenders)
            + '\n\nПортал отвечает из базы. Литералы — то, что в неё кладут, '
              'и второй читатель у них означает второй источник правды.',
        )

    def test_the_stub_is_gone(self):
        """Этап 11: сосуществования двух источников не бывает.

        Пока файл лежит рядом, к нему возвращаются — не в коде, так в
        тестах, и разойтись они успевают быстрее, чем это заметят.
        """
        self.assertFalse((CORE / 'stub_data.py').exists())


class DomainKnowsNothingAboutStorage(unittest.TestCase):

    def test_domain_imports_neither_stub_nor_models_nor_facade(self):
        forbidden = ('_corpus', 'core.data', 'from .data', 'models')
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
