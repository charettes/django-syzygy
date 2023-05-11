from itertools import product

from django.conf import settings
from django.db.migrations import CreateModel, DeleteModel, Migration
from django.db.migrations.operations.base import Operation
from django.db.migrations.operations.fields import RemoveField
from django.test import SimpleTestCase

from syzygy.constants import Stage
from syzygy.exceptions import AmbiguousPlan, AmbiguousStage
from syzygy.plan import (
    get_migration_stage,
    get_operation_stage,
    get_pre_deploy_plan,
    hash_plan,
    must_post_deploy_migration,
    partition_operations,
)


class HashPlanTests(SimpleTestCase):
    def test_stable(self):
        plan = [(Migration("0001_initial", "tests"), True)]
        self.assertEqual(hash_plan(plan), "a4a35230c7d1942265f1bc8f9ce53e05a50848be")

    def test_order(self):
        first = (Migration("0001_initial", "tests"), True)
        second = (Migration("0002_second", "tests"), True)
        self.assertNotEqual(hash_plan([first, second]), hash_plan([second, first]))

    def test_backward(self):
        forward = (Migration("0001_initial", "tests"), True)
        backward = (Migration("0001_initial", "tests"), False)
        self.assertNotEqual(hash_plan([forward]), hash_plan([backward]))

    def test_migration_name(self):
        first = (Migration("0001_initial", "tests"), True)
        second = (Migration("0002_second", "tests"), True)
        self.assertNotEqual(hash_plan([first]), hash_plan([second]))

    def test_app_label(self):
        test_app = (Migration("0001_initial", "tests"), True)
        other_app = (Migration("0001_initial", "other"), True)
        self.assertNotEqual(hash_plan([test_app]), hash_plan([other_app]))


class GetOperationStageTests(SimpleTestCase):
    def test_pre_deploy_operations(self):
        pre_deploy_operation = Operation()
        pre_deploy_operation.stage = Stage.PRE_DEPLOY
        operations = [CreateModel("model", []), pre_deploy_operation]
        for operation in operations:
            with self.subTest(operation=operation):
                self.assertIs(get_operation_stage(operation), Stage.PRE_DEPLOY)

    def test_post_deploy_operations(self):
        post_deploy_operation = Operation()
        post_deploy_operation.stage = Stage.POST_DEPLOY
        operations = [
            DeleteModel("model"),
            RemoveField("model", "field"),
            post_deploy_operation,
        ]
        for operation in operations:
            with self.subTest(operation=operation):
                self.assertIs(get_operation_stage(operation), Stage.POST_DEPLOY)


class PartitionOperationsTests(SimpleTestCase):
    pre_deploy_operations = [
        CreateModel("model", []),
    ]
    post_deploy_operations = [
        DeleteModel("model"),
    ]

    def test_empty(self):
        self.assertEqual(partition_operations([], "migrations"), ([], []))

    def test_pre_deploy_only(self):
        self.assertEqual(
            partition_operations(self.pre_deploy_operations, "migrations"),
            (self.pre_deploy_operations, []),
        )

    def test_post_deploy_only(self):
        self.assertEqual(
            partition_operations(self.post_deploy_operations, "migrations"),
            ([], self.post_deploy_operations),
        )

    def test_mixed(self):
        self.assertEqual(
            partition_operations(
                self.pre_deploy_operations + self.post_deploy_operations, "migrations"
            ),
            (self.pre_deploy_operations, self.post_deploy_operations),
        )

    def test_mixed_reorder(self):
        post_deploy_operations = [DeleteModel("other")]
        self.assertEqual(
            partition_operations(
                post_deploy_operations + self.pre_deploy_operations, "migrations"
            ),
            (self.pre_deploy_operations, post_deploy_operations),
        )

    def test_ambiguous(self):
        with self.assertRaises(AmbiguousStage):
            partition_operations(
                self.post_deploy_operations + self.pre_deploy_operations, "migrations"
            )


class GetMigrationStageTests(SimpleTestCase):
    def setUp(self):
        self.migration = Migration(app_label="tests", name="migration")

    def test_stage_override_setting(self):
        with self.settings():
            del settings.MIGRATION_STAGES_OVERRIDE
            self.assertIsNone(get_migration_stage(self.migration))

        overrides = ["tests.migration", "tests"]
        for stage, override in product(Stage, overrides):
            with self.subTest(stage=stage, override=override), self.settings(
                MIGRATION_STAGES_OVERRIDE={override: stage}
            ):
                self.assertIs(get_migration_stage(self.migration), stage)

    def test_stage_attribute(self):
        for stage in Stage:
            with self.subTest(stage=stage):
                self.migration.stage = stage
                self.assertIs(get_migration_stage(self.migration), stage)

    def test_operations_stages(self):
        self.assertIsNone(get_migration_stage(self.migration))

        self.migration.operations = [CreateModel("model", [])]
        self.assertEqual(get_migration_stage(self.migration), Stage.PRE_DEPLOY)

        self.migration.operations = [
            DeleteModel("model"),
            RemoveField("model", "field"),
        ]
        self.assertEqual(get_migration_stage(self.migration), Stage.POST_DEPLOY)

    def test_ambiguous_operations(self):
        self.migration.operations = [CreateModel("model", []), DeleteModel("model")]
        with self.assertRaises(AmbiguousStage):
            get_migration_stage(self.migration)

    def test_stage_fallback_setting(self):
        self.migration.operations = [CreateModel("model", []), DeleteModel("model")]
        with self.assertRaises(AmbiguousStage):
            get_migration_stage(self.migration)

        overrides = ["tests.migration", "tests"]
        for stage, override in product(Stage, overrides):
            with self.subTest(stage=stage, override=override), self.settings(
                MIGRATION_STAGES_FALLBACK={override: stage}
            ):
                self.assertIs(get_migration_stage(self.migration), stage)


