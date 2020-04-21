from django.db import migrations

from syzygy import Stage


class Migration(migrations.Migration):
    dependencies = [("tests", "0001_pre_deploy")]
    stage = Stage.POST_DEPLOY
    atomic = False
