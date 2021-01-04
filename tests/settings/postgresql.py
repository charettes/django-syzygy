import os

from . import *  # noqa

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "postgres")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": DB_HOST,
        "PORT": DB_PORT,
        "NAME": "syzygy",
        "USER": DB_USER,
        "PASSWORD": DB_PASSWORD,
    }
}
