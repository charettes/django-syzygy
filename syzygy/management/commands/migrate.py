import time
from contextlib import contextmanager
from datetime import timedelta
from typing import Iterator

from django.apps import apps
from django.core.management import CommandError
from django.core.management.commands import migrate  # type: ignore
from django.db import connections
from django.db.migrations.exceptions import AmbiguityError
from django.db.migrations.executor import MigrationExecutor

from syzygy.constants import Stage
from syzygy.plan import Plan, get_pre_deploy_plan, hash_plan
from syzygy.quorum import join_quorum, poll_quorum


class PreDeployMigrationExecutor(MigrationExecutor):
    def migration_plan(self, targets, clean_start=False) -> Plan:
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
        parser.add_argument(
            "--quorum",
            type=int,
            default=1,
            dest="quorum",
            help="Number of parties required to proceed with the migration plan.",
        )
        parser.add_argument(
            "--quorum-timeout",
            type=int,
            default=int(timedelta(minutes=30).total_seconds()),
            help="Number of seconds to wait before giving up waiting for quorum.",
        )

    def _get_plan(self, **options):  # pragma: no cover
        # XXX: Unfortunate copy-pasta from migrate.Command.handle.

        # Get the database we're operating from
        db = options["database"]
        connection = connections[db]

        # Hook for backends needing any database preparation
        connection.prepare_database()
        # Work out which apps have migrations and which do not
        executor = migrate.MigrationExecutor(
            connection, self.migration_progress_callback
        )

        # Raise an error if any migrations are applied before their dependencies.
        executor.loader.check_consistent_history(connection)

        # Before anything else, see if there's conflicting apps and drop out
        # hard if there are any
        conflicts = executor.loader.detect_conflicts()
        if conflicts:
            name_str = "; ".join(
                "%s in %s" % (", ".join(names), app) for app, names in conflicts.items()
            )
            raise CommandError(
                "Conflicting migrations detected; multiple leaf nodes in the "
                "migration graph: (%s).\nTo fix them run "
                "'python manage.py makemigrations --merge'" % name_str
            )

        # If they supplied command line arguments, work out what they mean.
        run_syncdb = options["run_syncdb"]
        if options["app_label"]:
            # Validate app_label.
            app_label = options["app_label"]
            try:
                apps.get_app_config(app_label)
            except LookupError as err:
                raise CommandError(str(err))
            if run_syncdb:
                if app_label in executor.loader.migrated_apps:
                    raise CommandError(
                        "Can't use run_syncdb with app '%s' as it has migrations."
                        % app_label
                    )
            elif app_label not in executor.loader.migrated_apps:
                raise CommandError("App '%s' does not have migrations." % app_label)

        if options["app_label"] and options["migration_name"]:
            migration_name = options["migration_name"]
            if migration_name == "zero":
                targets = [(app_label, None)]
            else:
                try:
                    migration = executor.loader.get_migration_by_prefix(
                        app_label, migration_name
                    )
                except AmbiguityError:
                    raise CommandError(
                        "More than one migration matches '%s' in app '%s'. "
                        "Please be more specific." % (migration_name, app_label)
                    )
                except KeyError:
                    raise CommandError(
                        "Cannot find a migration matching '%s' from app '%s'."
                        % (migration_name, app_label)
                    )
                targets = [(app_label, migration.name)]
        elif options["app_label"]:
            targets = [
                key for key in executor.loader.graph.leaf_nodes() if key[0] == app_label
            ]
        else:
            targets = executor.loader.graph.leaf_nodes()

        return executor.migration_plan(targets)

    def _poll_until_quorum(
        self, namespace: str, quorum: int, quorum_timeout: int
    ) -> float:
        started_at = time.monotonic()
        while not poll_quorum(namespace, quorum):
            if (time.monotonic() - started_at) > quorum_timeout:
                raise RuntimeError("Migration plan quorum timeout")
            time.sleep(1)
        return time.monotonic() - started_at

    @contextmanager
    def _handle_quorum(
        self, quorum: int, quorum_timeout: int, options: dict
    ) -> Iterator[bool]:
        """
        Context manager that handles migration application quorum by only
        allowing a single caller to proceed with application and preventing
        exit attempts until the application is completes.

        This ensures only a single invocation is allowed to proceed once
        quorum is reached and that context can only be exited once the
        invocation application succeeds.
        """
        if quorum < 2:
            yield True
            return
        verbosity = options["verbosity"]
        plan = self._get_plan(**options)
        if not plan:
            yield True
            return
        database = options["database"]
        plan_hash = hash_plan(plan)
        pre_namespace = f"pre:{database}:{plan_hash}"
        post_namespace = f"post:{database}:{plan_hash}"
        if join_quorum(pre_namespace, quorum):
            if verbosity:
                self.stdout.write(
                    "Reached pre-migrate quorum, proceeding with planned migrations..."
                )
            yield True
            join_quorum(post_namespace, quorum)
            if verbosity:
                self.stdout.write("Waiting for post-migrate quorum...")
            duration = self._poll_until_quorum(post_namespace, quorum, quorum_timeout)
            if verbosity:
                self.stdout.write(
                    f"Reached post-migrate quorum after {duration:.2f}s..."
                )
            return
        yield False
        if verbosity:
            self.stdout.write("Waiting for pre-migrate quorum...")
        duration = self._poll_until_quorum(pre_namespace, quorum, quorum_timeout)
        if verbosity:
            self.stdout.write(f"Reached pre-migrate quorum after {duration:.2f}s...")
            self.stdout.write("Waiting for migrations to be applied by remote party...")
        join_quorum(post_namespace, quorum)
        duration = self._poll_until_quorum(post_namespace, quorum, quorum_timeout)
        if verbosity:
            self.stdout.write(f"Reached post-migrate quorum after {duration:.2f}s...")
            self.stdout.write("Migrations applied by remote party")
        return

    def handle(
        self,
        *args,
        stage: Stage,
        quorum: int,
        quorum_timeout: int,
        **options,
    ):
        with _patch_executor(stage), self._handle_quorum(
            quorum, quorum_timeout, options
        ) as proceed:
            if proceed:
                super().handle(*args, **options)
