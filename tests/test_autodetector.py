from typing import List, Optional
from unittest import mock

from django.core.management.color import color_style
from django.db import migrations, models
from django.db.migrations.questioner import (
    InteractiveMigrationQuestioner,
    MigrationQuestioner,
)
from django.db.migrations.state import ModelState, ProjectState
from django.test import TestCase
from django.test.utils import captured_stderr, captured_stdin, captured_stdout

from syzygy.autodetector import MigrationAutodetector
from syzygy.constants import Stage
from syzygy.exceptions import AmbiguousStage
from syzygy.operations import (
    AddField,
    PostAddField,
    PreRemoveField,
    RenameField,
    RenameModel,
)
from syzygy.plan import get_migration_stage


class AutodetectorTestCase(TestCase):
    style = color_style()

    @staticmethod
    def make_project_state(model_states: List[ModelState]) -> ProjectState:
        project_state = ProjectState()
        for model_state in model_states:
            project_state.add_model(model_state.clone())
        return project_state

    def get_changes(
        self,
        before_states: List[ModelState],
        after_states: List[ModelState],
        questioner: Optional[MigrationQuestioner] = None,
    ) -> List[migrations.Migration]:
        changes = MigrationAutodetector(
            self.make_project_state(before_states),
            self.make_project_state(after_states),
            questioner=questioner,
            style=self.style,
        )._detect_changes()
        self.assertNotIn(MigrationAutodetector.STAGE_SPLIT, changes)
        return changes


