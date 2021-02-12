from io import StringIO
from unittest import mock

import django
from django.core.management import CommandError, call_command
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.test import TestCase, TransactionTestCase, override_settings


class MigrateTests(TransactionTestCase):
    def tearDown(self):
        MigrationRecorder(connection).flush()

    def get_applied_migrations(self):
        return {
            name
            for (app_label, name) in MigrationRecorder(connection).applied_migrations()
            if app_label == "tests"
        }

    def assert_not_applied(self, name):
        self.assertIn(("tests", name), self.recorder.applied_migrations())

    @override_settings(MIGRATION_MODULES={"tests": "tests.test_migrations.functional"})
    def test_pre_deploy_forward(self):
        stdout = StringIO()
        call_command(
            "migrate", "tests", plan=True, no_color=True, pre_deploy=True, stdout=stdout
        )
        self.assertIn("tests.0001_pre_deploy", stdout.getvalue())
        self.assertNotIn("tests.0002_post_deploy", stdout.getvalue())
        call_command("migrate", "tests", pre_deploy=True, verbosity=0)
        self.assertEqual(self.get_applied_migrations(), {"0001_pre_deploy"})

    @override_settings(MIGRATION_MODULES={"tests": "tests.test_migrations.functional"})
    def test_pre_deploy_backward(self):
        call_command("migrate", "tests", verbosity=0)
        self.assertEqual(
            self.get_applied_migrations(), {"0001_pre_deploy", "0002_post_deploy"}
        )
        stdout = StringIO()
        call_command(
            "migrate",
            "tests",
            "zero",
            plan=True,
            no_color=True,
            pre_deploy=True,
            stdout=stdout,
        )
        self.assertIn("tests.0002_post_deploy", stdout.getvalue())
        self.assertNotIn("tests.0001_pre_deploy", stdout.getvalue())
        call_command("migrate", "tests", "zero", pre_deploy=True, verbosity=0)
        self.assertEqual(self.get_applied_migrations(), {"0001_pre_deploy"})

    @override_settings(MIGRATION_MODULES={"tests": "tests.test_migrations.ambiguous"})
    def test_ambiguous(self):
        with self.assertRaisesMessage(
            CommandError, "Cannot automatically determine stage of tests.0001_initial."
        ):
            call_command("migrate", "tests", pre_deploy=True, verbosity=0)


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
