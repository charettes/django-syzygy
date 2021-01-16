from typing import Any, Dict, List, Optional

from django.db import migrations, models
from django.db.migrations.questioner import MigrationQuestioner
from django.db.migrations.state import ModelState, ProjectState
from django.test import TestCase

from syzygy.autodetector import MigrationAutodetector
from syzygy.constants import Stage
from syzygy.operations import AddField, PostAddField, PreRemoveField
from syzygy.plan import get_migration_stage


class AutodetectorTests(TestCase):
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
        answers: Optional[Dict[str, Any]] = None,
    ) -> List[migrations.Migration]:
        questioner = None
        if answers:
            questioner = MigrationQuestioner(defaults=answers)
        changes = MigrationAutodetector(
            self.make_project_state(before_states),
            self.make_project_state(after_states),
            questioner=questioner,
        )._detect_changes()
        self.assertNotIn(MigrationAutodetector.STAGE_SPLIT, changes)
        return changes

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
            [from_model], [to_model], answers={"ask_remove_default": 42}
        )["tests"]
        self.assertEqual(len(changes), 2)
        self.assertEqual(get_migration_stage(changes[0]), Stage.PRE_DEPLOY)
        self.assertEqual(changes[0].operations[0].field.default, 42)
        self.assertEqual(get_migration_stage(changes[1]), Stage.POST_DEPLOY)

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
