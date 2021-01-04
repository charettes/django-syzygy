from django.db import migrations
from django.db.models.fields import NOT_PROVIDED


class PreRemoveField(migrations.AlterField):
    """
    Perform database operations required to make sure an application with a
    rolling deployment won't crash prior to a field removal.

    If the field has a `default` value defined its corresponding column is
    altered to use it until the field is removed otherwise the field is made
    NULL'able if it's not already.
    """

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
            and schema_editor.connection.vendor != "sqlite"
        ):
            # XXX: Not implemented on SQLite because of the lack of ALTER TABLE
            # support which would require considerable changes to the SQLite's
            # backend `remake_table` method.
            changes_sql, params = schema_editor._alter_column_default_sql(
                model, None, field
            )
            sql = schema_editor.sql_alter_column % {
                "table": schema_editor.quote_name(model._meta.db_table),
                "changes": changes_sql,
            }
            schema_editor.execute(sql, params)
        else:
            nullable_field = field.clone()
            nullable_field.null = True
            operation = migrations.AlterField(
                self.model_name, self.name, nullable_field
            )
            operation.state_forwards(app_label, to_state)
            operation.database_forwards(app_label, schema_editor, from_state, to_state)
