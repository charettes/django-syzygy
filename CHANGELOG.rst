1.2.1
=====

:release-date: 2025-04-23

- Avoid unnecessary prompting for a default value on `ManyToManyField`
  removals. (#59)
- Address a ``makemigration`` crash when adding a ``ForeignKey`` with a
  callable ``default``. (#60)

1.2.0
=====

:release-date: 2025-02-03

- Add support for MySQL.
- Adjust `makemigrations` command to take advantage of auto-detector class. (#49)
- Add support for Django 5.2 and Python 3.13.
- Drop support for Python 3.8.
- Ensure staged renames and alters are properly serialized. (#52)
- Address improper handling of rename operation questioning. (#53)
- Address improper monkey-patching of `AlterField.migration_name_fragment`. (#56)

1.1.0
=====
:release-date: 2024-05-24

- Address typos in `AmbiguousPlan` error messages.
- Mention `MIGRATION_STAGES_OVERRIDE` on ambiguous plan involving third party apps.

1.0.1
=====
:release-date: 2024-04-13

- Avoid unnecessary two-step migration for nullable without default additions.
- Avoid splitting many-to-many field additions in stages. (#42)
- Adjust ambiguous stage auto-detection interactive questioning. (#44)

1.0.0
=====
:release-date: 2023-10-10

- Initial release
