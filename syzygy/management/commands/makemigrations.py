from django.core.management.commands import makemigrations  # type: ignore

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
        makemigrations.MigrationAutodetector = MigrationAutodetector
        try:
            super().handle(*args, **options)
        finally:
            makemigrations.MigrationAutodetector = MigrationAutodetector_
