import itertools
import sys
from typing import NamedTuple

from django.db.migrations import operations
from django.db.migrations.autodetector import (
    MigrationAutodetector as _MigrationAutodetector,
)
from django.db.migrations.operations.base import Operation
from django.db.migrations.questioner import InteractiveMigrationQuestioner
from django.db.models.fields import NOT_PROVIDED
from django.utils.functional import cached_property

from .compat import OperationDependency
from .constants import Stage
from .exceptions import AmbiguousStage
from .operations import (
    AlterField,
    RenameField,
    RenameModel,
    get_post_add_field_operation,
    get_pre_add_field_operation,
    get_pre_remove_field_operation,
)
from .plan import partition_operations

STAGE_SPLIT = "__stage__"


class OperationStage(Operation):
    """
    Fake operation that serves as a placeholder to break operations into
    multiple migrations.
    """


class StageDependency(NamedTuple):
    app_label: str
    operation: OperationStage


class StagedOperationDependency(NamedTuple):
    app_label: str
    model_name: str
    operation: Operation


class MigrationAutodetector(_MigrationAutodetector):
    """
    Migration auto-detector that splits migrations containing sequence of
    operations incompatible with staged deployments.

    It works by inserting fake `Stage` operations into a fake __stage__
    application since `_build_migration_list` will only split operations of a
    single application into multiple migrations if it has external
    dependencies.

    By creating a chain of external application dependencies between operations::

        app.FirstOperation -> __stage__.OperationStage -> app.SecondOperation

    The auto-detector will generate a sequence of migrations of the form::

        app.Migration1(operations=[FirstOperation])
        __stage__.Migration1(operations=[OperationStage])
        app.Migration2(operations=[FirstOperation])

    And automatically remove the __stage__ migrations since it's a not
    an existing application.
    """

    def __init__(self, *args, **kwargs):
        self.style = kwargs.pop("style", None)
        super().__init__(*args, **kwargs)

    @cached_property
    def has_interactive_questionner(self) -> bool:
        return not self.questioner.dry_run and isinstance(
            self.questioner, InteractiveMigrationQuestioner
        )

    def add_operation(self, app_label, operation, dependencies=None, beginning=False):
        if isinstance(operation, operations.RenameField):
            print(
                self.style.WARNING(
                    "Renaming a column from a database table actively relied upon might cause downtime "
                    "during deployment.",
                ),
                file=sys.stderr,
            )
            choice = self.questioner.defaults.get("ask_rename_field_stage", 1)
            if self.has_interactive_questionner:
                choice = self.questioner._choice_input(
                    "Please choose an appropriate action to take:",
                    [
                        (
                            f"Quit, and let me add a new {operation.model_name}.{operation.new_name} field meant "
                            f"to be backfilled with {operation.model_name}.{operation.old_name} values"
                        ),
                        (
                            f"Assume the currently deployed code doesn't reference {app_label}.{operation.model_name} "
                            f"on reachable code paths and mark the operation to be applied before deployment. "
                            + self.style.MIGRATE_LABEL(
                                "This might cause downtime if your assumption is wrong",
                            )
                        ),
                        (
                            f"Assume the newly deployed code doesn't reference {app_label}.{operation.model_name} on "
                            "reachable code paths and mark the operation to be applied after deployment. "
                            + self.style.MIGRATE_LABEL(
                                "This might cause downtime if your assumption is wrong",
                            )
                        ),
                    ],
                )
            if choice == 1:
                sys.exit(3)
            else:
                stage = Stage.PRE_DEPLOY if choice == 2 else Stage.POST_DEPLOY
                operation = RenameField.for_stage(operation, stage)
        if isinstance(operation, operations.RenameModel):
            from_db_table = (
                self.from_state.models[app_label, operation.old_name_lower].options.get(
                    "db_table"
                )
                or f"{app_label}_{operation.old_name_lower}"
            )
            to_db_table = self.to_state.models[
                app_label, operation.new_name_lower
            ].options.get("db_table")
            if from_db_table != to_db_table:
                print(
                    self.style.WARNING(
                        "Renaming an actively relied on database table might cause downtime during deployment."
                    ),
                    file=sys.stderr,
                )
                choice = self.questioner.defaults.get("ask_rename_model_stage", 1)
                if self.has_interactive_questionner:
                    choice = self.questioner._choice_input(
                        "Please choose an appropriate action to take:",
                        [
                            (
                                f"Quit, and let me manually set {app_label}.{operation.new_name}.Meta.db_table to "
                                f'"{from_db_table}" to avoid renaming its underlying table'
                            ),
                            (
                                f"Assume the currently deployed code doesn't reference "
                                f"{app_label}.{operation.old_name} on reachable code paths and mark the operation to "
                                "be applied before the deployment. "
                                + self.style.MIGRATE_LABEL(
                                    "This might cause downtime if your assumption is wrong",
                                )
                            ),
                            (
                                f"Assume the newly deployed code doesn't reference {app_label}.{operation.new_name} "
                                "on reachable code paths and mark the operation to be applied after the deployment. "
                                + self.style.MIGRATE_LABEL(
                                    "This might cause downtime if your assumption is wrong",
                                )
                            ),
                        ],
                    )
                if choice == 1:
                    sys.exit(3)
                else:
                    stage = Stage.PRE_DEPLOY if choice == 2 else Stage.POST_DEPLOY
                    operation = RenameModel.for_stage(operation, stage)
        elif isinstance(operation, operations.AlterField) and not operation.field.null:
            # Addition of not-NULL constraints must be performed post-deployment.
            from_field = self.from_state.models[
                app_label, operation.model_name_lower
            ].fields[operation.name]
            if from_field.null:
                operation = AlterField.for_stage(operation, Stage.POST_DEPLOY)
        super().add_operation(app_label, operation, dependencies, beginning)

    def _generate_added_field(self, app_label, model_name, field_name):
        # Delegate most of the logic to super() ...
        super()._generate_added_field(app_label, model_name, field_name)
        old_add_field = self.generated_operations[app_label][-1]
        field = old_add_field.field
        if (
            field.many_to_many
            or (field.null and not field.has_default())
            or getattr(field, "db_default", NOT_PROVIDED) is not NOT_PROVIDED
        ):
            return
        # ... otherwise swap the added operation by an adjusted one.
        add_field = get_pre_add_field_operation(
            old_add_field.model_name,
            old_add_field.name,
            old_add_field.field,
            preserve_default=old_add_field.preserve_default,
        )
        add_field._auto_deps = old_add_field._auto_deps
        self.generated_operations[app_label][-1] = add_field
        stage = OperationStage()
        self.add_operation(
            STAGE_SPLIT,
            stage,
            dependencies=[StagedOperationDependency(app_label, STAGE_SPLIT, add_field)],
        )
        post_add_field = get_post_add_field_operation(
            model_name=model_name,
            name=field_name,
            field=field,
            preserve_default=add_field.preserve_default,
        )
        super().add_operation(
            app_label,
            post_add_field,
            dependencies=[
                StageDependency(STAGE_SPLIT, stage),
            ],
        )

    def _generate_removed_field(self, app_label, model_name, field_name):
        field = self.from_state.models[app_label, model_name].fields[field_name]
        remove_default = field.default
        if (
            # Nullable fields will use null if not specified.
            (remove_default is NOT_PROVIDED and field.null)
            # Fields with a db_default will use the value if not specified.
            or getattr(field, "db_default", NOT_PROVIDED) is not NOT_PROVIDED
            # Many-to-many fields are not backend by concrete columns.
            or field.many_to_many
        ):
            return super()._generate_removed_field(app_label, model_name, field_name)

        if remove_default is NOT_PROVIDED:
            if self.has_interactive_questionner:
                choice = self.questioner._choice_input(
                    "You are trying to remove a non-nullable field '%s' from %s without a default; "
                    "we can't do that (the database needs a default for inserts before the removal).\n"
                    "Please select a fix:" % (field_name, model_name),
                    [
                        (
                            "Provide a one-off default now (will be set at the "
                            "database level in pre-deployment stage)"
                        ),
                        (
                            "Make the field temporarily nullable (attempts at reverting the "
                            "field removal might fail)"
                        ),
                    ],
                )
                if choice == 1:
                    remove_default = self.questioner._ask_default()
                elif choice == 2:
                    remove_default = None
                else:
                    sys.exit(3)
            else:
                remove_default = self.questioner.defaults.get("ask_remove_default")
            if remove_default is not NOT_PROVIDED:
                field = field.clone()
                if remove_default is None:
                    field.null = True
                else:
                    field.default = remove_default
        pre_remove_field = get_pre_remove_field_operation(
            model_name=model_name, name=field_name, field=field
        )
        self.add_operation(app_label, pre_remove_field)
        stage = OperationStage()
        self.add_operation(
            STAGE_SPLIT,
            stage,
            dependencies=[
                StagedOperationDependency(
                    app_label, STAGE_SPLIT, self.generated_operations[app_label][-1]
                ),
            ],
        )
        self.add_operation(
            app_label,
            operations.RemoveField(model_name=model_name, name=field_name),
            dependencies=[
                OperationDependency(
                    app_label,
                    model_name,
                    field_name,
                    OperationDependency.Type.REMOVE_ORDER_WRT,
                ),
                OperationDependency(
                    app_label,
                    model_name,
                    field_name,
                    OperationDependency.Type.ALTER_FOO_TOGETHER,
                ),
                StageDependency(STAGE_SPLIT, stage),
            ],
        )

    def check_dependency(self, operation, dependency):
        if isinstance(dependency, (StageDependency, StagedOperationDependency)):
            return dependency.operation is operation
        return super().check_dependency(operation, dependency)

    def _build_migration_list(self, *args, **kwargs):
        # Ensure generated operations sequence for each apps are partitioned
        # by stage.
        for app_label, app_operations in list(self.generated_operations.items()):
            if app_label == STAGE_SPLIT:
                continue
            try:
                pre_operations, post_operations = partition_operations(
                    app_operations, app_label
                )
            except AmbiguousStage:
                operations_description = "".join(
                    f"- {operation.describe()} \n" for operation in app_operations
                )
                print(
                    f'The auto-detected operations for the "{app_label}" '
                    "app cannot be partitioned into deployment stages:\n"
                    f"{operations_description}",
                    file=sys.stderr,
                )
                if self.has_interactive_questionner:
                    abort = (
                        self.questioner._choice_input(
                            "",
                            [
                                (
                                    "Let `makemigrations` complete. You'll have to "
                                    "manually break you operations in migrations "
                                    "with non-ambiguous stages."
                                ),
                                (
                                    "Abort `makemigrations`. You'll have to reduce "
                                    "the number of model changes before running "
                                    "`makemigrations` again."
                                ),
                            ],
                        )
                        == 2
                    )
                else:
                    abort = self.questioner.defaults.get("ask_ambiguous_abort", False)
                if abort:
                    sys.exit(3)
                continue
            if pre_operations and post_operations:
                stage = OperationStage()
                self.add_operation(
                    STAGE_SPLIT,
                    stage,
                    dependencies=[
                        StagedOperationDependency(
                            app_label, STAGE_SPLIT, pre_operations[-1]
                        )
                    ],
                )
                post_operations[0]._auto_deps.append(
                    StageDependency(STAGE_SPLIT, stage)
                )
                # Assign updated operations as they might have be re-ordered by
                # `partition_operations`.
                self.generated_operations[app_label] = pre_operations + post_operations
        super()._build_migration_list(*args, **kwargs)
        # Remove all dangling references to stage migrations.
        if self.migrations.pop(STAGE_SPLIT, None):
            for migration in itertools.chain.from_iterable(self.migrations.values()):
                migration.dependencies = [
                    dependency
                    for dependency in migration.dependencies
                    if dependency[0] != STAGE_SPLIT
                ]
