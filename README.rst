django-syzygy
=============

.. image:: https://github.com/charettes/django-syzygy/workflows/Test/badge.svg
    :target: https://github.com/charettes/django-syzygy/actions
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

Add ``'syzygy'`` to your ``INSTALLED_APPS``

.. code:: python

    # settings.py
    INSTALLED_APPS = [
        ...
        'syzygy',
        ...
    ]

Setup you deployment pipeline to run ``migrate --pre-deploy`` before rolling
out your code changes and ``migrate`` afterwards to apply the postponed
migrations.

Concept
-------

Syzygy introduces a notion of *prerequisite* and *postponed* migrations with
regards to deployment.

A migration is assumed to be a *prerequisite* to deployment unless it contains
a destructive operation or the migration has its ``stage`` class attribute set
to ``Stage.POST_DEPLOY``. When this attribute is defined it will bypass
``operations`` based heuristics.

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
for every migration with an ambiguous ``stage``.

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

Third-party migrations
----------------------

As long as the adoption of migration stages concept  not generalized your
project might depend on third-party apps containing migrations with an
ambiguous sequence of operations.

Since an explicit `stage` cannot be explicitly assigned by editing these
migrations a fallback or an override stage can be specified through the
respective ``MIGRATION_STAGES_FALLBACK`` and ``MIGRATION_STAGES_OVERRIDE``
settings.

By default third-party app migrations with an ambiguous sequence of operations
will fallback to ``Stage.PRE_DEPLOY`` but this behavior can be changed by
setting ``MIGRATION_THIRD_PARTY_STAGES_FALLBACK`` to ``Stage.POST_DEPLOY`` or
disabled by setting it to ``None``.

.. note::

  The third-party app detection logic relies on the ``site`` `Python module`_
  and is known to not properly detect all kind of third-party Django
  applications. You should rely on ``MIGRATION_STAGES_FALLBACK`` and
  ``MIGRATION_STAGES_OVERRIDE`` to configure stages if it doesn't work for your
  setup.

.. _`Python module`: https://docs.python.org/3/library/site.html

Migration quorum
----------------

When deploying migrations to multiple clusters sharing the same database it's
important that:

1. Migrations are applied only once
2. Pre-deployment migrations are applied before deployment in any clusters is
   takes place
3. Post-deployment migrations are only applied once all clusters are done
   deploying

The built-in ``migrate`` command doesn't offer any guarantees with regards to
serializability of invocations, in other words naively calling ``migrate`` from
multiple clusters before or after a deployment could cause some migrations to
be attempted to be applied twice.

To circumvent this limitation Syzygy introduces a ``--quorum <N:int>`` flag to the
``migrate`` command that allow clusters coordination to take place.

When specified the ``migrate --quorum <N:int>`` command will wait for at least
``N`` number invocations of ``migrate`` for the planned migrations before proceeding
with applying them once and blocking on all callers until the operation completes.

In order to use the ``--quorum`` feature you must configure ``MIGRATE_QUORUM_BACKEND``
to point to a quorum backend such as cache based one provided by Sygyzy

.. code:: python

    # settings.py

    MIGRATE_QUORUM_BACKEND = 'syzygy.quorum.backends.cache.CacheQuorum'

	# or

    CACHES = {
        ...,
        'quorum',
    }
	MIGRATE_QUORUM_BACKEND = {
        'backend': 'syzygy.quorum.backends.cache.CacheQuorum',
        'alias': 'quorum',
	}

.. note::

  In order for ``CacheQuorum`` to work properly in a distributed environment it
  must be pointed at a backend that supports atomic ``incr`` operations such as
  Memcached or Redis.


Development
-----------

Make your changes, and then run tests via tox:

.. code:: sh

    tox
