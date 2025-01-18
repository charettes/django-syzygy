import hashlib
from typing import Dict, List, Optional, Tuple

from django.apps import apps
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
    Partition an ordered list of operations by :class:`syzygy.constants.Stage.PRE_DEPLOY`.

    If `operations` contains
    :attr:`syzygy.constants.Stage.POST_DEPLOY` stage members followed
    :attr:`syzygy.constants.Stage.PRE_DEPLOY` stage members and they cannot be
    reordered a :class:`syzygy.exceptions.AmbiguousStage` exception will be
    raised.
    """
    stage_operations: Dict[Stage, List[Operation]] = {
        Stage.PRE_DEPLOY: [],
        Stage.POST_DEPLOY: [],
    }
    post_deploy_operations = stage_operations[Stage.POST_DEPLOY]
    for operation in operations:
        operation_stage = get_operation_stage(operation)
        if operation_stage is Stage.PRE_DEPLOY and post_deploy_operations:
            # Attempt to re-order `operation` if a pre-deploy stage one is
            # encountered after a post-deployment one if allowed.
            if all(
                op.reduce(operation, app_label) is True for op in post_deploy_operations
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


def _get_defined_stage(migration: Migration) -> Optional[Stage]:
    """
    Return the explicitly defined `Stage` of a migration or
    `None` if not defined.
    """
    return getattr(migration, "stage", None) or _get_migration_stage_override(migration)


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
    stage = _get_defined_stage(migration)
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
    post_deploy_plan = {}
    for migration, backward in plan:
        if must_post_deploy_migration(migration, backward):
            post_deploy_plan[migration.app_label, migration.name] = migration
        else:
            post_deploy_dep = None
            if post_deploy_plan:
                post_deploy_dep = next(
                    (
                        post_deploy_plan[dependency]
                        for dependency in migration.dependencies
                        if dependency in post_deploy_plan
                    ),
                    None,
                )
            if post_deploy_dep:
                inferred = []
                stage_defined = _get_defined_stage(migration) is not None
                post_stage_defined = _get_defined_stage(post_deploy_dep) is not None
                if stage_defined:
                    stage_origin = "defined"
                else:
                    stage_origin = "inferred"
                    inferred.append(migration)
                if post_stage_defined:
                    post_stage_origin = "defined"
                else:
                    post_stage_origin = "inferred"
                    inferred.append(post_deploy_dep)
                msg = (
                    f"Plan contains a non-contiguous sequence of pre-deployment "
                    f"migrations. Migration {migration} is {stage_origin} to be applied "
                    f"pre-deployment but it depends on {post_deploy_dep} which is "
                    f"{post_stage_origin} to be applied post-deployment."
                )
                if inferred:
                    first_party_inferred = []
                    third_party_inferred = []
                    for migration in inferred:
                        try:
                            app = apps.get_app_config(migration.app_label)
                        except LookupError:
                            pass
                        else:
                            if conf.is_third_party_app(app):
                                third_party_inferred.append(str(migration))
                                continue
                        first_party_inferred.append(str(migration))
                    if first_party_inferred:
                        first_party_names = " or ".join(first_party_inferred)
                        msg += (
                            f" Defining an explicit `Migration.stage: syzygy.Stage` "
                            f"for {first_party_names} "
                        )
                    if third_party_inferred:
                        if first_party_inferred:
                            msg += "or setting "
                        else:
                            msg += " Setting "
                        msg += " or ".join(
                            f"`MIGRATION_STAGES_OVERRIDE[{migration_name!r}]`"
                            for migration_name in third_party_inferred
                        )
                        msg += " to an explicit `syzygy.Stage` "
                    msg += "to bypass inference might help."
                    for migration in inferred:
                        try:
                            app = apps.get_app_config(migration.app_label)
                        except LookupError:
                            continue
                        if not conf.is_third_party_app(app):
                            continue
                        break
                raise AmbiguousPlan(msg)
            pre_deploy_plan.append((migration, backward))
    return pre_deploy_plan
