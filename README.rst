django-syzygy
=============

.. image:: https://github.com/charettes/django-syzygy/actions/workflows/test.yml/badge.svg?branch=master
    :target: https://github.com/charettes/django-syzygy/actions?query=branch%3Amaster
    :alt: Build Status

.. image:: https://coveralls.io/repos/github/charettes/django-syzygy/badge.svg?branch=master
    :target: https://coveralls.io/github/charettes/django-syzygy?branch=master
    :alt: Coverage status


Django application providing database migration tooling to automate their deployment.

Inspired by a `2015 post from Ludwig Hähne`_ and experience dealing with migration at Zapier_.

.. _`2015 post from Ludwig Hähne`: https://pankrat.github.io/2015/django-migrations-without-downtimes/#django-wishlist
.. _Zapier: https://zapier.com

Currently only tested against PostgreSQL, SQLite, and MySQL.

Note that while MySQL is supported it doesn't support transactional DDL meaning
it will `require manual intervention if a migration fails to apply`_ which makes
problematic to use in an automated CI/CD setup.

.. _`require manual intervention if a migration fails to apply`: https://docs.djangoproject.com/en/5.1/topics/migrations/#mysql

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

When dealing with database migrations in the context of an highly available
application managed through continuous deployment the Django migration
leaves a lot to be desired in terms of the sequencing of operations it
generates.

The automatically generated schema alterations for field additions, removals,
renames, and others do not account for deployments where versions of the old
and the new code must co-exist for a short period of time.

For example, adding a field with a ``default`` does not persist a database
level default which prevents ``INSERT`` from the pre-existing code which
ignores the existence of tentatively added field from succeeding.

Figuring out the proper sequencing of operations is doable but non-trivial and
error prone. Syzygy ought to provide a solution to this problem by introducing
a notion of *prerequisite* and *postponed* migrations with regards to
deployment and generating migrations that are aware of this sequencing.

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

To take advantage of this new notion of migration stage the `migrate` command
allows migrations meant to be run before a deployment to be targeted using
`--pre-deploy` flag.

What it does and doesn't do
---------------------------

It does
^^^^^^^
- Introduce a notion of pre and post-deployment migrations and support their
  creation, management, and deployment sequencing through adjustments made to
  the ``makemigrations`` and ``migrate`` command.
- Automatically split operations known to cause deployment sequencing issues
  in pre and post deployment stages.
- Refuse the temptation to guess in the face of ambiguity and force developers
  to reflect about the sequencing of their operations when dealing with
  non-trival changes. It is meant to provide guardrails with safe quality of
  life defaults.

It doesn't
^^^^^^^^^^
- Generate operations that are guaranteed to minimize contention on your
  database. You should investigate the usage of `database specific solutions`_
  for that.
- Allow developers to completely abstract the notion of sequencing of
  of operations. There are changes that are inherently unsafe or not deployable
  in an atomic manner and you should be prepared to deal with them.

.. _`database specific solutions`: https://pypi.org/project/django-pg-zero-downtime-migrations/

Specialized operations
----------------------

Syzygy overrides the ``makemigrations`` command to automatically split
and organize operations in a way that allows them to safely be applied
in pre and post-deployment stages. 

Field addition
^^^^^^^^^^^^^^

When adding a field to an existing model Django will generate an
``AddField`` operation that roughly translates to the following SQL

.. code:: sql

    ALTER TABLE "author" ADD COLUMN "dob" int NOT NULL DEFAULT 1988;
    ALTER TABLE "author" ALTER COLUMN "dob" DROP DEFAULT;

Which isn't safe as the immediate removal of the database level ``DEFAULT``
prevents the code deployed at the time of migration application from inserting
new records.

In order to make this change safe syzygy splits the operation in two, a
specialized ``AddField`` operation that performs the column addition without
the ``DROP DEFAULT`` and follow up ``PostAddField`` operation that drops the
database level default. The first is marked as ``Stage.PRE_DEPLOY`` and the
second as ``Stage.POST_DEPLOY``.

