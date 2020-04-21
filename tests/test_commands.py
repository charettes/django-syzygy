from django.core.management import CommandError, call_command
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.test import TransactionTestCase


class MigrateTests(TransactionTestCase):
    def get_applied_migrations(self):
        return {
            name
            for (app_label, name) in MigrationRecorder(connection).applied_migrations()
            if app_label == "tests"
        }

    def assert_not_applied(self, name):
        self.assertIn(("tests", name), self.recorder.applied_migrations())

    def test_pre_deploy_forward(self):
        with self.settings(
            MIGRATION_MODULES={"tests": "tests.test_migrations.functional"}
        ):
            call_command("migrate", "tests", pre_deploy=True, verbosity=0)
        self.assertEqual(self.get_applied_migrations(), {"0001_pre_deploy"})

    def test_pre_deploy_backward(self):
        with self.settings(
            MIGRATION_MODULES={"tests": "tests.test_migrations.functional"}
        ):
            call_command("migrate", "tests", verbosity=0)
            self.assertEqual(
                self.get_applied_migrations(), {"0001_pre_deploy", "0002_post_deploy"}
            )
            call_command("migrate", "tests", "zero", pre_deploy=True, verbosity=0)
            self.assertEqual(self.get_applied_migrations(), {"0001_pre_deploy"})

    def test_ambiguous(self):
        with self.settings(
            MIGRATION_MODULES={"tests": "tests.test_migrations.ambiguous"}
        ):
            with self.assertRaisesMessage(CommandError, 'Cannot automatically determine stage of tests.0001_initial.'):
                call_command("migrate", "tests", pre_deploy=True, verbosity=0)
