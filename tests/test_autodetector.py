from typing import List

from django.db import migrations, models
from django.db.migrations.state import ModelState, ProjectState
from django.test import TestCase

from syzygy.autodetector import MigrationAutodetector
from syzygy.constants import Stage
from syzygy.operations import PreRemoveField
from syzygy.plan import get_migration_stage


class AutodetectorTests(TestCase):
    @staticmethod
    def make_project_state(model_states: List[ModelState]) -> ProjectState:
        project_state = ProjectState()
        for model_state in model_states:
            project_state.add_model(model_state.clone())
        return project_state

    def get_changes(
        self, before_states: List[ModelState], after_states: List[ModelState]
    ) -> List[migrations.Migration]:
        return MigrationAutodetector(
            self.make_project_state(before_states),
            self.make_project_state(after_states),
        )._detect_changes()

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
