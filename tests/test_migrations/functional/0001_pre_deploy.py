from django.db import migrations

from syzygy import Stage


class Migration(migrations.Migration):
    initial = True
    stage = Stage.PRE_DEPLOY
    atomic = False
