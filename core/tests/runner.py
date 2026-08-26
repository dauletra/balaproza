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

Цена решения одна: тест, которому нужна пустая таблица, её больше не
получит. Это честно — пустой базы у портала не бывает и в бою, а
проверять пустые состояния интерфейса надо на пользователе без данных,
а не на пустой вселенной.
"""

import os

from django.core.management import call_command
from django.test.runner import DiscoverRunner
from django.test.utils import setup_databases

DEFAULT_PARALLEL = 4


class SeededTestRunner(DiscoverRunner):

    def __init__(self, *args, parallel=0, **kwargs):
        if not parallel:
            parallel = min(DEFAULT_PARALLEL, os.cpu_count() or 1)
        super().__init__(*args, parallel=parallel, **kwargs)

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
            call_command('seed_demo', quiet=True)
        finally:
            connection.close()
            connection.settings_dict['NAME'] = name
