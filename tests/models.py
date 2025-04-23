from django.db import models


class Foo(models.Model):
    pass


class Bar(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        managed = False
