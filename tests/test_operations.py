from typing import List, Optional, Tuple

from django.db import connection, migrations, models
from django.db.migrations.operations.base import Operation
from django.db.migrations.optimizer import MigrationOptimizer
from django.db.migrations.serializer import OperationSerializer
from django.db.migrations.state import ProjectState
from django.db.models.fields import NOT_PROVIDED
from django.test import TestCase

from syzygy.autodetector import MigrationAutodetector
from syzygy.constants import Stage
from syzygy.operations import AddField, PostAddField, PreRemoveField
from syzygy.plan import get_operation_stage


class OperationTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        connection.disable_constraint_checking()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        connection.enable_constraint_checking()

    @staticmethod
    def apply_operation(
        operation: Operation, state: Optional[ProjectState] = None
    ) -> ProjectState:
        if state is None:
            from_state = ProjectState()
        else:
            from_state = state.clone()
        to_state = from_state.clone()
        operation.state_forwards("tests", to_state)
        with connection.schema_editor() as schema_editor:
            operation.database_forwards("tests", schema_editor, from_state, to_state)
        return to_state

    @classmethod
    def apply_operations(
        cls, operations: List[Operation], state: Optional[ProjectState] = None
    ) -> Optional[ProjectState]:
        for operation in operations:
            state = cls.apply_operation(operation, state)
        return state

    def assert_optimizes_to(
        self, operations: List[Operation], expected: List[Operation]
    ):
        optimized = MigrationOptimizer().optimize(operations, "tests")
        deep_deconstruct = MigrationAutodetector(
            ProjectState(), ProjectState()
        ).deep_deconstruct
        self.assertEqual(deep_deconstruct(optimized), deep_deconstruct(expected))


class AddFieldTests(OperationTestCase):
    def test_database_forwards(self, preserve_default=True):
        model_name = "TestModel"
        field_name = "foo"
        field = models.IntegerField(default=42)
        state = self.apply_operation(
            migrations.CreateModel(model_name, [("id", models.AutoField())]),
        )
        pre_model = state.apps.get_model("tests", model_name)
        state = self.apply_operation(
            AddField(model_name, field_name, field, preserve_default=preserve_default),
            state,
        )
        post_model = state.apps.get_model("tests", model_name)
        pre_model.objects.create()
        self.assertEqual(post_model.objects.get().foo, 42)

    def test_database_forwards_discard_default(self):
        self.test_database_forwards(preserve_default=False)

    def test_deconstruct(self):
        model_name = "TestModel"
        field_name = "foo"
        field = models.IntegerField(default=42)
        operation = AddField(model_name, field_name, field)
        self.assertEqual(
            operation.deconstruct(),
            (
                "AddField",
                [],
                {"model_name": model_name, "name": field_name, "field": field},
            ),
        )
        serializer = OperationSerializer(operation)
        serialized, imports = serializer.serialize()
        self.assertTrue(serialized.startswith("syzygy.operations.AddField"))
        self.assertIn("import syzygy.operations", imports)


