from contextlib import contextmanager

from django.db import migrations
from django.db.models.fields import NOT_PROVIDED

from syzygy.constants import Stage


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


class PreRemoveField(migrations.AlterField):
    """
    Perform database operations required to make sure an application with a
    rolling deployment won't crash prior to a field removal.

    If the field has a `default` value defined its corresponding column is
    altered to use it until the field is removed otherwise the field is made
    NULL'able if it's not already.
    """

    elidable = True

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        # Ensure column meant to be removed have database level default defined
        # or is made NULL'able prior to removal to allow INSERT during the
        # deployment stage.
        field = model._meta.get_field(self.name)
        if (
            field.default is not NOT_PROVIDED
            # XXX: Not implemented on SQLite because of the lack of ALTER TABLE
            # support which would require considerable changes to the SQLite's
            # backend `remake_table` method.
            and schema_editor.connection.vendor != "sqlite"
        ):
            _alter_field_db_default(schema_editor, model, self.name)
        else:
            nullable_field = field.clone()
            nullable_field.null = True
            operation = migrations.AlterField(
                self.model_name, self.name, nullable_field
            )
            operation.state_forwards(app_label, to_state)
            operation.database_forwards(app_label, schema_editor, from_state, to_state)


class AddField(migrations.AddField):
    """
    Subclass of `AddField` that preserves the database default on database
    application.
    """

    @contextmanager
    def _include_column_default(self, schema_editor, model):
        # On the SQLite backend the strategy is different since it emulates
        # ALTER support by rebuilding tables.
        column_sql_ = schema_editor.column_sql

        def column_sql(model, field, include_default=False):
            include_default |= field.name == self.name
            # XXX: SQLite doesn't support parameterized DDL but this isn't an
            # issue upstream since this method is never called with
            # `include_default=True` due to table rebuild.
            sql, params = column_sql_(model, field, include_default)
            return sql % tuple(params), ()

        schema_editor.column_sql = column_sql
        try:
            yield
        finally:
            schema_editor.column_sql = column_sql_

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
            return self._include_column_default(schema_editor, model)
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


class PostAddField(migrations.AlterField):
    """
    Elidable operation that drops a previously preserved database default.
    """

    elidable = True
    stage = Stage.POST_DEPLOY

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        if schema_editor.connection.vendor == "sqlite":
            # Simply trigger a table rebuild.
            super().database_forwards(app_label, schema_editor, from_state, to_state)
        else:
            _alter_field_db_default(schema_editor, model, self.name, drop=True)
