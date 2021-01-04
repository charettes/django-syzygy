from typing import List

from django.db import connection, migrations, models
from django.db.migrations.operations.base import Operation
from django.db.migrations.state import ProjectState
from django.test import TestCase

from syzygy.operations import PreRemoveField


class PreRemoveFieldTests(TestCase):
    @classmethod
    def setUpClass(cls):
        connection.disable_constraint_checking()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        connection.enable_constraint_checking()

    @staticmethod
    def apply_operations(operations: List[Operation]) -> ProjectState:
        state = ProjectState()
        for operation in operations:
            from_state = state.clone()
            operation.state_forwards("tests", state)
            with connection.schema_editor() as schema_editor:
                operation.database_forwards("tests", schema_editor, from_state, state)
        return state

    def test_database_forwards_null(self):
        model_name = "TestModel"
        field = models.IntegerField()
        operations = [
            migrations.CreateModel(model_name, [("foo", field)]),
            PreRemoveField(
                model_name,
                "foo",
                field,
            ),
        ]
        state = self.apply_operations(operations)
        pre_model = state.apps.get_model("tests", model_name)
        remove_field = migrations.RemoveField(model_name, "foo")
        remove_field.state_forwards("tests", state)
        post_model = state.apps.get_model("tests", model_name)
        post_model.objects.create()
        self.assertIsNone(pre_model.objects.get().foo)

    def test_database_forwards_default(self):
        model_name = "TestModel"
        field = models.IntegerField(default=42)
        operations = [
            migrations.CreateModel(model_name, [("foo", field)]),
            PreRemoveField(
                model_name,
                "foo",
                field,
            ),
        ]
        state = self.apply_operations(operations)
        pre_model = state.apps.get_model("tests", model_name)
        remove_field = migrations.RemoveField(model_name, "foo")
        remove_field.state_forwards("tests", state)
        post_model = state.apps.get_model("tests", model_name)
        post_model.objects.create()
        if connection.vendor == "sqlite":
            # Not implemented on SQLite due to the lack of ALTER TABLE support.
            self.assertIsNone(pre_model.objects.get().foo)
        else:
            self.assertEqual(pre_model.objects.get().foo, 42)
