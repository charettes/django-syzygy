from contextlib import contextmanager

from django.core.management import CommandError
from django.core.management.commands import migrate  # type: ignore
from django.db.migrations.executor import MigrationExecutor

from syzygy.constants import Stage
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


@contextmanager
def _patch_executor(stage: Stage):
    """
    Monkey-patch migrate.MigrationExecutor if necessary since the command
    doesn't allow it to be overridden in any other way.
    """
    if stage is Stage.PRE_DEPLOY:
        migrate.MigrationExecutor = PreDeployMigrationExecutor
    try:
        yield
    finally:
        migrate.MigrationExecutor = MigrationExecutor


class Command(migrate.Command):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--pre-deploy",
            action="store_const",
            const=Stage.PRE_DEPLOY,
            default=Stage.POST_DEPLOY,
            dest="stage",
            help="Only run migrations staged for pre-deployment.",
        )

    def handle(self, *args, stage: Stage, **options):
        with _patch_executor(stage):
            super().handle(*args, **options)
