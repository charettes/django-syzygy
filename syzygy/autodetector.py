import itertools

import django
from django.db.migrations import operations
from django.db.migrations.autodetector import (
    MigrationAutodetector as _MigrationAutodetector,
)
from django.db.migrations.operations.base import Operation
from django.db.models.fields import NOT_PROVIDED

from .operations import AddField, PostAddField, PreRemoveField
from .plan import partition_operations


class Stage(Operation):
    """
    Fake operation that servers as a placeholder to break operations into
    multiple migrations.
    """

    def __repr__(self):
        return f"<Stage {id(self)}>"


class MigrationAutodetector(_MigrationAutodetector):
    """
    Migration auto-detector that splits migrations containing sequence of
    operations incompatible with staged deployments.

    It works by inserting fake `Stage` operations into a fake __stage__
    application since `_build_migration_list` will only split operations of a
    single application into multiple migrations if it has external
    dependencies.

    By creating a chain of external application dependencies between operations::

        app.FirstOperation -> __stage__.Stage -> app.SecondOperation

    The auto-detector will generate a sequence of migrations of the form::

        app.Migration1(operations=[FirstOperation])
        __stage__.Migration1(operations=[Stage])
        app.Migration2(operations=[FirstOperation])

    And automatically remove the __stage__ migrations since it's a not
    an existing application.
    """

    STAGE_SPLIT = "__stage__"

    def _generate_added_field(self, app_label, model_name, field_name):
        super()._generate_added_field(app_label, model_name, field_name)
        add_field = self.generated_operations[app_label][-1]
        add_field.__class__ = AddField
        stage = Stage()
        self.add_operation(
            self.STAGE_SPLIT,
            stage,
            dependencies=[(app_label, self.STAGE_SPLIT, add_field)],
        )
        self.add_operation(
            app_label,
            PostAddField(model_name=model_name, name=field_name, field=add_field.field),
            dependencies=[
                (self.STAGE_SPLIT, stage),
            ],
        )

    def _generate_removed_field(self, app_label, model_name, field_name):
        if django.VERSION >= (3, 1):
            field = self.from_state.models[app_label, model_name].fields[field_name]
        else:
            for fname, field in self.from_state.models[app_label, model_name].fields:
                if fname == field_name:
                    break
        if field.default is NOT_PROVIDED and field.null:
            return super()._generate_removed_field(app_label, model_name, field_name)
        self.add_operation(
            app_label,
            PreRemoveField(model_name=model_name, name=field_name, field=field),
        )
        stage = Stage()
        self.add_operation(
            self.STAGE_SPLIT,
            stage,
            dependencies=[
                (app_label, self.STAGE_SPLIT, self.generated_operations[app_label][-1])
            ],
        )
        self.add_operation(
            app_label,
            operations.RemoveField(model_name=model_name, name=field_name),
            dependencies=[
                (app_label, model_name, field_name, "order_wrt_unset"),
                (app_label, model_name, field_name, "foo_together_change"),
                (self.STAGE_SPLIT, stage),
            ],
        )

    def check_dependency(self, operation, dependency):
        # Stage dependency on a previous operation.
        if dependency[1] == self.STAGE_SPLIT:
            return dependency[2] is operation
        # Dependency on a stage.
        if dependency[0] == self.STAGE_SPLIT:
            return dependency[1] is operation
        return super().check_dependency(operation, dependency)

    def _build_migration_list(self, *args, **kwargs):
        # Ensure generated operations sequence for each apps are partitioned
        # by stage.
        for app_label, app_operations in list(self.generated_operations.items()):
            if app_label == self.STAGE_SPLIT:
                continue
            pre_operations, post_operations = partition_operations(app_operations)
            if pre_operations and post_operations:
                stage = Stage()
                self.add_operation(
                    self.STAGE_SPLIT,
                    stage,
                    dependencies=[(app_label, self.STAGE_SPLIT, pre_operations[-1])],
                )
                post_operations[0]._auto_deps.append((self.STAGE_SPLIT, stage))
        super()._build_migration_list(*args, **kwargs)
        # Remove all dangling references to stage migrations.
        if self.migrations.pop(self.STAGE_SPLIT, None):
            for migration in itertools.chain.from_iterable(self.migrations.values()):
                migration.dependencies = [
                    dependency
                    for dependency in migration.dependencies
                    if dependency[0] != self.STAGE_SPLIT
                ]
