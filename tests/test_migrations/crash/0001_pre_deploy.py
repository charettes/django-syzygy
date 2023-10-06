from django.db import migrations

from syzygy import Stage


def crash(*args, **kwargs):
    raise Exception("Test crash")


class Migration(migrations.Migration):
    initial = True
    stage = Stage.PRE_DEPLOY
    atomic = False

    operations = [migrations.RunPython(crash)]
