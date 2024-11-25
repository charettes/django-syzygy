import os

from . import *  # noqa

DB_HOST = os.environ.get("DB_MYSQL_HOST", "127.0.0.1")
DB_PORT = os.environ.get("DB_MYSQL_PORT", "3306")
DB_USER = os.environ.get("DB_MYSQL_USER", "mysql")
DB_PASSWORD = os.environ.get("DB_MYSQL_PASSWORD", "mysql")


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "HOST": DB_HOST,
        "PORT": DB_PORT,
        "NAME": "syzygy",
        "USER": DB_USER,
        "PASSWORD": DB_PASSWORD,
    }
}
