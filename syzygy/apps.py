from django.apps import AppConfig
from django.core import checks

from .checks import check_migrations


class SyzygyConfig(AppConfig):
    name = __package__

    def ready(self):
        checks.register(check_migrations, "migrations")
