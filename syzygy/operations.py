from contextlib import contextmanager

from django.db import connection
from django.db.backends.utils import truncate_name
from django.db.migrations import operations
from django.db.models.fields import NOT_PROVIDED
from django.utils.functional import cached_property

from .compat import field_db_default_supported
from .constants import Stage


def _alter_field_db_default_sql_params(schema_editor, model, name, drop=False):
    field = model._meta.get_field(name)
    changes_sql, params = schema_editor._alter_column_default_sql(
        model, None, field, drop=drop
    )
    sql = schema_editor.sql_alter_column % {
        "table": schema_editor.quote_name(model._meta.db_table),
        "changes": changes_sql,
    }
    return sql, params


def _alter_field_db_default(schema_editor, model, name, drop=False):
    sql, params = _alter_field_db_default_sql_params(
        schema_editor, model, name, drop=drop
    )
    schema_editor.execute(sql, params)


@contextmanager
def _force_field_alteration(schema_editor):
    # Django implements an optimization to prevent SQLite table rebuilds
    # when unnecessary. Until proper db_default alteration support lands this
    # optimization has to be disabled under some circumstances.
    _field_should_be_altered = schema_editor._field_should_be_altered
    schema_editor._field_should_be_altered = lambda old_field, new_field: True
    try:
        yield
    finally:
        schema_editor._field_should_be_altered = _field_should_be_altered


@contextmanager
def _include_column_default(schema_editor, field_name):
    column_sql_ = schema_editor.column_sql

    def column_sql(model, field, include_default=False):
        include_default |= field.name == field_name
        # XXX: SQLite doesn't support parameterized DDL but this isn't an
        # issue upstream since this method is never called with
        # `include_default=True` due to table rebuild.
        sql, params = column_sql_(model, field, include_default)
        return sql % tuple(params), ()

    schema_editor.column_sql = column_sql
    try:
        with _force_field_alteration(schema_editor):
            yield
    finally:
        schema_editor.column_sql = column_sql_


class PreRemoveField(operations.AlterField):
    """
    Perform database operations required to make sure an application with a
    rolling deployment won't crash prior to a field removal.

    If the field has a `default` value defined its corresponding column is
    altered to use it until the field is removed otherwise the field is made
    NULL'able if it's not already.
    """

    def state_forwards(self, app_label, state):
        pass

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        to_state = to_state.clone()
        super().state_forwards(app_label, to_state)
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        # Ensure column meant to be removed have database level default defined
        # or is made NULL'able prior to removal to allow INSERT during the
        # deployment stage.
        field = model._meta.get_field(self.name)
        if field.default is not NOT_PROVIDED:
            if schema_editor.connection.vendor == "sqlite":
                with _include_column_default(schema_editor, self.name):
                    super().database_forwards(
                        app_label, schema_editor, from_state, to_state
                    )
            else:
                _alter_field_db_default(schema_editor, model, self.name)
        else:
            nullable_field = field.clone()
            nullable_field.null = True
            operation = operations.AlterField(
                self.model_name, self.name, nullable_field
            )
            operation.state_forwards(app_label, to_state)
            operation.database_forwards(app_label, schema_editor, from_state, to_state)

    @property
    def migration_name_fragment(self):
        if self.field.default is not NOT_PROVIDED:
            return "set_db_default_%s_%s" % (
                self.model_name_lower,
                self.name,
            )
        return "set_nullable_%s_%s" % (
            self.model_name_lower,
            self.name,
        )

    def describe(self):
        if self.field.default is not NOT_PROVIDED:
            return "Set database DEFAULT of field %s on %s" % (
                self.name,
                self.model_name,
            )
        return "Set field %s of %s NULLable" % (self.name, self.model_name)


