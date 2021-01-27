from django.apps import AppConfig
from django.core import checks
from django.core.signals import setting_changed

from .checks import check_migrations
from .conf import _configure, _watch_settings


class SyzygyConfig(AppConfig):
    name = __package__

    def ready(self):
        _configure()
        checks.register(check_migrations, "migrations")
        setting_changed.connect(_watch_settings)
