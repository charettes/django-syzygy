from django.conf import settings
from django.db.migrations import CreateModel, DeleteModel, Migration
from django.db.migrations.operations.base import Operation
from django.db.migrations.operations.fields import RemoveField
from django.test import SimpleTestCase

from syzygy.constants import Stage
from syzygy.plan import (
    get_migration_stage,
    get_operation_stage,
    get_pre_deploy_plan,
    must_post_deploy_migration,
)


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


class GetMigrationStageTests(SimpleTestCase):
    def setUp(self):
        self.migration = Migration(app_label="tests", name="migration")

    def test_stage_setting(self):
        with self.settings():
            del settings.MIGRATION_STAGES
            self.assertIsNone(get_migration_stage(self.migration))

        for stage in Stage:
            with self.subTest(stage=stage), self.settings(
                MIGRATION_STAGES={"tests.migration": stage}
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
        with self.assertRaises(ValueError):
            get_migration_stage(self.migration)


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
        with self.assertRaises(ValueError):
            must_post_deploy_migration(self.migration)


class GetPreDeployPlanTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pre_deploy = Migration(app_label="tests", name="0001")
        cls.pre_deploy.stage = Stage.PRE_DEPLOY
        cls.post_deploy = Migration(app_label="tests", name="0002")
        cls.post_deploy.stage = Stage.POST_DEPLOY

    def test_forward(self):
        plan = [(self.pre_deploy, False), (self.post_deploy, False)]
        self.assertEqual(get_pre_deploy_plan(plan), [(self.pre_deploy, False)])

    def test_backward(self):
        plan = [(self.post_deploy, True), (self.pre_deploy, True)]
        self.assertEqual(get_pre_deploy_plan(plan), [(self.post_deploy, True)])

    def test_non_contiguous(self):
        plan = [
            (self.pre_deploy, False),
            (self.post_deploy, False),
            (self.pre_deploy, False),
        ]
        with self.assertRaises(ValueError):
            get_pre_deploy_plan(plan)
