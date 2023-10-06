from io import StringIO
from multiprocessing.pool import ThreadPool
from unittest import mock

import django
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.db import connection, connections
from django.db.migrations.recorder import MigrationRecorder
from django.test import TestCase, TransactionTestCase, override_settings

from syzygy.constants import Stage


class BaseMigrateTests(TransactionTestCase):
    def setUp(self) -> None:
        super().setUp()
        recorder = MigrationRecorder(connection)
        recorder.ensure_schema()
        self.addCleanup(recorder.flush)

    def call_command(self, *args, **options):
        stdout = StringIO()
        call_command("migrate", "tests", *args, no_color=True, stdout=stdout, **options)
        return stdout.getvalue()

    def get_applied_migrations(self):
        return {
            name
            for (app_label, name) in MigrationRecorder(connection).applied_migrations()
            if app_label == "tests"
        }


class MigrateTests(BaseMigrateTests):
    @override_settings(MIGRATION_MODULES={"tests": "tests.test_migrations.functional"})
    def test_pre_deploy_forward(self):
        stdout = self.call_command(plan=True, stage=Stage.PRE_DEPLOY)
        self.assertIn("tests.0001_pre_deploy", stdout)
        self.assertNotIn("tests.0002_post_deploy", stdout)
        call_command("migrate", "tests", stage=Stage.PRE_DEPLOY, verbosity=0)
        self.assertEqual(self.get_applied_migrations(), {"0001_pre_deploy"})

    @override_settings(MIGRATION_MODULES={"tests": "tests.test_migrations.functional"})
    def test_pre_deploy_backward(self):
        self.call_command(verbosity=0)
        self.assertEqual(
            self.get_applied_migrations(), {"0001_pre_deploy", "0002_post_deploy"}
        )
        stdout = self.call_command("zero", plan=True, stage=Stage.PRE_DEPLOY)
        self.assertIn("tests.0002_post_deploy", stdout)
        self.assertNotIn("tests.0001_pre_deploy", stdout)
        self.call_command("zero", stage=Stage.PRE_DEPLOY)
        self.assertEqual(self.get_applied_migrations(), {"0001_pre_deploy"})

    @override_settings(MIGRATION_MODULES={"tests": "tests.test_migrations.ambiguous"})
    def test_ambiguous(self):
        with self.assertRaisesMessage(
            CommandError, "Cannot automatically determine stage of tests.0001_initial."
        ):
            self.call_command(plan=True, stage=Stage.PRE_DEPLOY, verbosity=0)


