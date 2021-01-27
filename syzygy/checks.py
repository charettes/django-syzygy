import os
from importlib import import_module

from django.apps import apps
from django.core.checks import Error
from django.db.migrations.loader import MigrationLoader
from django.utils.module_loading import import_string

from .plan import must_post_deploy_migration


def check_migrations(app_configs, **kwargs):
    if app_configs is None:
        app_configs = apps.get_app_configs()
    errors = []
    hint = (
        "Assign an explicit stage to it, break its operation into multiple "
        "migrations if it's not already applied or define an explicit stage for "
        "it using `MIGRATION_STAGE_OVERRIDE` or `MIGRATION_STAGE_FALLBACK` if the "
        "migration is not under your control."
    )
    for app_config in app_configs:
        # Most of the following code is taken from MigrationLoader.load_disk
        # while allowing non-global app_configs to be used.
        module_name, _explicit = MigrationLoader.migrations_module(app_config.label)
        if module_name is None:  # pragma: no cover
            continue
        try:
            module = import_module(module_name)
        except ImportError:
            # This is not the place to deal with migration issues.
            continue
        directory = os.path.dirname(module.__file__)
        migration_names = set()
        for name in os.listdir(directory):
            if name.endswith(".py"):
                import_name = name.rsplit(".", 1)[0]
                migration_names.add(import_name)
        for migration_name in migration_names:
            try:
                migration_class = import_string(
                    f"{module_name}.{migration_name}.Migration"
                )
            except ImportError:
                # This is not the place to deal with migration issues.
                continue
            migration = migration_class(migration_name, app_config.label)
            try:
                must_post_deploy_migration(migration)
            except ValueError as e:
                errors.append(
                    Error(
                        str(e),
                        hint=hint,
                        obj=(migration.app_label, migration.name),
                        id="migrations.0001",
                    )
                )
    return errors
