from collections import namedtuple

import django
from django.utils.functional import cached_property

field_db_default_supported = django.VERSION >= (5,)

try:
    from django.db.migrations.autodetector import OperationDependency

except ImportError:

    class OperationDependency(
        namedtuple("OperationDependency", "app_label model_name field_name type")
    ):
        class Type:
            CREATE = True
            REMOVE = False
            ALTER = "alter"
            REMOVE_ORDER_WRT = "order_wrt_unset"
            ALTER_FOO_TOGETHER = "foo_together_change"

        @cached_property
        def model_name_lower(self):
            return self.model_name.lower()

        @cached_property
        def field_name_lower(self):
            return self.field_name.lower()
