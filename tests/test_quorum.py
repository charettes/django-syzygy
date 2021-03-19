import time
import uuid
from multiprocessing.pool import ThreadPool

from django.core.exceptions import ImproperlyConfigured
from django.test.testcases import SimpleTestCase
from django.test.utils import override_settings

from syzygy.quorum import join_quorum, poll_quorum


class QuorumConfigurationTests(SimpleTestCase):
    def test_missing_setting(self):
        msg = (
            "The `MIGRATION_QUORUM_BACKEND` setting must be configured "
            "for syzygy.quorum to be used"
        )
        with self.assertRaisesMessage(ImproperlyConfigured, msg):
            join_quorum("foo", 1)

    @override_settings(MIGRATION_QUORUM_BACKEND={})
    def test_misconfigured_setting(self):
        msg = (
            "The `MIGRATION_QUORUM_BACKEND` setting must either be an import "
            "path string or a dict with a 'backend' path key string"
        )
        with self.assertRaisesMessage(ImproperlyConfigured, msg):
            join_quorum("foo", 1)

    @override_settings(MIGRATION_QUORUM_BACKEND="syzygy.void")
    def test_cannot_import_backend(self):
        msg = "Cannot import `MIGRATION_QUORUM_BACKEND` backend 'syzygy.void'"
        with self.assertRaisesMessage(ImproperlyConfigured, msg):
            join_quorum("foo", 1)

    @override_settings(
        MIGRATION_QUORUM_BACKEND={
            "backend": "syzygy.quorum.backends.cache.CacheQuorum",
            "unsupported": True,
        }
    )
    def test_cannot_initialize_backend(self):
        msg = (
            "Cannot initialize `MIGRATION_QUORUM_BACKEND` backend "
            "'syzygy.quorum.backends.cache.CacheQuorum' with {'unsupported': True}"
        )
        with self.assertRaisesMessage(ImproperlyConfigured, msg):
            join_quorum("foo", 1)


class BaseQuorumTestMixin:
    def test_single(self):
        namespace = str(uuid.uuid4())
        self.assertTrue(join_quorum(namespace, 1))

    def test_multiple(self):
        namespace = str(uuid.uuid4())
        self.assertFalse(join_quorum(namespace, 2))
        self.assertFalse(poll_quorum(namespace, 2))
        self.assertTrue(join_quorum(namespace, 2))
        self.assertTrue(poll_quorum(namespace, 2))

    def test_thread_safety(self):
        quorum = 5

        def achieve_quorum(namespace):
            if join_quorum(namespace, quorum):
                return True
            while not poll_quorum(namespace, quorum):
                time.sleep(0.01)
            return False

        with ThreadPool(processes=quorum) as pool:
            results = pool.map_async(achieve_quorum, [str(uuid.uuid4())] * quorum).get()

        self.assertTrue(all(result is False for result in results[:-1]))
        self.assertIs(results[-1], True)


@override_settings(MIGRATION_QUORUM_BACKEND="syzygy.quorum.backends.cache.CacheQuorum")
class CacheQuorumTests(BaseQuorumTestMixin, SimpleTestCase):
    pass


@override_settings(
    CACHES={
        "quorum": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    },
    MIGRATION_QUORUM_BACKEND={
        "backend": "syzygy.quorum.backends.cache.CacheQuorum",
        "alias": "quorum",
        "version": 46,
    },
)
class CacheQuorumConfigsTests(BaseQuorumTestMixin, SimpleTestCase):
    pass