if field_db_default_supported:
    # XXX: This allows for a more descriptive migration_name_fragment
    # to be associated with instances of AlterField.
    operations.AlterField.migration_name_fragment = cached_property(  # type: ignore[assignment,method-assign]
        operations.AlterField.migration_name_fragment.fget  # type: ignore[attr-defined]
    )
    operations.AlterField.migration_name_fragment.name = "migration_name_fragment"  # type: ignore[attr-defined]

    def get_pre_remove_field_operation(model_name, name, field, **kwargs):
        if field.db_default is not NOT_PROVIDED:
            raise ValueError(
                "Fields with a db_default don't require a pre-deployment operation."
            )
        field = field.clone()
        if field.has_default():
            field.db_default = field.get_default()
            fragment = f"set_db_default_{model_name.lower()}_{name}"
            description = f"Set database DEFAULT of field {name} on {model_name}"
        else:
            field.null = True
            fragment = f"set_nullable_{model_name.lower()}_{name}"
            description = f"Set field {name} of {model_name} NULLable"
        operation = operations.AlterField(model_name, name, field, **kwargs)
        operation.migration_name_fragment = fragment
        operation.describe = lambda: description
        return operation

    # XXX: Shim kept for historical migrations generated before Django 5.
    PreRemoveField = get_pre_remove_field_operation  # type: ignore[assignment,misc] # noqa: F811
else:
    get_pre_remove_field_operation = PreRemoveField  # type: ignore[assignment]


class AddField(operations.AddField):
    """
    Subclass of `AddField` that preserves the database default on database
    application.
    """

    @contextmanager
    def _prevent_drop_default(self, schema_editor, model):
        # On other backends the most straightforward way
        drop_default_sql_params = _alter_field_db_default_sql_params(
            schema_editor, model, self.name, drop=True
        )
        execute_ = schema_editor.execute

        def execute(sql, params=()):
            if (sql, params) == drop_default_sql_params:
                return
            return execute_(sql, params)

        schema_editor.execute = execute
        try:
            yield
        finally:
            schema_editor.execute = execute_

    def _preserve_column_default(self, schema_editor, model):
        # XXX: Hopefully future support for `Field.db_default` will add better
        # injection points to `BaseSchemaEditor.add_field`.
        if schema_editor.connection.vendor == "sqlite":
            # On the SQLite backend the strategy is different since it emulates
            # ALTER support by rebuilding tables.
            return _include_column_default(schema_editor, self.name)
        return self._prevent_drop_default(schema_editor, model)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        # Defer the removal of DEFAUT to `PostAddField`
        with self._preserve_column_default(schema_editor, model):
            return super().database_forwards(
                app_label, schema_editor, from_state, to_state
            )


if field_db_default_supported:

    def get_pre_add_field_operation(model_name, name, field, preserve_default=True):
        if field.db_default is not NOT_PROVIDED:
            raise ValueError(
                "Fields with a db_default don't require a pre-deployment operation."
            )
        field = field.clone()
        field.db_default = field.get_default()
        operation = operations.AddField(model_name, name, field, preserve_default)
        return operation

    # XXX: Shim kept for historical migrations generated before Django 5.
    AddField = get_pre_add_field_operation  # type: ignore[assignment,misc] # noqa: F811
else:
    get_pre_add_field_operation = AddField


class PostAddField(operations.AlterField):
    """
    Elidable operation that drops a previously preserved database default.
    """

    stage = Stage.POST_DEPLOY

    def state_forwards(self, app_label, state):
        pass

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        if schema_editor.connection.vendor == "sqlite":
            # Trigger a table rebuild to DROP the database level DEFAULT
            with _force_field_alteration(schema_editor):
                super().database_forwards(
                    app_label, schema_editor, from_state, to_state
                )
        else:
            _alter_field_db_default(schema_editor, model, self.name, drop=True)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        to_state = to_state.clone()
        super().state_forwards(app_label, to_state)
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        if schema_editor.connection.vendor == "sqlite":
            with _include_column_default(schema_editor, self.name):
                super().database_forwards(
                    app_label, schema_editor, from_state, to_state
                )
        else:
            _alter_field_db_default(schema_editor, model, self.name)

    @property
    def migration_name_fragment(self):
        return "drop_db_default_%s_%s" % (
            self.model_name_lower,
            self.name,
        )

    def describe(self):
        return "Drop database DEFAULT of field %s on %s" % (
            self.name,
            self.model_name,
        )


if field_db_default_supported:

    def get_post_add_field_operation(model_name, name, field, preserve_default=True):
        if field.db_default is not NOT_PROVIDED:
            raise ValueError(
                "Fields with a db_default don't require a post-deployment operation."
            )
        field = field.clone()
        field.db_default = NOT_PROVIDED
        if not preserve_default:
            field.default = NOT_PROVIDED
        operation = AlterField(
            model_name,
            name,
            field,
            stage=Stage.POST_DEPLOY,
        )
        operation.migration_name_fragment = (
            f"drop_db_default_{model_name.lower()}_{name}"
        )
        operation.describe = (
            lambda: f"Drop database DEFAULT of field {name} on {model_name}"
        )
        return operation

    # XXX: Shim kept for historical migrations generated before Django 5.
    PostAddField = get_post_add_field_operation  # type: ignore[assignment,misc] # noqa: F811
