from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        from . import counters  # noqa: F401 — регистрирует сигналы счётчиков
