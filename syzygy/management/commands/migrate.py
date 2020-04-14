from django.core.management import CommandError
from django.core.management.commands.migrate import (  # type: ignore
    Command as MigrateCommand,
)
from django.db.models.signals import pre_migrate

from syzygy.plan import get_prerequisite_plan


class Command(MigrateCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument("--prerequisite", action="store_true")

    def migrate_prerequisite(self, plan, **kwargs):
        try:
            plan[:] = get_prerequisite_plan(plan)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

    def handle(self, *args, prerequisite, **options):
        if prerequisite:
            pre_migrate.connect(self.migrate_prerequisite)
        super().handle(*args, **options)