else:
    get_post_add_field_operation = PostAddField


class StagedOperation(operations.base.Operation):
    stage: Stage

    def __init__(self, *args, **kwargs):
        self.stage = kwargs.pop("stage")
        super().__init__(*args, **kwargs)

    @classmethod
    def for_stage(cls, operation: operations.base.Operation, stage: Stage):
        _, args, kwargs = operation.deconstruct()
        kwargs["stage"] = stage
        return cls(*args, **kwargs)

    def deconstruct(self):
        name, args, kwargs = super().deconstruct()
        kwargs["stage"] = self.stage
        return name, args, kwargs


class RenameField(StagedOperation, operations.RenameField):
    """
    Subclass of ``RenameField`` that explicitly defines a stage for the rare
    instances where a rename operation is safe to perform.
    """

    # XXX: Explicitly define the signature as migration serializer rely on
    # __init__ introspection to assign the kwargs.
    def __init__(self, model_name, old_name, new_name, stage):
        super().__init__(
            model_name=model_name, old_name=old_name, new_name=new_name, stage=stage
        )


class RenameModel(StagedOperation, operations.RenameModel):
    """
    Subclass of ``RenameModel`` that explicitly defines a stage for the rare
    instances where a rename operation is safe to perform.
    """

    # XXX: Explicitly define the signature as migration serializer rely on
    # __init__ introspection to assign the kwargs.
    def __init__(self, old_name, new_name, stage):
        super().__init__(old_name=old_name, new_name=new_name, stage=stage)


class AlterField(StagedOperation, operations.AlterField):
    """
    Subclass of ``AlterField`` that allows explicitly defining a stage.
    """

    # XXX: Explicitly define the signature as migration serializer rely on
    # __init__ introspection to assign the kwargs.
    def __init__(self, model_name, name, field, stage, preserve_default=True):
        super().__init__(
            model_name=model_name,
            name=name,
            field=field,
            stage=stage,
            preserve_default=preserve_default,
        )


class AliasOperationMixin:
    @staticmethod
    def _create_instead_of_triggers(schema_editor, view_name, model):
        """
        SQLite requires INSTEAD OF triggers to be created for the view to
        direct DML statements to the referenced table.
        """
        quote = schema_editor.quote_name
        max_name_length = schema_editor.connection.ops.max_name_length()
        opts = model._meta
        view = quote(view_name)
        table = quote(opts.db_table)
        columns = [quote(field.column) for field in opts.local_fields]
        pk = quote(opts.pk.column)
        schema_editor.execute(
            (
                "CREATE TRIGGER {trigger} INSTEAD OF INSERT ON {view}\n"
                "BEGIN\n"
                "INSERT INTO {table}({fields}) VALUES({values});\n"
                "END"
            ).format(
                trigger=quote(truncate_name(f"{view_name}_insert", max_name_length)),
                view=view,
                table=table,
                fields=", ".join(columns),
                values=", ".join(f"NEW.{column}" for column in columns),
            )
        )
        for field, column in zip(opts.local_fields, columns):
            schema_editor.execute(
                (
                    "CREATE TRIGGER {trigger} INSTEAD OF UPDATE OF {column} ON {view}\n"
                    "BEGIN\n"
                    "UPDATE {table} SET {column}=NEW.{column} WHERE {pk}=NEW.{pk};\n"
                    "END"
                ).format(
                    trigger=quote(
                        truncate_name(
                            f"{view_name}_update_{field.name}", max_name_length
                        )
                    ),
                    view=view,
                    table=table,
                    column=column,
                    pk=pk,
                )
            )
        schema_editor.execute(
            (
                "CREATE TRIGGER {trigger} INSTEAD OF DELETE ON {view}\n"
                "BEGIN\n"
                "DELETE FROM {table} WHERE {pk}=OLD.{pk};\n"
                "END"
            ).format(
                trigger=quote(truncate_name(f"{view_name}_delete", max_name_length)),
                view=view,
                table=table,
                pk=pk,
            )
        )

    @staticmethod
    def _get_view_name(app_label, alias_name):
        return truncate_name(
            "%s_%s" % (app_label, alias_name.lower()),
            connection.ops.max_name_length(),
        )

    @classmethod
    def _create_view(cls, schema_editor, model, alias_name):
        # XXX: Explicitly use connection to retrieve ops.max_name_length() and
        # not schema_editor.connection as Django systematically use the default
        # connection (see https://code.djangoproject.com/ticket/13528).
        view_name = cls._get_view_name(model._meta.app_label, alias_name)
        quote = schema_editor.quote_name
        schema_editor.execute(
            "CREATE VIEW {} AS SELECT * FROM {}".format(
                quote(view_name), quote(model._meta.db_table)
            )
        )
        if schema_editor.connection.vendor == "sqlite":
            cls._create_instead_of_triggers(schema_editor, view_name, model)

    @staticmethod
    def _drop_view(schema_editor, view_name: str):
        schema_editor.execute(
            "DROP VIEW {}".format(schema_editor.quote_name(view_name))
        )

    @classmethod
    def alias_model(cls, schema_editor, model, alias_name):
        for many_to_many in model._meta.local_many_to_many:
            through = many_to_many.remote_field.through
            if through._meta.auto_created:
                raise NotImplementedError(
                    "Aliasing of models containing many-to-many fields "
                    "without an explicit intermediary model (through) is not "
                    "implemented."
                )
        cls._create_view(schema_editor, model, alias_name)

    def unalias_model(cls, schema_editor, model, alias_name):
        view_name = cls._get_view_name(model._meta.app_label, alias_name)
        for many_to_many in model._meta.local_many_to_many:
            through = many_to_many.remote_field.through
            if through._meta.auto_created:
                raise NotImplementedError(
                    "Un-aliasing of models containing many-to-many fields "
                    "without an explicit intermediary model (through) is not "
                    "implemented."
                )
        cls._drop_view(schema_editor, view_name)


