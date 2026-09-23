from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'
    # Заголовок раздела в админке: «Core» редактору ничего не говорит.
    verbose_name = 'Портал'

    def ready(self):
        from . import counters  # noqa: F401 — регистрирует сигналы счётчиков
        from . import media_cleanup  # noqa: F401 — регистрирует сигналы файлов
