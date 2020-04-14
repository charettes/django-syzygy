django-syzygy
=============

.. image:: https://travis-ci.org/charettes/django-syzygy.svg?branch=master
    :target: https://travis-ci.org/charettes/django-syzygy
    :alt: Build Status

.. image:: https://coveralls.io/repos/github/charettes/django-syzygy/badge.svg?branch=master
    :target: https://coveralls.io/github/charettes/django-syzygy?branch=master
    :alt: Coverage status


Django application providing database migration tooling to automate their deployment.

Installation
------------

.. code:: sh

    pip install django-syzygy

Concept
-------

Syzygy introduces a notion of _prerequisite_ and _postponed_ migrations with
regards to deployment.

A migration is assumed to be a _prerequisite_ unless it contains a destructive
operation or the migration has its `postpone` class attribute set to `True`.
When this boolean attribute is defined it will bypass `operations` based
heuristics.

e.g. this migration would be considered a _prerequisite_

.. code:: python

    class Migration(migrations.Migration):
        operations = [
            AddField('model', 'field', models.IntegerField(null=True))
        ]

while the following migrations would be _postponed_

.. code:: python

    class Migration(migrations.Migration):
        operations = [
            RemoveField('model', 'field'),
        ]

In order to prevent the creation of migrations mixing operations of different
nature this package registers system checks. These checks will generate an error
for every migration not explicitly tagged using the `postpone` class attribute
that contains an ambiguous sequence of operations.

e.g. this migration would result in a check error

.. code:: python

    class Migration(migrations.Migration):
        operations = [
            AddField('model', 'other_field', models.IntegerField(null=True)),
            RemoveField('model', 'field'),
        ]

Migration revert are also supported and result in inverting the nature of
migrations. A migration that is normally considered a _prerequisite_ would then
be _postponed_ when reverted.

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

Setup you deployment pipeline to run `migrate --prerequisite` before rolling
out your code changes and `migrate` afterwards to apply the postponed
migrations.

Development
-----------

Make your changes, and then run tests via tox:

.. code:: sh

    tox