class AliasModel(AliasOperationMixin, operations.models.ModelOperation):
    """
    First stage of alias-based `RenameModel` replacement.

    Implements the alias creation for the table meant to be renamed.
    """

    stage = Stage.PRE_DEPLOY
    alias_name: str

    def __init__(self, name: str, alias_name: str):
        self.alias_name = alias_name
        super().__init__(name)

    @cached_property
    def alias_name_lower(self):
        return self.alias_name.lower()

    def state_forwards(self, app_label, state):
        # Create an un-managed model to represent the alias.
        aliased_model = state.models[app_label, self.name_lower].clone()
        aliased_model.name = self.alias_name
        aliased_model.options["managed"] = False
        state.add_model(aliased_model)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.name)
        alias = schema_editor.connection.alias
        if not self.allow_migrate_model(alias, model):
            return
        self.alias_model(schema_editor, model, self.alias_name)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        model = from_state.apps.get_model(app_label, self.name)
        alias = schema_editor.connection.alias
        if not self.allow_migrate_model(alias, model):
            return
        self.unalias_model(schema_editor, model, self.alias_name)

    def describe(self):
        return f"Alias model {self.name} to {self.alias_name}"

    def reduce(self, operation, app_label):
        if (
            isinstance(operation, RenameAliasedModel)
            and operation.name_lower == operation.old_name_lower
            and operation.new_name_lower == self.alias_name_lower
        ):
            return [operations.RenameModel(operation.old_name, operation.new_name)]
        return super().reduce(operation, app_label)


class RenameAliasedModel(AliasOperationMixin, operations.RenameModel):
    """
    Second stage of alias-based `RenameModel` replacements.

    Implements the table renaming and alias removal.
    """

    stage = Stage.POST_DEPLOY

    def state_forwards(self, app_label, state):
        state.remove_model(app_label, self.new_name)
        super().state_forwards(app_label, state)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        to_model = to_state.apps.get_model(app_label, self.new_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, to_model):
            return
        self.unalias_model(schema_editor, to_model, self.alias_name)
        super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        from_model = from_state.apps.get_model(app_label, self.new_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, from_model):
            return
        super().database_backwards(app_label, schema_editor, from_state, to_state)
        self.alias_model(schema_editor, from_model, self.alias_name)

    def describe(self):
        return f"Rename model {self.name} to {self.alias_name}"
