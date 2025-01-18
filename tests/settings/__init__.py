SECRET_KEY = "not-secret-anymore"

TIME_ZONE = "America/Montreal"

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3"}}

INSTALLED_APPS = ["syzygy", "tests"]

SYZYGY_POSTPONE: dict[tuple[str, str], bool] = {}

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
