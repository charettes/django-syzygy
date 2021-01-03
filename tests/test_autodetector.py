from typing import List

from django.db import models
from django.db.migrations.state import ModelState, ProjectState
from django.test import TestCase

from syzygy.autodetector import MigrationAutodetector
from syzygy.constants import Stage
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
    ):
        return MigrationAutodetector(
            self.make_project_state(before_states),
            self.make_project_state(after_states),
        )._detect_changes()

    def test_non_nullable_field_removal(self):
        from_model = ModelState("tests", "Model", [("field", models.IntegerField())])
        to_model = ModelState("tests", "Model", [])
        changes = self.get_changes([from_model], [to_model])["tests"]
        self.assertEqual(len(changes), 2)
        self.assertEqual(get_migration_stage(changes[0]), Stage.PRE_DEPLOY)
        self.assertEqual(changes[0].dependencies, [])
        self.assertEqual(get_migration_stage(changes[1]), Stage.POST_DEPLOY)
        self.assertEqual(changes[1].dependencies, [("tests", "auto_1")])
