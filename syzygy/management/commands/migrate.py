from django.core.management import CommandError
from django.core.management.commands import migrate  # type: ignore
from django.db.migrations.executor import MigrationExecutor

from syzygy.plan import get_pre_deploy_plan


class PreDeployMigrationExecutor(MigrationExecutor):
    def migration_plan(self, targets, clean_start=False):
        plan = super().migration_plan(targets, clean_start=clean_start)
        if not clean_start:
            try:
                plan = get_pre_deploy_plan(plan)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
        return plan


class Command(migrate.Command):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--pre-deploy",
            action="store_true",
            help="Only run migrations staged for pre-deployment.",
        )

    def handle(self, *args, pre_deploy, **options):
        if pre_deploy:
            # Monkey-patch migrate.MigrationExecutor since the command doesn't
            # allow it to be overridden in any other way.
            migrate.MigrationExecutor = PreDeployMigrationExecutor
        try:
            super().handle(*args, **options)
        finally:
            migrate.MigrationExecutor = MigrationExecutor
