import django
from django.db.migrations.state import ModelState
from django.db.models.fields import Field

if django.VERSION >= (3, 1):

    def get_model_state_field(model_state: ModelState, field_name: str) -> Field:
        return model_state.fields[field_name]  # type: ignore


else:

    def get_model_state_field(model_state: ModelState, field_name: str) -> Field:
        for fname, field in model_state.fields:
            if fname == field_name:
                return field
        raise KeyError(field_name)
