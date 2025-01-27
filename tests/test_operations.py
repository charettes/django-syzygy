from typing import List, Optional, Tuple, TypeVar
from unittest import mock, skipUnless

from django.db import connection, migrations, models
from django.db.migrations.operations.base import Operation
from django.db.migrations.optimizer import MigrationOptimizer
from django.db.migrations.serializer import OperationSerializer
from django.db.migrations.state import ProjectState
from django.db.migrations.writer import OperationWriter
from django.db.models.fields import NOT_PROVIDED
from django.test import TestCase, TransactionTestCase

from syzygy.autodetector import MigrationAutodetector
from syzygy.compat import field_db_default_supported
from syzygy.constants import Stage
from syzygy.operations import (
    AliasModel,
    AlterField,
    RenameAliasedModel,
    RenameField,
    RenameModel,
    get_post_add_field_operation,
    get_pre_add_field_operation,
    get_pre_remove_field_operation,
)
from syzygy.plan import get_operation_stage

if connection.features.can_rollback_ddl:
    SchemaTestCase = TestCase
else:

    class SchemaTestCase(TransactionTestCase):
        @classmethod
        def setUpClass(cls):
            super().setUpClass()
            with connection.cursor() as cursor:
                cls.tables = {
                    table.name
                    for table in connection.introspection.get_table_list(cursor)
                }

        def tearDown(self):
            super().tearDown()
            with connection.cursor() as cursor:
                created_tables = [
                    (table_name, table.type == "v")
                    for table in connection.introspection.get_table_list(cursor)
                    if (table_name := table.name) not in self.tables
                ]
            if created_tables:
                for name, is_view in created_tables:
                    with connection.cursor() as cursor:
                        if is_view:
                            cursor.execute(f"DROP VIEW {name}")
                        else:
                            cursor.execute(f"DROP TABLE {name}")


O = TypeVar("O", bound=Operation)


class OperationTestCase(SchemaTestCase):
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

    def serde_roundtrip(self, operation: O) -> O:
        serialized, imports = OperationWriter(operation, indentation=0).serialize()
        locals = {}
        exec(
            "\n".join(list(imports) + [f"operation = {serialized[:-1]}"]),
            {},
            locals,
        )
        return locals["operation"]

    def assert_serde_roundtrip_equal(self, operation: Operation):
        self.assertEqual(
            self.serde_roundtrip(operation).deconstruct(), operation.deconstruct()
        )


