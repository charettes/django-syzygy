from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    operations = [
        migrations.CreateModel(
            "Foo",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("bar", models.IntegerField()),
            ],
        ),
        migrations.CreateModel(
            "Bar",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(unique=True)),
            ],
            options={"managed": False},
        ),
    ]
