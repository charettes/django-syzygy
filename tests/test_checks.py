from django.apps import apps
from django.core.checks import run_checks
from django.core.checks.messages import Error
from django.test import SimpleTestCase


class ChecksTests(SimpleTestCase):
    hint = (
        "Assign an explicit stage to it, break its operation into multiple "
        "migrations if it's not already applied or define an explicit stage for "
        "it using `MIGRATION_STAGE_OVERRIDE` or `MIGRATION_STAGE_FALLBACK` if the "
        "migration is not under your control."
    )

    def test_ambiguous_stage(self):
        with self.settings(
            MIGRATION_MODULES={"tests": "tests.test_migrations.ambiguous"}
        ):
            checks = run_checks(
                app_configs=[apps.get_app_config("tests")], tags={"migrations"}
            )
        self.assertEqual(len(checks), 1)
        self.assertEqual(
            checks[0],
            Error(
                msg="Cannot automatically determine stage of tests.0001_initial.",
                hint=self.hint,
                obj=("tests", "0001_initial"),
                id="migrations.0001",
            ),
        )
