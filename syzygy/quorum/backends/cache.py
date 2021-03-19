from typing import Optional

from django.core.cache import DEFAULT_CACHE_ALIAS, caches

from .base import QuorumBase


class CacheQuorum(QuorumBase):
    cache_key_format = "syzygy-quorum:{namespace}"

    def __init__(
        self,
        alias: str = DEFAULT_CACHE_ALIAS,
        timeout: int = 3600,
        version: Optional[int] = None,
    ):
        self.cache = caches[alias]
        self.timeout = timeout
        self.version = version

    def join(self, namespace: str, quorum: int) -> bool:
        """Join the `namespace` and return whether or not `quorum` was reached."""
        cache_key = self.cache_key_format.format(namespace=namespace)
        self.cache.add(cache_key, 0, timeout=self.timeout, version=self.version)
        return self.cache.incr(cache_key, version=self.version) == quorum

    def poll(self, namespace: str, quorum: int) -> bool:
        """Return whether or not `namespace`'s `quorum` was reached."""
        cache_key = self.cache_key_format.format(namespace=namespace)
        return self.cache.get(cache_key, version=self.version) == quorum
