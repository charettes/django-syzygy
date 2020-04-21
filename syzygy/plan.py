from typing import Dict, List, Optional, Tuple

from django.conf import settings
from django.db.migrations import DeleteModel, Migration, RemoveField
from django.db.migrations.operations.base import Operation

from .constants import Stage

MigrationStagesSetting = Dict[str, Stage]
Plan = List[Tuple[Migration, bool]]


def get_operation_stage(operation: Operation) -> Stage:
    """Return the heuristically determined `Stage` of the operation."""
    if isinstance(operation, (DeleteModel, RemoveField)):
        return Stage.POST_DEPLOY
    return Stage.PRE_DEPLOY


def _get_configured_migration_stage(migration: Migration) -> Optional[Stage]:
    """Return the `Stage` configured through setting:`MIGRATION_STAGES` of the migration."""
    setting: MigrationStagesSetting = getattr(settings, "MIGRATION_STAGES", None)
    if setting is None:
        return
    return setting.get(f"{migration.app_label}.{migration.name}")


def get_migration_stage(migration: Migration) -> Optional[Stage]:
    """
    Return the `Stage` of the migration.

    If not specified through setting:`MIGRATION_STAGES` or a `stage`
    :class:`django.db.migrations.Migration` class attribute it will be
    tentatively deduced from its list of
    attr:`django.db.migrations.Migration.operations`.

    If the migration doesn't have any `operations` then `None` will be returned
    and a `ValueError` will be raised if its contains operations of different
    stages.
    """
    stage = getattr(migration, "stage", None) or _get_configured_migration_stage(
        migration
    )
    if stage is not None:
        return stage
    for operation in migration.operations:
        operation_stage = get_operation_stage(operation)
        if stage is None:
            stage = operation_stage
        elif operation_stage != stage:
            raise ValueError(f"Cannot automatically determine stage of {migration}.")
    return stage


def must_post_deploy_migration(
    migration: Migration, backward: bool = False
) -> Optional[bool]:
    """
    Return whether or not migration must be run after deployment.

    If not specified through a `stage` :class:`django.db.migrations.Migration`
    class attribute it will be tentatively deduced from its list of
    attr:`django.db.migrations.Migration.operations`.

    In cases of ambiguity a `ValueError` will be raised.
    """
    migration_stage = get_migration_stage(migration)
    if migration_stage is None:
        return None
    if migration_stage is Stage.PRE_DEPLOY:
        return backward
    return not backward


def get_pre_deploy_plan(plan: Plan) -> Plan:
    """
    Trim provided plan to its leading contiguous pre-deployment sequence.

    If the plan contains non-contiguous sequence of pre-deployment migrations
    or migrations with ambiguous deploy stage a `ValueError` is raised.
    """
    pre_deploy_plan: Plan = []
    post_deploy = False
    for migration, backward in plan:
        if must_post_deploy_migration(migration, backward):
            post_deploy = True
        else:
            if post_deploy:
                raise ValueError(
                    "Plan contains a non-contiguous sequence of pre-deployment "
                    "migrations."
                )
            pre_deploy_plan.append((migration, backward))
    return pre_deploy_plan
