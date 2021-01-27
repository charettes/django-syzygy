import site
from typing import Dict, Optional

from django.apps import apps
from django.conf import settings

from .constants import Stage

__all__ = ("MIGRATION_STAGES_OVERRIDE", "MIGRATION_STAGES_FALLBACK")

MigrationStagesSetting = Dict[str, Stage]

MIGRATION_STAGES_OVERRIDE: MigrationStagesSetting
MIGRATION_STAGES_FALLBACK: MigrationStagesSetting


def _configure():
    global MIGRATION_STAGES_OVERRIDE
    global MIGRATION_STAGES_FALLBACK
    MIGRATION_STAGES_OVERRIDE = getattr(settings, "MIGRATION_STAGES_OVERRIDE", {})
    MIGRATION_STAGES_FALLBACK = getattr(settings, "MIGRATION_STAGES_FALLBACK", {})
    third_party_stages_fallback: Optional[Stage] = getattr(
        settings, "MIGRATION_THIRD_PARTY_STAGES_FALLBACK", Stage.PRE_DEPLOY
    )
    if third_party_stages_fallback:
        for app in apps.get_app_configs():
            for prefix in site.PREFIXES:
                if app.path.startswith(prefix):
                    MIGRATION_STAGES_FALLBACK.setdefault(
                        app.label, third_party_stages_fallback
                    )


watched_settings = {
    "MIGRATION_STAGES_OVERRIDE",
    "MIGRATION_STAGES_FALLBACK",
    "MIGRATION_THIRD_PARTY_STAGES_FALLBACK",
}


def _watch_settings(setting, **kwargs):
    if setting in watched_settings:
        _configure()
