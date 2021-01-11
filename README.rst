django-syzygy
=============

.. image:: https://travis-ci.org/charettes/django-syzygy.svg?branch=master
    :target: https://travis-ci.org/charettes/django-syzygy
    :alt: Build Status

.. image:: https://coveralls.io/repos/github/charettes/django-syzygy/badge.svg?branch=master
    :target: https://coveralls.io/github/charettes/django-syzygy?branch=master
    :alt: Coverage status


Django application providing database migration tooling to automate their deployment.

Inspired by a `2015 post from Ludwig Hähne`_ and experience dealing with migration at Zapier_.

.. _`2015 post from Ludwig Hähne`: https://pankrat.github.io/2015/django-migrations-without-downtimes/#django-wishlist
.. _Zapier: https://zapier.com

Installation
------------

.. code:: sh

    pip install django-syzygy

Usage
-----

Add `'syzygy'` to your `INSTALLED_APPS`

.. code:: python

    # settings.py
    INSTALLED_APPS = [
        ...
        'syzygy',
        ...
    ]

Setup you deployment pipeline to run `migrate --pre-deploy` before rolling
out your code changes and `migrate` afterwards to apply the postponed
migrations.

Concept
-------

Syzygy introduces a notion of *prerequisite* and *postponed* migrations with
regards to deployment.

A migration is assumed to be a *prerequisite* to deployment unless it contains
a destructive operation or the migration has its `stage` class attribute set to
`POST_DEPLOY`. When this attribute is defined it will bypass `operations` based
heuristics.

e.g. this migration would be considered a *prerequisite*

.. code:: python

    class Migration(migrations.Migration):
        operations = [
            AddField('model', 'field', models.IntegerField(null=True))
        ]

while the following migrations would be *postponed*

.. code:: python

    class Migration(migrations.Migration):
        operations = [
            RemoveField('model', 'field'),
        ]

.. code:: python

    from syzygy import Stage

    class Migration(migrations.Migration):
        stage = Stage.POST_DEPLOY

        operations = [
            RunSQL(...),
        ]

In order to prevent the creation of migrations mixing operations of different
*stages* this package registers system checks. These checks will generate an error
for every migration with an ambiguous `stage`.

e.g. this migration would result in a check error

.. code:: python

    class Migration(migrations.Migration):
        operations = [
            AddField('model', 'other_field', models.IntegerField(null=True)),
            RemoveField('model', 'field'),
        ]

Migration revert are also supported and result in inverting the nature of
migrations. A migration that is normally considered a *prerequisite* would then
be *postponed* when reverted.

With this new notion of migration stage it's possible for the `migrate` command
to target only migrations meant to be run before a deployment using the
`--pre-deploy` flag or error out in the case on an ambiguous plan.

Development
-----------

Make your changes, and then run tests via tox:

.. code:: sh

    tox
