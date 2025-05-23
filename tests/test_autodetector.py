from typing import List, Optional
from unittest import mock, skipUnless

from django.core.management.color import color_style
from django.db import migrations, models
from django.db.migrations.questioner import (
    InteractiveMigrationQuestioner,
    MigrationQuestioner,
)
from django.db.migrations.state import ModelState, ProjectState
from django.test import TestCase
from django.test.utils import captured_stderr, captured_stdin, captured_stdout

from syzygy.autodetector import STAGE_SPLIT, MigrationAutodetector
from syzygy.compat import field_db_default_supported
from syzygy.constants import Stage
from syzygy.exceptions import AmbiguousStage
from syzygy.operations import (
    AddField,
    AlterField,
    PostAddField,
    PreRemoveField,
    RenameField,
    RenameModel,
)
from syzygy.plan import get_migration_stage

from .models import Bar


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
        self.assertNotIn(STAGE_SPLIT, changes)
        return changes


class AutodetectorTests(AutodetectorTestCase):
    def _test_field_addition(self, field, expected_db_default=None):
        from_model = ModelState("tests", "Model", [])
        to_model = ModelState("tests", "Model", [("field", field)])
        changes = self.get_changes([from_model], [to_model])["tests"]
        self.assertEqual(len(changes), 2)
        self.assertEqual(get_migration_stage(changes[0]), Stage.PRE_DEPLOY)
        self.assertEqual(changes[0].dependencies, [])
        self.assertEqual(len(changes[0].operations), 1)
        pre_operation = changes[0].operations[0]
        if field_db_default_supported:
            self.assertIsInstance(pre_operation, migrations.AddField)
            self.assertEqual(
                pre_operation.field.db_default,
                expected_db_default or field.get_default(),
            )
        else:
            self.assertIsInstance(pre_operation, AddField)
        self.assertEqual(get_migration_stage(changes[1]), Stage.POST_DEPLOY)
        self.assertEqual(changes[1].dependencies, [("tests", "auto_1")])
        self.assertEqual(len(changes[1].operations), 1)
        post_operation = changes[1].operations[0]
        if field_db_default_supported:
            self.assertIsInstance(post_operation, AlterField)
            self.assertIs(post_operation.field.db_default, models.NOT_PROVIDED)
        else:
            self.assertIsInstance(post_operation, PostAddField)

    def test_field_addition(self):
        fields = [
            models.IntegerField(default=42),
            models.IntegerField(null=True, default=42),
            models.IntegerField(default=lambda: 42),
            # Foreign keys with callable defaults should have their associated
            # db_default generated with care.
            (models.ForeignKey("tests.Model", models.CASCADE, default=42), 42),
            (
                models.ForeignKey(
                    "tests.Bar", models.CASCADE, default=lambda: Bar(id=42)
                ),
                42,
            ),
            (
                models.ForeignKey(
                    "tests.bar",
                    models.CASCADE,
                    to_field="name",
                    default=lambda: Bar(id=123, name="bar"),
                ),
                "bar",
            ),
        ]
        for field in fields:
            if isinstance(field, tuple):
                field, expected_db_default = field
            else:
                expected_db_default = None
            with self.subTest(field=field):
                self._test_field_addition(field, expected_db_default)

    def test_many_to_many_addition(self):
        from_model = ModelState("tests", "Model", [])
        to_model = ModelState(
            "tests", "Model", [("field", models.ManyToManyField("self"))]
        )
        changes = self.get_changes([from_model], [to_model])["tests"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(get_migration_stage(changes[0]), Stage.PRE_DEPLOY)
        self.assertEqual(changes[0].dependencies, [])
        self.assertEqual(len(changes[0].operations), 1)
        operation = changes[0].operations[0]
        self.assertIsInstance(operation, migrations.AddField)

    def test_nullable_field_addition(self):
        """
        No action required if the field is already NULL'able and doesn't have
        a `default`.
        """
        from_model = ModelState("tests", "Model", [])
        to_model = ModelState(
            "tests", "Model", [("field", models.IntegerField(null=True))]
        )
        changes = self.get_changes([from_model], [to_model])["tests"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(get_migration_stage(changes[0]), Stage.PRE_DEPLOY)

    @skipUnless(field_db_default_supported, "Field.db_default is not supported")
    def test_db_default_field_addition(self):
        """
        No action required if the field already has a `db_default`
        """
        from_model = ModelState("tests", "Model", [])
        to_model = ModelState(
            "tests", "Model", [("field", models.IntegerField(db_default=42))]
        )
        changes = self.get_changes([from_model], [to_model])["tests"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(get_migration_stage(changes[0]), Stage.PRE_DEPLOY)

    def _test_field_removal(self, field):
        from_model = ModelState("tests", "Model", [("field", field)])
        to_model = ModelState("tests", "Model", [])
        changes = self.get_changes([from_model], [to_model])["tests"]
        self.assertEqual(len(changes), 2)
        self.assertEqual(get_migration_stage(changes[0]), Stage.PRE_DEPLOY)
        self.assertEqual(changes[0].dependencies, [])
        self.assertEqual(len(changes[0].operations), 1)
        pre_operation = changes[0].operations[0]
        if field_db_default_supported:
            self.assertIsInstance(pre_operation, migrations.AlterField)
            if field.has_default():
                self.assertEqual(pre_operation.field.db_default, 42)
            else:
                self.assertIs(pre_operation.field.null, True)
        else:
            self.assertIsInstance(pre_operation, PreRemoveField)
        if not field.has_default():
            self.assertIs(pre_operation.field.null, True)
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

    def test_many_to_many_removal(self):
        from_model = ModelState(
            "tests", "Model", [("field", models.ManyToManyField("self"))]
        )
        to_model = ModelState("tests", "Model", [])
        changes = self.get_changes([from_model], [to_model])["tests"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(get_migration_stage(changes[0]), Stage.POST_DEPLOY)
        self.assertEqual(changes[0].dependencies, [])
        self.assertEqual(len(changes[0].operations), 1)
        operation = changes[0].operations[0]
        self.assertIsInstance(operation, migrations.RemoveField)

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

    @skipUnless(field_db_default_supported, "Field.db_default is not supported")
    def test_db_default_field_removal(self):
        """
        No action required if the field already has a `db_default`
        """
        from_model = ModelState(
            "tests", "Model", [("field", models.IntegerField(db_default=42))]
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
        questioner.defaults["ask_rename_field_stage"] = 2
        with captured_stderr():
            changes = self.get_changes(from_models, to_models, questioner)["tests"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(get_migration_stage(changes[0]), Stage.PRE_DEPLOY)
        self.assertIsInstance(changes[0].operations[0], RenameField)
        # Post-deploy rename.
        questioner.defaults["ask_rename_field_stage"] = 3
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
        questioner.defaults["ask_rename_model_stage"] = 2
        with captured_stderr():
            changes = self.get_changes(from_models, to_models, questioner)["tests"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(get_migration_stage(changes[0]), Stage.PRE_DEPLOY)
        self.assertIsInstance(changes[0].operations[0], RenameModel)
        # Post-deploy rename.
        questioner.defaults["ask_rename_model_stage"] = 3
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
        if field_db_default_supported:
            self.assertIsInstance(changes[1].operations[0], AlterField)
        else:
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
        questioner = MigrationQuestioner({"ask_ambiguous_abort": True})
        with self.assertRaisesMessage(SystemExit, "3"), mock.patch(
            "syzygy.autodetector.partition_operations", side_effect=AmbiguousStage
        ), captured_stderr() as stderr:
            self.get_changes(from_models, to_models, questioner)["tests"]


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
        ), captured_stdin() as stdin, captured_stdout() as stdout, captured_stderr():
            questioner = InteractiveMigrationQuestioner()
            stdin.write("1\n")
            stdin.seek(0)
            self.get_changes(from_models, to_models, questioner)["tests"]
        self.assertEqual(
            stdout.getvalue(),
            "\n 1) Let `makemigrations` complete. You'll have to manually break you operations in migrations "
            "with non-ambiguous stages.\n 2) Abort `makemigrations`. You'll have to reduce the number of model "
            "changes before running `makemigrations` again.\nSelect an option: ",
        )
