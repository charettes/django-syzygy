from django.core.management.commands import makemigrations

from syzygy.autodetector import MigrationAutodetector


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
        # Monkey-patch makemigrations.MigrationAutodetector since the command
        # doesn't allow it to be overridden in any other way.
        MigrationAutodetector_ = makemigrations.MigrationAutodetector
        style = self.style

        class StyledMigrationAutodetector(MigrationAutodetector):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs, style=style)

        if hasattr(self, "autodetector"):
            self.autodetector = StyledMigrationAutodetector
        else:
            makemigrations.MigrationAutodetector = StyledMigrationAutodetector
        try:
            super().handle(*args, **options)
        finally:
            if not hasattr(self, "autodetector"):
                makemigrations.MigrationAutodetector = MigrationAutodetector_
