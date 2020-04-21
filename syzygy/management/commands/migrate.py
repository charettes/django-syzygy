from django.apps import apps
from django.core.management import CommandError
from django.core.management.commands.migrate import (  # type: ignore
    Command as MigrateCommand,
)
from django.db.models.signals import pre_migrate

from syzygy.plan import get_pre_deploy_plan


class Command(MigrateCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--pre-deploy",
            action="store_true",
            help="Only run migrations staged for pre-deployment.",
        )

    def migrate_pre_deploy(self, plan, **kwargs):
        try:
            plan[:] = get_pre_deploy_plan(plan)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

    def handle(self, *args, pre_deploy, **options):
        if pre_deploy:
            pre_migrate.connect(self.migrate_pre_deploy, sender=apps.get_app_config('syzygy'))
        super().handle(*args, **options)
