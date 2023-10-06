from typing import Optional, Tuple

from django.core.cache import DEFAULT_CACHE_ALIAS, caches

from ..exceptions import QuorumDisolved
from .base import QuorumBase


class CacheQuorum(QuorumBase):
    namespace_key_format = "syzygy-quorum:{namespace}"

    def __init__(
        self,
        alias: str = DEFAULT_CACHE_ALIAS,
        timeout: int = 3600,
        version: Optional[int] = None,
    ):
        self.cache = caches[alias]
        self.timeout = timeout
        self.version = version

    @classmethod
    def _get_namespace_keys(cls, namespace: str) -> Tuple[str, str]:
        namespace_key = cls.namespace_key_format.format(namespace=namespace)
        clear_namespace_key = f"{namespace_key}:clear"
        return namespace_key, clear_namespace_key

    def _clear(self, namespace: str):
        self.cache.delete_many(
            self._get_namespace_keys(namespace), version=self.version
        )

    def join(self, namespace: str, quorum: int) -> bool:
        namespace_key, clear_namespace_key = self._get_namespace_keys(namespace)
        self.cache.add(namespace_key, 0, timeout=self.timeout, version=self.version)
        self.cache.add(
            clear_namespace_key,
            quorum - 1,
            timeout=self.timeout,
            version=self.version,
        )
        current = self.cache.incr(namespace_key, version=self.version)
        if current == quorum:
            return True
        return False

    def sever(self, namespace: str, quorum: int):
        namespace_key, _ = self._get_namespace_keys(namespace)
        self.cache.add(namespace_key, 0, timeout=self.timeout, version=self.version)
        self.cache.decr(namespace_key, quorum, version=self.version)

    def poll(self, namespace: str, quorum: int) -> bool:
        namespace_key, clear_namespace_key = self._get_namespace_keys(namespace)
        current = self.cache.get(namespace_key, version=self.version)
        if current == quorum:
            if self.cache.decr(clear_namespace_key, version=self.version) == 0:
                self._clear(namespace)
            return True
        elif current <= 0:
            if self.cache.decr(clear_namespace_key, version=self.version) == 0:
                self._clear(namespace)
            raise QuorumDisolved
        return False