@override_settings(MIGRATION_QUORUM_BACKEND="syzygy.quorum.backends.cache.CacheQuorum")
class MigrateQuorumTests(BaseMigrateTests):
    def setUp(self):
        super().setUp()
        self.addCleanup(cache.clear)

    @override_settings(MIGRATION_MODULES={"tests": "tests.test_migrations.functional"})
    def test_empty_plan(self):
        """Quorum is entirely skipped when no migrations are planed"""
        stdout = self.call_command("zero", quorum=2)
        self.assertNotIn("quorum", stdout)

    def _call_command_thread(self, options):
        stdout = self.call_command(**options)
        connections.close_all()
        return stdout

    def _call_failing_command_thread(self, options):
        stdout = StringIO()
        stderr = StringIO()
        with self.assertRaises(Exception) as exc:
            call_command(
                "migrate",
                "tests",
                no_color=True,
                stdout=stdout,
                stderr=stderr,
                **options,
            )
        connections.close_all()
        return exc.exception, stdout.getvalue(), stderr.getvalue()

    def call_command_with_quorum(self, stage, quorum=3):
        with mock.patch("time.sleep"), ThreadPool(processes=quorum) as pool:
            stdouts = pool.map_async(
                self._call_command_thread,
                [{"stage": stage, "quorum": quorum}] * quorum,
            ).get()
        apply_stdouts = []
        for stdout in stdouts:
            if stdout.startswith(
                "Reached pre-migrate quorum, proceeding with planned migrations..."
            ):
                apply_stdouts.append(stdout)
                self.assertIn("Reached post-migrate quorum after", stdout)
            else:
                self.assertTrue(stdout.startswith("Waiting for pre-migrate quorum..."))
                self.assertIn("Reached pre-migrate quorum after", stdout)
                self.assertIn(
                    "Waiting for migrations to be applied by remote party...", stdout
                )
                self.assertIn("Reached post-migrate quorum after", stdout)
                self.assertIn("Migrations applied by remote party", stdout)
        if not apply_stdouts:
            self.fail("Migrations were not applied")
        if len(apply_stdouts) > 1:
            self.fail("Migrations were applied more than once")
        return apply_stdouts[0]

    @override_settings(MIGRATION_MODULES={"tests": "tests.test_migrations.functional"})
    def test_pre_deploy(self):
        stdout = self.call_command_with_quorum(stage=Stage.PRE_DEPLOY)
        self.assertIn("tests.0001_pre_deploy", stdout)
        self.assertNotIn("tests.0002_post_deploy", stdout)
        self.assertEqual(self.get_applied_migrations(), {"0001_pre_deploy"})

    @override_settings(MIGRATION_MODULES={"tests": "tests.test_migrations.functional"})
    def test_post_deploy(self):
        stdout = self.call_command_with_quorum(stage=Stage.POST_DEPLOY)
        self.assertIn("tests.0001_pre_deploy", stdout)
        self.assertIn("tests.0002_post_deploy", stdout)
        self.assertEqual(
            self.get_applied_migrations(), {"0001_pre_deploy", "0002_post_deploy"}
        )

    @override_settings(MIGRATION_MODULES={"tests": "tests.test_migrations.functional"})
    def test_quorum_timeout(self):
        msg = "Migration plan quorum timeout"
        with self.assertRaisesMessage(RuntimeError, msg):
            self.call_command(quorum=2, quorum_timeout=1)

    @override_settings(MIGRATION_MODULES={"tests": "tests.test_migrations.crash"})
    def test_quorum_severed(self):
        quorum = 3
        stage = Stage.PRE_DEPLOY
        with mock.patch("time.sleep"), ThreadPool(processes=quorum) as pool:
            results = pool.map_async(
                self._call_failing_command_thread,
                [{"stage": stage, "quorum": quorum}] * quorum,
            ).get()
        severed = 0
        severer = 0
        for exc, stdout, stderr in results:
            if (
                isinstance(exc, CommandError)
                and str(exc)
                == "Error encountered by remote party while applying migration, aborting."
            ):
                self.assertIn(
                    "Waiting for migrations to be applied by remote party...", stdout
                )
                self.assertEqual(stderr, "")
                severed += 1
            elif str(exc) == "Test crash":
                self.assertIn(
                    "Reached pre-migrate quorum, proceeding with planned migrations...",
                    stdout,
                )
                self.assertIn(
                    "Encountered exception while applying migrations, disovling quorum",
                    stderr,
                )
                severer += 1
            else:
                self.fail(f"Unexpected exception: {exc}")
        self.assertEqual(severed, quorum - 1)
        self.assertEqual(severer, 1)


class MakeMigrationsTests(TestCase):
    def test_disabled(self):
        failure = AssertionError("syzygy should be disabled")
        with mock.patch(
            "syzygy.management.commands.makemigrations.MigrationAutodetector",
            side_effect=failure,
        ):
            call_command(
                "makemigrations",
                "tests",
                verbosity=0,
                dry_run=True,
                disable_syzygy=True,
            )

    @override_settings(
        MIGRATION_MODULES={"tests": "tests.test_migrations.null_field_removal"}
    )
    def test_null_field_removal(self):
        stdout = StringIO()
        call_command(
            "makemigrations", "tests", no_color=True, dry_run=True, stdout=stdout
        )
        output = stdout.getvalue()
        if django.VERSION >= (3, 2):
            self.assertIn("null_field_removal/0002_set_db_default_foo_bar.py", output)
        else:
            self.assertIn("null_field_removal/0002_auto", output)
        self.assertIn("- Set database DEFAULT of field bar on foo", output)
        self.assertIn("null_field_removal/0003_remove_foo_bar.py", output)
        self.assertIn("- Remove field bar from foo", output)

    @override_settings(
        MIGRATION_MODULES={"tests": "tests.test_migrations.merge_conflict"}
    )
    def test_merge_conflict(self):
        stdout = StringIO()
        call_command(
            "makemigrations",
            "tests",
            merge=True,
            interactive=False,
            no_color=True,
            dry_run=True,
            stdout=stdout,
        )
        self.assertIn("0002_first", stdout.getvalue())
        self.assertIn("0002_second", stdout.getvalue())