.. note::

    On Django 5.0+ the specialized operations are respectively replaced by
    vanilla ``AddField`` and ``AlterField`` ones that make use of the newly
    introduced support for ``db_default`` feature.

Field removal
^^^^^^^^^^^^^

When removing a field from an existing model Django will generate a
``RemoveField`` operation that roughly translates to the following SQL

.. code:: sql

    ALTER TABLE "author" DROP COLUMN "dob";

Such operation cannot be run before deployment because it would cause
any ``SELECT``, ``INSERT``, and ``UPDATE`` initiated by the pre-existing code
to crash while doing it after deployment would cause ``INSERT`` crashes in the
newly-deployed code that _forgot_ the existence of the field.

In order to make this change safe syzygy splits the operation in two, a
specialized ``PreRemoveField`` operation adds a database level ``DEFAULT`` to
the column if a ``Field.default`` is present or make the field nullable
otherwise and a second vanilla ``RemoveField`` operation. The first is marked as
``Stage.PRE_DEPLOY`` and the second as ``Stage.POST_DEPLOY`` just like any
``RemoveField``.

The presence of a database level ``DEFAULT`` or the removal of the ``NOT NULL``
constraint ensures a smooth rollout sequence.

.. note::

    On Django 5.0+ the specialized ``PreRemoveField`` operation is replaced by
    a vanilla ``AlterField`` that make use of the newly introduced support for
    ``db_default`` feature.

Checks
------

In order to prevent the creation of migrations mixing operations of different
*stages* this package registers `system checks`_. These checks will generate an error
for every migration with an ambiguous ``stage``.

e.g. a migration mixing inferred stages would result in a check error

.. code:: python

    class Migration(migrations.Migration):
        operations = [
            AddField('model', 'other_field', models.IntegerField(null=True)),
            RemoveField('model', 'field'),
        ]

By default, syzygy should *not* generate automatically migrations and you should
only run into check failures when manually creating migrations or adding syzygy
to an historical project.

For migrations that are part of your project and trigger a failure of this check
it is recommended to manually annotate them with proper ``stage: syzygy.stageStage``
annotations. For third party migrations you should refer to the following section.

.. _`system checks`: https://docs.djangoproject.com/en/stable/topics/checks/

Third-party migrations
----------------------

As long as the adoption of migration stages concept is not generalized your
project might depend on third-party apps containing migrations with an
ambiguous sequence of operations.

Since an explicit ``stage`` cannot be explicitly assigned by editing these
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

Reverts
-------

Migration revert are also supported and result in inverting the nature of
migrations. A migration that is normally considered a *prerequisite* would then
be *postponed* when reverted.

CI Integration
--------------

In order to ensure that no feature branch includes an ambiguous sequence of
operations users are encouraged to include a job that attempts to run the
``migrate --pre-deploy`` command against a database that only includes the
changes from the target branch.

For example, given a feature branch ``add-shiny-feature`` and a target branch
of ``main`` a script would look like

.. code:: sh

    git checkout main
    python manage.py migrate
    git checkout add-shiny-feature
    python manage.py migrate --pre-deploy

Assuming the feature branch contains a sequence of operations that cannot be
applied in a single atomic deployment consisting of pre-deployment, deployment,
and post-deployment stages the ``migrate --pre-deploy`` command will fail with
an ``AmbiguousPlan`` exception detailing the ambiguity and resolution paths.

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

In order to use the ``--quorum`` feature you must configure the ``MIGRATION_QUORUM_BACKEND``
setting to point to a quorum backend such as cache based one provided by Sygyzy

.. code:: python

    MIGRATION_QUORUM_BACKEND = 'syzygy.quorum.backends.cache.CacheQuorum'

or

.. code:: python

    CACHES = {
        ...,
        'quorum': {
            ...
        },
    }
    MIGRATION_QUORUM_BACKEND = {
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
