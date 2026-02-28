from django.core.management.commands import makemigrations
from django.db.migrations.writer import MigrationWriter

from syzygy.autodetector import MigrationAutodetector


class AtomicAwareMigrationWriter(MigrationWriter):
    def as_string(self):
        result = super().as_string()
        if getattr(self.migration, "atomic", True) is False:
            result = result.replace(
                "class Migration(migrations.Migration):\n",
                "class Migration(migrations.Migration):\n\n    atomic = False\n",
                1,
            )
        return result


class Command(makemigrations.Command):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--disable-syzygy",
            action="store_true",
            help=(
                "Disable syzygy operation injection and stage splitting. "
                "Please report issues requiring usage of this flag upstream."
            ),
        )

    def handle(self, *args, disable_syzygy, **options):
        if disable_syzygy:
            return super().handle(*args, **options)
        # Monkey-patch makemigrations since the command doesn't allow
        # MigrationAutodetector or MigrationWriter to be overridden
        # in any other way.
        MigrationAutodetector_ = makemigrations.MigrationAutodetector
        MigrationWriter_ = makemigrations.MigrationWriter
        style = self.style

        class StyledMigrationAutodetector(MigrationAutodetector):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs, style=style)

        if hasattr(self, "autodetector"):
            self.autodetector = StyledMigrationAutodetector
        else:
            makemigrations.MigrationAutodetector = StyledMigrationAutodetector
        makemigrations.MigrationWriter = AtomicAwareMigrationWriter
        try:
            super().handle(*args, **options)
        finally:
            if not hasattr(self, "autodetector"):
                makemigrations.MigrationAutodetector = MigrationAutodetector_
            makemigrations.MigrationWriter = MigrationWriter_
