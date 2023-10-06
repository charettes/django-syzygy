import time
import uuid
from multiprocessing.pool import ThreadPool
from random import shuffle

from django.core.exceptions import ImproperlyConfigured
from django.test.testcases import SimpleTestCase
from django.test.utils import override_settings

from syzygy.quorum import (
    QuorumDisolved,
    join_quorum,
    poll_quorum,
    sever_quorum,
)


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
    quorum = 5

    def test_multiple(self):
        namespace = str(uuid.uuid4())
        self.assertFalse(join_quorum(namespace, 2))
        self.assertFalse(poll_quorum(namespace, 2))
        self.assertTrue(join_quorum(namespace, 2))
        self.assertTrue(poll_quorum(namespace, 2))

    @classmethod
    def attain_quorum(cls, namespace):
        if join_quorum(namespace, cls.quorum):
            return True
        while not poll_quorum(namespace, cls.quorum):
            time.sleep(0.01)
        return False

    def test_attainment(self):
        namespace = str(uuid.uuid4())

        with ThreadPool(processes=self.quorum) as pool:
            results = pool.map_async(
                self.attain_quorum, [namespace] * self.quorum
            ).get()

        self.assertEqual(sum(1 for result in results if result is True), 1)
        self.assertEqual(sum(1 for result in results if result is False), 4)

    def test_attainment_namespace_reuse(self):
        namespace = str(uuid.uuid4())
        self.assertFalse(join_quorum(namespace, 2))
        self.assertTrue(join_quorum(namespace, 2))
        self.assertTrue(poll_quorum(namespace, 2))
        # Once quorum is reached its associated namespace is immediately
        # cleared to make it reusable.
        self.assertFalse(join_quorum(namespace, 2))
        self.assertTrue(join_quorum(namespace, 2))
        self.assertTrue(poll_quorum(namespace, 2))

    def test_disolution(self):
        namespace = str(uuid.uuid4())

        calls = [(self.attain_quorum, (namespace,))] * (self.quorum - 1)
        calls.append((sever_quorum, (namespace, self.quorum)))
        shuffle(calls)

        with ThreadPool(processes=self.quorum) as pool:
            results = [pool.apply_async(func, args) for func, args in calls]
            pool.close()
            pool.join()

        disolved = 0
        for result in results:
            try:
                attained = result.get()
            except QuorumDisolved:
                disolved += 1
            else:
                if attained is not None:
                    self.fail(f"Unexpected quorum attainment: {attained}")
        self.assertEqual(disolved, self.quorum - 1)

    def test_disolution_namespace_reuse(self):
        namespace = str(uuid.uuid4())
        self.assertFalse(join_quorum(namespace, 2))
        sever_quorum(namespace, 2)
        with self.assertRaises(QuorumDisolved):
            poll_quorum(namespace, 2)
        # Once quorum is disolved its associated namespace is immediately
        # cleared to make it reusable.
        self.assertFalse(join_quorum(namespace, 2))
        self.assertTrue(join_quorum(namespace, 2))
        self.assertTrue(poll_quorum(namespace, 2))


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