class PreAddFieldTests(OperationTestCase):
    def test_database_forwards(self, preserve_default=True):
        model_name = "TestModel"
        field_name = "foo"
        field = models.IntegerField(default=42)
        state = self.apply_operation(
            migrations.CreateModel(model_name, [("id", models.AutoField())]),
        )
        pre_model = state.apps.get_model("tests", model_name)
        state = self.apply_operation(
            get_pre_add_field_operation(
                model_name, field_name, field, preserve_default=preserve_default
            ),
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
        operation = get_pre_add_field_operation(model_name, field_name, field)
        deconstructed = operation.deconstruct()
        if field_db_default_supported:
            self.assertEqual(
                operation.deconstruct(),
                (
                    "AddField",
                    [],
                    {"model_name": model_name, "name": field_name, "field": mock.ANY},
                ),
            )
            self.assertEqual(
                deconstructed[2]["field"].deconstruct(),
                (
                    None,
                    "django.db.models.IntegerField",
                    [],
                    {"default": 42, "db_default": 42},
                ),
            )
        else:
            self.assertEqual(
                deconstructed,
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
                get_pre_add_field_operation(
                    model_name, field_name, field, preserve_default=preserve_default
                ),
            ]
        )
        to_state = self.apply_operation(
            get_post_add_field_operation(
                model_name, field_name, field, preserve_default=preserve_default
            ),
            from_state.clone(),
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
            get_post_add_field_operation(
                model_name, field_name, field
            ).database_backwards("tests", schema_editor, to_state, from_state)
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
        for field in fields:
            if field.name == "foo":
                break
        else:
            self.fail('Could not find field "foo"')
        self.assertEqual(int(field.default), 42)

    def test_database_backwards_discard_default(self):
        self.test_database_backwards(preserve_default=False)

    def test_stage(self):
        model_name = "TestModel"
        field_name = "foo"
        field = models.IntegerField(default=42)
        self.assertEqual(
            get_operation_stage(
                get_post_add_field_operation(model_name, field_name, field)
            ),
            Stage.POST_DEPLOY,
        )

    def test_migration_name_fragment(self):
        self.assertEqual(
            get_post_add_field_operation(
                "TestModel", "foo", models.IntegerField(default=42)
            ).migration_name_fragment,
            "drop_db_default_testmodel_foo",
        )

    def test_describe(self):
        self.assertEqual(
            get_post_add_field_operation(
                "TestModel", "foo", models.IntegerField(default=42)
            ).describe(),
            "Drop database DEFAULT of field foo on TestModel",
        )

    def test_deconstruct(self):
        model_name = "TestModel"
        field_name = "foo"
        field = models.IntegerField(default=42)
        operation = get_post_add_field_operation(model_name, field_name, field)
        deconstructed = operation.deconstruct()
        if field_db_default_supported:
            self.assertEqual(
                deconstructed,
                (
                    "AlterField",
                    [],
                    {
                        "model_name": model_name,
                        "name": field_name,
                        "field": mock.ANY,
                        "stage": Stage.POST_DEPLOY,
                    },
                ),
            )
            self.assertEqual(
                deconstructed[2]["field"].deconstruct(),
                (
                    None,
                    "django.db.models.IntegerField",
                    [],
                    {"default": 42},
                ),
            )
        else:
            self.assertEqual(
                deconstructed,
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
            get_pre_add_field_operation(model_name, field_name, field),
            get_post_add_field_operation(model_name, field_name, field),
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
            get_pre_remove_field_operation(
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
            get_pre_remove_field_operation(
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
            get_pre_remove_field_operation(
                "TestModel", "foo", models.IntegerField(default=42)
            ).migration_name_fragment,
            "set_db_default_testmodel_foo",
        )
        self.assertEqual(
            get_pre_remove_field_operation(
                "TestModel", "foo", models.IntegerField()
            ).migration_name_fragment,
            "set_nullable_testmodel_foo",
        )

    def test_describe(self):
        self.assertEqual(
            get_pre_remove_field_operation(
                "TestModel", "foo", models.IntegerField(default=42)
            ).describe(),
            "Set database DEFAULT of field foo on TestModel",
        )
        self.assertEqual(
            get_pre_remove_field_operation(
                "TestModel", "foo", models.IntegerField()
            ).describe(),
            "Set field foo of TestModel NULLable",
        )

    def test_deconstruct(self):
        model_name = "TestModel"
        field_name = "foo"
        field = models.IntegerField(default=42)
        operation = get_pre_remove_field_operation(
            model_name,
            field_name,
            field,
        )
        deconstructed = operation.deconstruct()
        if field_db_default_supported:
            self.assertEqual(
                deconstructed,
                (
                    "AlterField",
                    [],
                    {"model_name": model_name, "name": field_name, "field": mock.ANY},
                ),
            )
            self.assertEqual(
                deconstructed[2]["field"].deconstruct(),
                (
                    None,
                    "django.db.models.IntegerField",
                    [],
                    {"default": 42, "db_default": 42},
                ),
            )
        else:
            self.assertEqual(
                deconstructed,
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
            get_pre_remove_field_operation(
                model_name,
                field_name,
                field,
            ),
            migrations.RemoveField(model_name, field_name, field),
        ]
        self.assert_optimizes_to(operations, [operations[-1]])

    @skipUnless(field_db_default_supported, "Field.db_default not supported")
    def test_defined_db_default(self):
        with self.assertRaisesMessage(
            ValueError,
            "Fields with a db_default don't require a pre-deployment operation.",
        ):
            get_pre_remove_field_operation(
                "model", "field", models.IntegerField(db_default=42)
            )


class RenameFieldTests(OperationTestCase):
    def test_serialization(self):
        self.assert_serde_roundtrip_equal(
            RenameField("model", "old_field", "new_field", stage=Stage.POST_DEPLOY)
        )


class RenameModelTests(OperationTestCase):
    def test_serialization(self):
        self.assert_serde_roundtrip_equal(
            RenameModel("old_name", "new_name", stage=Stage.POST_DEPLOY)
        )


class AlterFieldTests(OperationTestCase):
    def test_serialization(self):
        operation = self.serde_roundtrip(
            AlterField(
                "model",
                "field",
                models.IntegerField(),
                Stage.PRE_DEPLOY,
            )
        )
        self.assertEqual(operation.model_name, "model")
        self.assertEqual(operation.name, "field")
        self.assertEqual(
            operation.field.deconstruct(), models.IntegerField().deconstruct()
        )
        self.assertEqual(operation.stage, Stage.PRE_DEPLOY)


class AliasModelTests(OperationTestCase):
    def test_describe(self):
        self.assertEqual(
            AliasModel("OldName", "NewName").describe(),
            "Alias model OldName to NewName",
        )

    def _apply_forwards(self):
        model_name = "TestModel"
        field = models.IntegerField()
        pre_state = self.apply_operations(
            [
                migrations.CreateModel(model_name, [("foo", field)]),
            ]
        )
        new_model_name = "NewTestModel"
        post_state = self.apply_operations(
            [
                AliasModel(model_name, new_model_name),
            ],
            pre_state,
        )
        return (pre_state, model_name), (post_state, new_model_name)

    def test_database_forwards(self):
        (pre_state, _), (post_state, new_model_name) = self._apply_forwards()
        pre_model = pre_state.apps.get_model("tests", "testmodel")
        pre_obj = pre_model.objects.create(foo=1)
        self.assertEqual(pre_model.objects.get(), pre_obj)
        post_model = post_state.apps.get_model("tests", new_model_name)
        self.assertEqual(post_model.objects.get().pk, pre_obj.pk)
        pre_model.objects.all().delete()
        post_obj = post_model.objects.create(foo=2)
        # XXX: Does that make the option non-viable on SQLite?
        if connection.vendor == "sqlite":
            # SQLite doesn't allow the usage of RETURNING in INSTEAD OF INSERT
            # triggers and thus the object has to be re-fetched.
            post_obj = post_model.objects.latest("pk")
        self.assertEqual(post_model.objects.get(), post_obj)
        self.assertEqual(pre_model.objects.get().pk, post_obj.pk)
        pre_model.objects.update(foo=3)
        self.assertEqual(post_model.objects.get().foo, 3)

    def test_database_backwards(self):
        (pre_state, model_name), (post_state, new_model_name) = self._apply_forwards()
        with connection.schema_editor() as schema_editor:
            AliasModel(model_name, new_model_name).database_backwards(
                "tests", schema_editor, post_state, pre_state
            )

    def test_elidable(self):
        model_name = "TestModel"
        new_model_name = "NewTestModel"
        operations = [
            AliasModel(
                model_name,
                new_model_name,
            ),
            RenameAliasedModel(model_name, new_model_name),
        ]
        self.assert_optimizes_to(
            operations, [migrations.RenameModel(model_name, new_model_name)]
        )
