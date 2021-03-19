import hashlib
from typing import Dict, List, Optional, Tuple

from django.db.migrations import DeleteModel, Migration, RemoveField
from django.db.migrations.operations.base import Operation

from . import conf
from .constants import Stage
from .exceptions import AmbiguousPlan, AmbiguousStage

Plan = List[Tuple[Migration, bool]]


def hash_plan(plan: Plan) -> str:
    """Return a stable hash from a migration plan."""
    return hashlib.sha1(
        ";".join(f"{migration}:{backward}" for migration, backward in plan).encode()
    ).hexdigest()


def get_operation_stage(operation: Operation) -> Stage:
    """Return the heuristically determined `Stage` of the operation."""
    try:
        stage = operation.stage  # type: ignore
    except AttributeError:
        pass
    else:
        return Stage(stage)
    if isinstance(operation, (DeleteModel, RemoveField)):
        return Stage.POST_DEPLOY
    return Stage.PRE_DEPLOY


def partition_operations(
    operations: List[Operation],
    app_label: str,
) -> Tuple[List[Operation], List[Operation]]:
    """
    Partition an ordered list of operations by :class:`syzygy.constants.Stage`.

    If `operations` is composed of members with a
    :attr:`syzygy.constants.Stage.PRE_DEPLOY` stage after members with a
    :attr:`syzygy.constants.Stage.PRE_DEPLOY` stage and cannot be reordered a
    :class:`syzygy.exceptions.AmbiguousStage` exception will be raised.
    """
    stage_operations: Dict[Stage, List[Operation]] = {
        Stage.PRE_DEPLOY: [],
        Stage.POST_DEPLOY: [],
    }
    post_deploy_operations = stage_operations[Stage.POST_DEPLOY]
    for operation in operations:
        operation_stage = get_operation_stage(operation)
        if operation_stage is Stage.PRE_DEPLOY and post_deploy_operations:
            # If a pre-deploy operation is encountered after a post-deployment
            # one attempt to re-order operation is allowed.
            if all(
                op.reduce(operation, app_label) is True for op in post_deploy_operations  # type: ignore
            ):
                stage_operations[Stage.PRE_DEPLOY].append(operation)
                continue
            raise AmbiguousStage(
                "Post-deployment operations cannot be followed by "
                "pre-deployments operations"
            )
        stage_operations[operation_stage].append(operation)
    return stage_operations[Stage.PRE_DEPLOY], post_deploy_operations


def _get_migration_stage_override(migration: Migration) -> Optional[Stage]:
    """
    Return the `Stage` override configured through setting:`MIGRATION_STAGES_OVERRIDE`
    of the migration.
    """
    override = conf.MIGRATION_STAGES_OVERRIDE
    return override.get(f"{migration.app_label}.{migration.name}") or override.get(
        migration.app_label
    )


def _get_migration_stage_fallback(migration: Migration) -> Optional[Stage]:
    """
    Return the `Stage` fallback configured through setting:`MIGRATION_STAGES_FALLBACK`
    of the migration.
    """
    fallback = conf.MIGRATION_STAGES_FALLBACK
    return fallback.get(f"{migration.app_label}.{migration.name}") or fallback.get(
        migration.app_label
    )


def get_migration_stage(migration: Migration) -> Optional[Stage]:
    """
    Return the `Stage` of the migration.

    If not specified through setting:`MIGRATION_STAGES` or a `stage`
    :class:`django.db.migrations.Migration` class attribute it will be
    tentatively deduced from its list of
    attr:`django.db.migrations.Migration.operations`.

    If the migration doesn't have any `operations` then `None` will be returned
    and a :class:`syzygy.exceptions.AmbiguousStage` exception will be raised
    if it contains operations of mixed stages.
    """
    stage = getattr(migration, "stage", None) or _get_migration_stage_override(
        migration
    )
    if stage is not None:
        return stage
    for operation in migration.operations:
        operation_stage = get_operation_stage(operation)
        if stage is None:
            stage = operation_stage
        elif operation_stage != stage:
            fallback_stage = _get_migration_stage_fallback(migration)
            if fallback_stage:
                stage = fallback_stage
                break
            raise AmbiguousStage(
                f"Cannot automatically determine stage of {migration}."
            )
    return stage


def must_post_deploy_migration(
    migration: Migration, backward: bool = False
) -> Optional[bool]:
    """
    Return whether or not migration must be run after deployment.

    If not specified through a `stage` :class:`django.db.migrations.Migration`
    class attribute it will be tentatively deduced from its list of
    attr:`django.db.migrations.Migration.operations`.

    In cases of ambiguity a :class:`syzygy.exceptions.AmbiguousStage` exception
    will be raised.
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
    or migrations with ambiguous deploy stage a :class:`syzygy.exceptions.AmbiguousPlan`
    exception is raised.
    """
    pre_deploy_plan: Plan = []
    post_deploy = False
    for migration, backward in plan:
        if must_post_deploy_migration(migration, backward):
            post_deploy = True
        else:
            if post_deploy:
                raise AmbiguousPlan(
                    "Plan contains a non-contiguous sequence of pre-deployment "
                    "migrations."
                )
            pre_deploy_plan.append((migration, backward))
    return pre_deploy_plan
