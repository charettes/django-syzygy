from django.core.management.commands import makemigrations  # type: ignore

from syzygy.autodetector import MigrationAutodetector


class Command(makemigrations.Command):
    def handle(self, *args, **options):
        # Monkey-patch makemigrations.MigrationAutodetector since the command
        # doesn't allow it to be overridden in any other way.
        MigrationAutodetector_ = makemigrations.MigrationAutodetector
        makemigrations.MigrationAutodetector = MigrationAutodetector
        try:
            super().handle(*args, **options)
        finally:
            makemigrations.MigrationAutodetector = MigrationAutodetector_
