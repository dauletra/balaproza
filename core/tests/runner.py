"""Тест-раннер: корпус в базе один раз на прогон, прогон — в несколько процессов.

Страницы читают базу, значит корпус нужен почти каждому тесту. Класть
его в `setUpTestData` было первым решением и стоило дорого: сид крутился
на каждом тест-классе, и суита выросла с двадцати семи секунд до трёх
минут. Три минуты на прогон — это уже не «запущу перед коммитом», а
«запущу когда-нибудь», то есть тесты, которые перестают ловить.

Здесь сид выполняется сразу после создания тестовой базы. Дальше
работает обычный механизм `TestCase`: каждый тест идёт в транзакции и
откатывается к состоянию сразу после сида, поэтому корпус виден всем и
не переносит между тестами ничьих изменений.

**Порядок с `--parallel` важен и потому здесь свой.** Django создаёт базу
и тут же клонирует её по числу процессов — всё внутри одного вызова. Сид,
выполненный после него, попал бы в исходную базу, а работали бы тесты в
пустых клонах. Поэтому база создаётся без клонов, засевается, и только
потом снимаются копии: клон делается `CREATE DATABASE ... TEMPLATE`, то
есть корпус приезжает в каждый процесс готовым, а не сеется четыре раза.

**Сколько процессов.** Сами тесты на восьми процессах идут вчетверо
быстрее, чем на одном (105 с → 25 с), но каждый клон базы на Windows
стоит около восьми секунд, и на восьми процессах выигрыш съедается
созданием копий. Четыре — точка, где общее время минимально. `--parallel 1`
возвращает последовательный прогон: он нужен для `--pdb` и тогда, когда
падение надо читать, а не разбирать по процессам.

**`--keepdb` — быстрый круг.** Базы не пересоздаются, и прогон занимает
секунды вместо минуты. Клоны при этом остаются с прошлым содержимым, и
поэтому сид проходит по каждому из них: он идемпотентен и возвращает
изменённое к эталону, так что правка корпуса или моделей доезжает и до
рабочих копий. Без этого `--keepdb` показывал бы вчерашние данные и
отвечал бы не на тот вопрос, который ему задали.

Перед сидом клон **мигрирует**: головную базу `--keepdb` догоняет сам
Django, клоны — никто, и новая колонка роняла быстрый круг ошибками
«столбец не существует» на каждом тесте, который её читает, — при
зелёном полном прогоне.

Цена решения одна: тест, которому нужна пустая таблица, её больше не
получит. Это честно — пустой базы у портала не бывает и в бою, а
проверять пустые состояния интерфейса надо на пользователе без данных,
а не на пустой вселенной.
"""

import os
import shutil
import tempfile

from django.core.management import call_command
from django.test.runner import DiscoverRunner, ParallelTestSuite, _init_worker
from django.test.utils import override_settings, setup_databases

DEFAULT_PARALLEL = 4

# Через окружение, потому что через память нельзя: на Windows и macOS
# процессы прогона не наследуют состояние головного, а создаются заново
# (`spawn`). Переменные окружения они при этом получают — это
# единственный канал, по которому путь доезжает до работника.
MEDIA_ROOT_ENV = 'QAZAQNOVEL_TEST_MEDIA_ROOT'


def _init_worker_with_media(counter, *args, **kwargs):
    """Инициализация процесса прогона: как у Django, плюс временная `media/`.

    Django поднимает работника с нуля — `django.setup()`,
    `setup_test_environment()`, своя копия базы, — и подмены настроек,
    включённые в головном процессе, до него не доезжают. То есть тест,
    сохраняющий обложку, писал её в **настоящую** `media/` разработчика,
    хотя раннер подменил путь: подмена осталась в том процессе, который
    тестов не выполняет.

    Видно это было только числом: прогон оставлял два файла в
    `media/covers/`, и `--parallel 1` не оставлял ни одного.
    """
    _init_worker(counter, *args, **kwargs)
    root = os.environ.get(MEDIA_ROOT_ENV)
    if root:
        # Без `disable()`: процесс работника живёт ровно прогон, и снимать
        # подмену с него некому и незачем.
        override_settings(MEDIA_ROOT=root).enable()


