from typing import Dict, Tuple

SECRET_KEY = "not-secret-anymore"

TIME_ZONE = "America/Montreal"

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3"}}

INSTALLED_APPS = ["syzygy", "tests"]

SYZYGY_POSTPONE: Dict[Tuple[str, str], bool] = {}
