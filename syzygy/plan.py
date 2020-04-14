from typing import List, NewType, Optional, Tuple

from django.conf import settings
from django.db.migrations import DeleteModel, Migration, RemoveField
from django.db.migrations.operations.base import Operation

Plan = NewType("Plan", List[Tuple[Migration, bool]])


def must_postpone_operation(
    operation: Operation, backward: bool = False
) -> Optional[bool]:
    """Return whether not operation must be postponed."""
    if isinstance(operation, (DeleteModel, RemoveField)):
        return not backward
    # All other operations are assumed to be prerequisite.
    return backward


def must_postpone_migration(
    migration: Migration, backward: bool = False
) -> Optional[bool]:
    """
    Return whether or not migration must be postponed.

    If not specified through a `postpone` :class:`django.db.migrations.Migration`
    class attribute it will be tentatively deduced from its list of
    attr:`django.db.migrations.Migration.operations`.

    In cases of ambiguity a `ValueError` will be raised.
    """
    # Postponed migrations are considered prerequisite when they are reverted.
    try:
        setting = settings.SYZYGY_POSTPONE
    except AttributeError:
        global_postpone = None
    else:
        key = (migration.app_label, migration.name)
        global_postpone = setting.get(key)
    postpone = getattr(migration, "postpone", global_postpone)
    if postpone is True:
        return not backward
    elif postpone is False:
        return backward
    # Migrations without operations such as merges are never postponed.
    if not migration.operations:
        return False
    for operation in migration.operations:
        postpone_operation = must_postpone_operation(operation, backward)
        if postpone is None:
            postpone = postpone_operation
        elif postpone_operation != postpone:
            raise ValueError(
                f"Cannot determine whether or not {migration} should be postponed."
            )
    return postpone


def get_prerequisite_plan(plan: Plan) -> Plan:
    """
    Trim provided plan to its leading contiguous prerequisite sequence.

    If the plan contains non-contiguous sequence of prerequisite migrations
    or migrations with ambiguous prerequisite nature a `ValueError` is raised.
    """
    prerequisite_plan = []
    postpone = False
    for migration, backward in plan:
        if must_postpone_migration(migration, backward):
            postpone = True
        else:
            if postpone:
                raise ValueError(
                    "Plan contains a non-contiguous sequence of prerequisite "
                    "migrations."
                )
            prerequisite_plan.append((migration, backward))
    return prerequisite_plan
