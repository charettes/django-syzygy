from functools import lru_cache
from typing import Union

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string


@lru_cache(maxsize=1)
def _get_quorum(backend_path, **backend_options):
    backend_cls = import_string(backend_path)
    return backend_cls(**backend_options)


def _get_configured_quorum():
    try:
        config: Union[dict, str] = settings.MIGRATION_QUORUM_BACKEND  # type: ignore
    except AttributeError:
        raise ImproperlyConfigured(
            "The `MIGRATION_QUORUM_BACKEND` setting must be configured "
            "for syzygy.quorum to be used"
        )
    backend_path: str
    backend_options: dict
    if isinstance(config, str):
        backend_path = config
        backend_options = {}
    elif isinstance(config, dict) and config.get("backend"):
        backend_options = config.copy()
        backend_path = backend_options.pop("backend")
    else:
        raise ImproperlyConfigured(
            "The `MIGRATION_QUORUM_BACKEND` setting must either be an import "
            "path string or a dict with a 'backend' path key string"
        )
    try:
        return _get_quorum(backend_path, **backend_options)
    except ImportError as exc:
        raise ImproperlyConfigured(
            f"Cannot import `MIGRATION_QUORUM_BACKEND` backend '{backend_path}'"
        ) from exc
    except TypeError as exc:
        raise ImproperlyConfigured(
            f"Cannot initialize `MIGRATION_QUORUM_BACKEND` backend '{backend_path}' "
            f"with {backend_options!r}"
        ) from exc


def join_quorum(namespace: str, quorum: int) -> bool:
    return _get_configured_quorum().join(namespace=namespace, quorum=quorum)


def poll_quorum(namespace: str, quorum: int) -> bool:
    return _get_configured_quorum().poll(namespace=namespace, quorum=quorum)