class MustPostDeployMigrationTests(SimpleTestCase):
    def setUp(self):
        self.migration = Migration(app_label="tests", name="migration")

    def test_forward(self):
        self.assertIsNone(must_post_deploy_migration(self.migration))
        self.migration.stage = Stage.PRE_DEPLOY
        self.assertIs(must_post_deploy_migration(self.migration), False)
        self.migration.stage = Stage.POST_DEPLOY
        self.assertIs(must_post_deploy_migration(self.migration), True)

    def test_backward(self):
        self.migration.stage = Stage.PRE_DEPLOY
        self.assertIs(must_post_deploy_migration(self.migration, True), True)
        self.migration.stage = Stage.POST_DEPLOY
        self.assertIs(must_post_deploy_migration(self.migration, True), False)

    def test_ambiguous_operations(self):
        self.migration.operations = [CreateModel("model", []), DeleteModel("model")]
        with self.assertRaises(AmbiguousStage):
            must_post_deploy_migration(self.migration)


class GetPreDeployPlanTests(SimpleTestCase):
    def setUp(self):
        self.pre_deploy = Migration(app_label="tests", name="0001")
        self.pre_deploy.stage = Stage.PRE_DEPLOY
        self.post_deploy = Migration(app_label="tests", name="0002")
        self.post_deploy.dependencies = [("tests", "0001")]
        self.post_deploy.stage = Stage.POST_DEPLOY

    def test_forward(self):
        plan = [(self.pre_deploy, False), (self.post_deploy, False)]
        self.assertEqual(get_pre_deploy_plan(plan), [(self.pre_deploy, False)])

    def test_backward(self):
        plan = [(self.post_deploy, True), (self.pre_deploy, True)]
        self.assertEqual(get_pre_deploy_plan(plan), [(self.post_deploy, True)])

    def test_non_contiguous_free(self):
        post_deploy_free = Migration(app_label="other", name="0001")
        post_deploy_free.stage = Stage.POST_DEPLOY
        plan = [
            (post_deploy_free, False),
            (self.pre_deploy, False),
            (self.post_deploy, False),
        ]
        self.assertEqual(get_pre_deploy_plan(plan), [(self.pre_deploy, False)])

    def test_non_contiguous_free_backward(self):
        pre_deploy_free = Migration(app_label="other", name="0001")
        pre_deploy_free.stage = Stage.PRE_DEPLOY
        plan = [
            (pre_deploy_free, True),
            (self.post_deploy, True),
            (self.pre_deploy, True),
        ]
        self.assertEqual(get_pre_deploy_plan(plan), [(self.post_deploy, True)])

    def test_non_contiguous_deps(self):
        pre_deploy_dep = Migration(app_label="other", name="0001")
        pre_deploy_dep.stage = Stage.PRE_DEPLOY
        pre_deploy_dep.dependencies = [("tests", "0002")]
        plan = [
            (self.pre_deploy, False),
            (self.post_deploy, False),
            (pre_deploy_dep, False),
        ]
        msg = (
            "Plan contains a non-contiguous sequence of pre-deployment migrations. "
            "Migration other.0001 is defined to be applied pre-deployment but it "
            "depends on tests.0002 which is defined to be applied post-deployment."
        )
        with self.assertRaisesMessage(AmbiguousPlan, msg):
            get_pre_deploy_plan(plan)
        del pre_deploy_dep.stage
        pre_deploy_dep.operations = [
            CreateModel("model", []),
        ]
        msg = (
            "Plan contains a non-contiguous sequence of pre-deployment migrations. "
            "Migration other.0001 is inferred to be applied pre-deployment but it "
            "depends on tests.0002 which is defined to be applied post-deployment. "
            "Definining an explicit `Migration.stage: syzygy.Stage` for other.0001 "
            "to bypass inferrence might help."
        )
        with self.assertRaisesMessage(AmbiguousPlan, msg):
            get_pre_deploy_plan(plan)
        del self.post_deploy.stage
        self.post_deploy.operations = [
            DeleteModel("model"),
        ]
        msg = (
            "Plan contains a non-contiguous sequence of pre-deployment migrations. "
            "Migration other.0001 is inferred to be applied pre-deployment but it "
            "depends on tests.0002 which is inferred to be applied post-deployment. "
            "Definining an explicit `Migration.stage: syzygy.Stage` for other.0001 "
            "or tests.0002 to bypass inferrence might help."
        )
        with self.assertRaisesMessage(AmbiguousPlan, msg):
            get_pre_deploy_plan(plan)