class PostAddFieldTests(OperationTestCase):
    def test_database_forwards(
        self, preserve_default=True
    ) -> Tuple[ProjectState, ProjectState]:
        model_name = "TestModel"
        field_name = "foo"
        field = models.IntegerField(default=42)
        from_state = self.apply_operations(
            [
                migrations.CreateModel(model_name, [("id", models.AutoField())]),
                AddField(
                    model_name, field_name, field, preserve_default=preserve_default
                ),
            ]
        )
        to_state = self.apply_operation(
            PostAddField(model_name, field_name, field), from_state.clone()
        )
        if not preserve_default:
            self.assertIs(
                NOT_PROVIDED,
                to_state.models["tests", model_name.lower()].fields[field_name].default,
            )
        with connection.cursor() as cursor:
            fields = connection.introspection.get_table_description(
                cursor, "tests_testmodel"
            )
        self.assertIsNone(fields[-1].default)
        return from_state, to_state

    def test_database_forwards_discard_default(self):
        self.test_database_forwards(preserve_default=False)

    def test_database_backwards(self, preserve_default=True):
        from_state, to_state = self.test_database_forwards(preserve_default)
        model_name = "TestModel"
        field_name = "foo"
        field = models.IntegerField(default=42)
        with connection.schema_editor() as schema_editor:
            PostAddField(model_name, field_name, field).database_backwards(
                "tests", schema_editor, to_state, from_state
            )
        if not preserve_default:
            self.assertIs(
                NOT_PROVIDED,
                from_state.models["tests", model_name.lower()]
                .fields[field_name]
                .default,
            )
        with connection.cursor() as cursor:
            fields = connection.introspection.get_table_description(
                cursor, "tests_testmodel"
            )
        self.assertEqual(int(fields[-1].default), 42)

    def test_database_backwards_discard_default(self):
        self.test_database_backwards(preserve_default=False)

    def test_stage(self):
        model_name = "TestModel"
        field_name = "foo"
        field = models.IntegerField(default=42)
        self.assertEqual(
            get_operation_stage(PostAddField(model_name, field_name, field)),
            Stage.POST_DEPLOY,
        )

    def test_migration_name_fragment(self):
        self.assertEqual(
            PostAddField(
                "TestModel", "foo", models.IntegerField(default=42)
            ).migration_name_fragment,
            "drop_db_default_testmodel_foo",
        )

    def test_describe(self):
        self.assertEqual(
            PostAddField(
                "TestModel", "foo", models.IntegerField(default=42)
            ).describe(),
            "Drop database DEFAULT of field foo on TestModel",
        )

    def test_deconstruct(self):
        model_name = "TestModel"
        field_name = "foo"
        field = models.IntegerField(default=42)
        operation = PostAddField(model_name, field_name, field)
        self.assertEqual(
            operation.deconstruct(),
            (
                "PostAddField",
                [],
                {"model_name": model_name, "name": field_name, "field": field},
            ),
        )
        serializer = OperationSerializer(operation)
        serialized, imports = serializer.serialize()
        self.assertTrue(serialized.startswith("syzygy.operations.PostAddField"))
        self.assertIn("import syzygy.operations", imports)

    def test_reduce(self):
        model_name = "TestModel"
        field_name = "foo"
        field = models.IntegerField(default=42)
        operations = [
            AddField(model_name, field_name, field),
            PostAddField(model_name, field_name, field),
        ]
        self.assert_optimizes_to(
            operations,
            [
                migrations.AddField(model_name, field_name, field),
            ],
        )


class PreRemoveFieldTests(OperationTestCase):
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
        self.assertEqual(pre_model.objects.get().foo, 42)

    def test_migration_name_fragment(self):
        self.assertEqual(
            PreRemoveField(
                "TestModel", "foo", models.IntegerField(default=42)
            ).migration_name_fragment,
            "set_db_default_testmodel_foo",
        )
        self.assertEqual(
            PreRemoveField(
                "TestModel", "foo", models.IntegerField()
            ).migration_name_fragment,
            "set_nullable_testmodel_foo",
        )

    def test_describe(self):
        self.assertEqual(
            PreRemoveField(
                "TestModel", "foo", models.IntegerField(default=42)
            ).describe(),
            "Set database DEFAULT of field foo on TestModel",
        )
        self.assertEqual(
            PreRemoveField("TestModel", "foo", models.IntegerField()).describe(),
            "Set field foo of TestModel NULLable",
        )

    def test_deconstruct(self):
        model_name = "TestModel"
        field_name = "foo"
        field = models.IntegerField(default=42)
        operation = PreRemoveField(
            model_name,
            field_name,
            field,
        )
        self.assertEqual(
            operation.deconstruct(),
            (
                "PreRemoveField",
                [],
                {"model_name": model_name, "name": field_name, "field": field},
            ),
        )
        serializer = OperationSerializer(operation)
        serialized, imports = serializer.serialize()
        self.assertTrue(serialized.startswith("syzygy.operations.PreRemoveField"))
        self.assertIn("import syzygy.operations", imports)

    def test_elidable(self):
        model_name = "TestModel"
        field_name = "foo"
        field = models.IntegerField(default=42)
        operations = [
            PreRemoveField(
                model_name,
                field_name,
                field,
            ),
            migrations.RemoveField(model_name, field_name, field),
        ]
        self.assert_optimizes_to(operations, [operations[-1]])
