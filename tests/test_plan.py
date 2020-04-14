from django.db.migrations import CreateModel, DeleteModel, Migration
from django.db.migrations.operations.fields import RemoveField
from django.test import SimpleTestCase

from syzygy.plan import must_postpone_migration, must_postpone_operation


class MustPostponeOperationTests(SimpleTestCase):
    def test_postpone_operations(self):
        operations = [DeleteModel("model"), RemoveField("model", "field")]
        for operation in operations:
            with self.subTest(operation=operation):
                self.assertIs(True, must_postpone_operation(operation))
                self.assertIs(False, must_postpone_operation(operation, backward=True))

    def test_prerequisite_operations(self):
        operations = [CreateModel("model", [])]
        for operation in operations:
            with self.subTest(operation=operation):
                self.assertIs(False, must_postpone_operation(operation))
                self.assertIs(True, must_postpone_operation(operation, backward=True))


class MustPostponeMigrationTests(SimpleTestCase):
    def test_pospone_attribute(self):
        class PostponedTrueMigration(Migration):
            postpone = True

        migration = PostponedTrueMigration("tests", "migration")
        self.assertIs(True, must_postpone_migration(migration))
        self.assertIs(False, must_postpone_migration(migration, backward=True))

        class PostponedFalseMigration(Migration):
            postpone = False

        migration = PostponedFalseMigration("tests", "migration")
        self.assertIs(False, must_postpone_migration(migration))
        self.assertIs(True, must_postpone_migration(migration, backward=True))

    def test_no_operations_never_postponed(self):
        class PostponedMigration(Migration):
            operations = []

        migration = PostponedMigration("tests", "migration")
        self.assertIs(False, must_postpone_migration(migration))
        self.assertIs(False, must_postpone_migration(migration, backward=True))

    def test_postpone_by_operations(self):
        class PostponedMigration(Migration):
            operations = [DeleteModel("model"), RemoveField("model", "field")]

        migration = PostponedMigration("tests", "migration")
        self.assertIs(True, must_postpone_migration(migration))
        self.assertIs(False, must_postpone_migration(migration, backward=True))

    def test_ambiguous_operations(self):
        class AmgiguousOperationsMigration(Migration):
            operations = [CreateModel("foo", fields=[]), DeleteModel("bar")]

        migration = AmgiguousOperationsMigration("tests", "migration")
        with self.assertRaises(ValueError):
            must_postpone_migration(migration)