class _SeededParallelSuite(ParallelTestSuite):
    init_worker = _init_worker_with_media


class SeededTestRunner(DiscoverRunner):

    parallel_test_suite = _SeededParallelSuite

    def __init__(self, *args, parallel=0, **kwargs):
        if not parallel:
            parallel = min(DEFAULT_PARALLEL, os.cpu_count() or 1)
        super().__init__(*args, parallel=parallel, **kwargs)

    # ── `media/` на время прогона — временная папка ──────────────────────
    #
    # Сид ниже пишет в `MEDIA_ROOT`, и без подмены это **настоящая**
    # `media/` разработчика. Цена обнаружилась числом: 2453 файла-сироты
    # в `media/awards/` — по одному на каждый прошлый прогон. Механика
    # такая: `seed_demo` сохраняет `ContestAward`, сигнал замены растра
    # (`media_cleanup`) считает файл изменившимся, пишет новый рядом (у
    # Django имя занято — добавляется суффикс) и удаляет прежний. Строка
    # в базе после этого указывает на новое имя, а руками скопированный
    # файл, про который написано в README, исчезает.
    #
    # Отсюда же бралась плавающая суита: тест, проверяющий существование
    # эмблемы, падал или нет в зависимости от того, прошёл ли сид до него
    # — то есть от порядка тестов. Прогон, который зависит от порядка,
    # непрерывной интеграции не годится.
    #
    # Подмена ставится здесь, а не в отдельных тестах: сид идёт в
    # головном процессе (см. `setup_databases`), и покрыть надо именно
    # его. Тем двум классам, что грузят файлы сами, свои временные папки
    # оставлены — они от этого не зависят.
    #
    # Головным процессом дело не кончается: сами тесты идут в других, и
    # до них подмена доезжает через `MEDIA_ROOT_ENV` и
    # `_init_worker_with_media` — см. их выше. Папка одна на прогон и
    # удаляется здесь же, поэтому работникам её убирать не надо.
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._media_root = tempfile.mkdtemp(prefix='qnovel-test-media-')
        os.environ[MEDIA_ROOT_ENV] = self._media_root
        self._media = override_settings(MEDIA_ROOT=self._media_root)
        self._media.enable()

    def teardown_test_environment(self, **kwargs):
        self._media.disable()
        os.environ.pop(MEDIA_ROOT_ENV, None)
        shutil.rmtree(self._media_root, ignore_errors=True)
        super().teardown_test_environment(**kwargs)

    def setup_databases(self, **kwargs):
        config = setup_databases(
            self.verbosity,
            self.interactive,
            time_keeper=self.time_keeper,
            keepdb=self.keepdb,
            debug_sql=self.debug_sql,
            parallel=0,          # клонировать будем сами — после сида
            **kwargs,
        )
        # Пустой `config` — тестовой базы не создали. Django создаёт её
        # только если тесты её просят (`get_databases(suite)`), а модули из
        # чистого `unittest.TestCase` — фильтры, лint шаблонов — не просят.
        # Безусловный сид в этом случае уходил не в тестовую базу, а в ту,
        # что стоит в `DATABASE_URL`, то есть в базу разработки.
        if not config:
            return config

        call_command('seed_demo', quiet=True)

        for connection, _, _ in config:
            # Postgres не даёт снять шаблон с базы, к которой кто-то
            # подключён, — а сид только что оттуда вышел не закрыв.
            connection.close()
            for index in range(1, self.parallel + 1):
                connection.creation.clone_test_db(
                    suffix=str(index),
                    verbosity=self.verbosity,
                    keepdb=self.keepdb,
                )
                if self.keepdb:
                    self._reseed_clone(connection, index)
        return config

    def _reseed_clone(self, connection, index):
        """Догнать переиспользованный клон до эталона.

        Только при `--keepdb`: свежий клон снят с уже засеянной базы и в
        этом не нуждается.
        """
        name = connection.settings_dict['NAME']
        connection.close()
        connection.settings_dict['NAME'] = (
            connection.creation.get_test_db_clone_settings(str(index))['NAME'])
        try:
            call_command('migrate', verbosity=0, interactive=False)
            call_command('seed_demo', quiet=True)
        finally:
            connection.close()
            connection.settings_dict['NAME'] = name