class AutodetectorTests(AutodetectorTestCase):
    def test_field_addition(self):
        from_model = ModelState("tests", "Model", [])
        to_model = ModelState(
            "tests", "Model", [("field", models.IntegerField(default=42))]
        )
        changes = self.get_changes([from_model], [to_model])["tests"]
        self.assertEqual(len(changes), 2)
        self.assertEqual(get_migration_stage(changes[0]), Stage.PRE_DEPLOY)
        self.assertEqual(changes[0].dependencies, [])
        self.assertEqual(len(changes[0].operations), 1)
        self.assertIsInstance(changes[0].operations[0], AddField)
        self.assertEqual(get_migration_stage(changes[1]), Stage.POST_DEPLOY)
        self.assertEqual(changes[1].dependencies, [("tests", "auto_1")])
        self.assertEqual(len(changes[1].operations), 1)
        self.assertIsInstance(changes[1].operations[0], PostAddField)

    def _test_field_removal(self, field):
        from_model = ModelState("tests", "Model", [("field", field)])
        to_model = ModelState("tests", "Model", [])
        changes = self.get_changes([from_model], [to_model])["tests"]
        self.assertEqual(len(changes), 2)
        self.assertEqual(get_migration_stage(changes[0]), Stage.PRE_DEPLOY)
        self.assertEqual(changes[0].dependencies, [])
        self.assertEqual(len(changes[0].operations), 1)
        self.assertIsInstance(changes[0].operations[0], PreRemoveField)
        self.assertEqual(get_migration_stage(changes[1]), Stage.POST_DEPLOY)
        self.assertEqual(changes[1].dependencies, [("tests", "auto_1")])
        self.assertEqual(len(changes[1].operations), 1)
        self.assertIsInstance(changes[1].operations[0], migrations.RemoveField)

    def test_field_removal(self):
        fields = [
            models.IntegerField(),
            models.IntegerField(default=42),
            models.IntegerField(null=True, default=42),
        ]
        for field in fields:
            with self.subTest(field=field):
                self._test_field_removal(field)

    def test_nullable_field_removal(self):
        """
        No action required if the field is already NULL'able and doesn't have
        a `default`.
        """
        from_model = ModelState(
            "tests", "Model", [("field", models.IntegerField(null=True))]
        )
        to_model = ModelState("tests", "Model", [])
        changes = self.get_changes([from_model], [to_model])["tests"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(get_migration_stage(changes[0]), Stage.POST_DEPLOY)

    def test_non_nullable_field_removal_default(self):
        from_model = ModelState("tests", "Model", [("field", models.IntegerField())])
        to_model = ModelState("tests", "Model", [])
        changes = self.get_changes(
            [from_model], [to_model], MigrationQuestioner({"ask_remove_default": 42})
        )["tests"]
        self.assertEqual(len(changes), 2)
        self.assertEqual(get_migration_stage(changes[0]), Stage.PRE_DEPLOY)
        self.assertEqual(changes[0].operations[0].field.default, 42)
        self.assertEqual(get_migration_stage(changes[1]), Stage.POST_DEPLOY)

    def test_alter_field_null_to_not_null(self):
        from_model = ModelState(
            "tests", "Model", [("field", models.IntegerField(null=True))]
        )
        to_model = ModelState("tests", "Model", [("field", models.IntegerField())])
        changes = self.get_changes([from_model], [to_model])["tests"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(get_migration_stage(changes[0]), Stage.POST_DEPLOY)

    def test_field_rename(self):
        from_models = [
            ModelState(
                "tests",
                "Foo",
                [
                    ("id", models.IntegerField(primary_key=True)),
                    ("foo", models.BooleanField(default=False)),
                ],
            ),
        ]
        to_models = [
            ModelState(
                "tests",
                "Foo",
                [
                    ("id", models.IntegerField(primary_key=True)),
                    ("bar", models.BooleanField(default=False)),
                ],
            ),
        ]
        questioner = MigrationQuestioner({"ask_rename": True})
        with captured_stderr(), self.assertRaisesMessage(SystemExit, "3"):
            self.get_changes(from_models, to_models, questioner)["tests"]
        # Pre-deploy rename.
        questioner.defaults["ask_rename_field_stage"] = 1
        with captured_stderr():
            changes = self.get_changes(from_models, to_models, questioner)["tests"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(get_migration_stage(changes[0]), Stage.PRE_DEPLOY)
        self.assertIsInstance(changes[0].operations[0], RenameField)
        # Post-deploy rename.
        questioner.defaults["ask_rename_field_stage"] = 2
        with captured_stderr():
            changes = self.get_changes(from_models, to_models, questioner)["tests"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(get_migration_stage(changes[0]), Stage.POST_DEPLOY)
        self.assertIsInstance(changes[0].operations[0], RenameField)

    def test_model_rename(self):
        from_models = [
            ModelState(
                "tests",
                "Foo",
                [
                    ("id", models.IntegerField(primary_key=True)),
                ],
            ),
        ]
        to_models = [
            ModelState(
                "tests",
                "Bar",
                [
                    ("id", models.IntegerField(primary_key=True)),
                ],
            ),
        ]
        questioner = MigrationQuestioner(
            {
                "ask_rename_model": True,
            }
        )
        with captured_stderr(), self.assertRaisesMessage(SystemExit, "3"):
            self.get_changes(from_models, to_models, questioner)["tests"]
        # Pre-deploy rename.
        questioner.defaults["ask_rename_model_stage"] = 1
        with captured_stderr():
            changes = self.get_changes(from_models, to_models, questioner)["tests"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(get_migration_stage(changes[0]), Stage.PRE_DEPLOY)
        self.assertIsInstance(changes[0].operations[0], RenameModel)
        # Post-deploy rename.
        questioner.defaults["ask_rename_model_stage"] = 2
        with captured_stderr():
            changes = self.get_changes(from_models, to_models, questioner)["tests"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(get_migration_stage(changes[0]), Stage.POST_DEPLOY)
        self.assertIsInstance(changes[0].operations[0], RenameModel)
        # db_table override
        to_models[0].options["db_table"] = "tests_foo"
        changes = self.get_changes(from_models, to_models, questioner)["tests"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(get_migration_stage(changes[0]), Stage.PRE_DEPLOY)
        self.assertIsInstance(changes[0].operations[0], migrations.RenameModel)


class AutodetectorStageTests(AutodetectorTestCase):
    def test_mixed_stage_same_app(self):
        from_models = [
            ModelState(
                "tests", "Model", [("field", models.IntegerField(primary_key=True))]
            )
        ]
        to_models = [
            ModelState(
                "tests",
                "OtherModel",
                [("field", models.IntegerField(primary_key=True))],
            )
        ]
        changes = self.get_changes(from_models, to_models)["tests"]
        self.assertEqual(len(changes), 2)
        self.assertEqual(get_migration_stage(changes[0]), Stage.PRE_DEPLOY)
        self.assertEqual(changes[0].dependencies, [])
        self.assertEqual(len(changes[0].operations), 1)
        self.assertIsInstance(changes[0].operations[0], migrations.CreateModel)
        self.assertEqual(get_migration_stage(changes[1]), Stage.POST_DEPLOY)
        self.assertEqual(changes[1].dependencies, [("tests", "auto_1")])
        self.assertEqual(len(changes[1].operations), 1)
        self.assertIsInstance(changes[1].operations[0], migrations.DeleteModel)

    def test_mixed_stage_reorder(self):
        from_models = [
            ModelState("tests", "Foo", [("id", models.IntegerField(primary_key=True))]),
            ModelState(
                "tests",
                "Bar",
                [
                    ("id", models.IntegerField(primary_key=True)),
                    ("foo", models.ForeignKey("Foo", models.CASCADE)),
                ],
            ),
        ]
        to_models = [
            ModelState(
                "tests",
                "Foo",
                [
                    ("id", models.IntegerField(primary_key=True)),
                    ("bar", models.BooleanField(default=False)),
                ],
            ),
        ]
        changes = self.get_changes(from_models, to_models)["tests"]
        self.assertEqual(len(changes), 2)
        self.assertEqual(get_migration_stage(changes[0]), Stage.PRE_DEPLOY)
        self.assertEqual(changes[0].dependencies, [])
        self.assertEqual(len(changes[0].operations), 1)
        self.assertIsInstance(changes[0].operations[0], migrations.AddField)
        self.assertEqual(get_migration_stage(changes[1]), Stage.POST_DEPLOY)
        self.assertEqual(changes[1].dependencies, [("tests", "auto_1")])
        self.assertEqual(len(changes[1].operations), 2)
        self.assertIsInstance(changes[1].operations[0], PostAddField)
        self.assertIsInstance(changes[1].operations[1], migrations.DeleteModel)

    def test_mixed_stage_failure(self):
        from_models = [
            ModelState("tests", "Foo", [("id", models.IntegerField(primary_key=True))]),
            ModelState(
                "tests",
                "Bar",
                [
                    ("id", models.IntegerField(primary_key=True)),
                    ("foo", models.ForeignKey("Foo", models.CASCADE)),
                ],
            ),
        ]
        to_models = [
            ModelState(
                "tests",
                "Foo",
                [
                    ("id", models.IntegerField(primary_key=True)),
                    ("bar", models.BooleanField(default=False)),
                ],
            ),
        ]
        with mock.patch(
            "syzygy.autodetector.partition_operations", side_effect=AmbiguousStage
        ), captured_stderr() as stderr:
            self.get_changes(from_models, to_models)["tests"]
        self.assertIn(
            'The auto-detected operations for the "tests" app cannot be partitioned into deployment stages:',
            stderr.getvalue(),
        )
        self.assertIn(
            "- Remove field foo from bar",
            stderr.getvalue(),
        )


class InteractiveAutodetectorTests(AutodetectorTestCase):
    def test_field_rename(self):
        from_models = [
            ModelState(
                "tests",
                "Foo",
                [
                    ("id", models.IntegerField(primary_key=True)),
                    ("foo", models.BooleanField(default=False)),
                ],
            ),
        ]
        to_models = [
            ModelState(
                "tests",
                "Foo",
                [
                    ("id", models.IntegerField(primary_key=True)),
                    ("bar", models.BooleanField(default=False)),
                ],
            ),
        ]
        with captured_stdin() as stdin, captured_stdout() as stdout, captured_stderr() as stderr:
            questioner = InteractiveMigrationQuestioner()
            stdin.write("y\n2\n")
            stdin.seek(0)
            self.get_changes(from_models, to_models, questioner)
        self.assertIn(
            self.style.WARNING(
                "Renaming a column from a database table actively relied upon might cause downtime during deployment."
            ),
            stderr.getvalue(),
        )
        self.assertIn(
            "1) Quit, and let me add a new foo.bar field meant to be backfilled with foo.foo values",
            stdout.getvalue(),
        )
        self.assertIn(
            self.style.MIGRATE_LABEL(
                "This might cause downtime if your assumption is wrong"
            ),
            stdout.getvalue(),
        )

    def test_model_rename(self):
        from_models = [
            ModelState(
                "tests",
                "Foo",
                [
                    ("id", models.IntegerField(primary_key=True)),
                ],
            ),
        ]
        to_models = [
            ModelState(
                "tests",
                "Bar",
                [
                    ("id", models.IntegerField(primary_key=True)),
                ],
            ),
        ]
        with captured_stdin() as stdin, captured_stdout() as stdout, captured_stderr() as stderr:
            questioner = InteractiveMigrationQuestioner()
            stdin.write("y\n2\n")
            stdin.seek(0)
            self.get_changes(from_models, to_models, questioner)
        self.assertIn(
            self.style.WARNING(
                "Renaming an actively relied on database table might cause downtime during deployment."
            ),
            stderr.getvalue(),
        )
        self.assertIn(
            '1) Quit, and let me manually set tests.Bar.Meta.db_table to "tests_foo" to avoid '
            "renaming its underlying table",
            stdout.getvalue(),
        )
        self.assertIn(
            self.style.MIGRATE_LABEL(
                "This might cause downtime if your assumption is wrong"
            ),
            stdout.getvalue(),
        )
