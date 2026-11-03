"""Record one migration as applied without running it.

The migrate step runs this in a child process under the service's settings,
for a spec entry that sets ``fake``::

    DJANGO_SETTINGS_MODULE=lms.envs.aqueduct \\
        python -m lehrer_bootstrap.fake_migration submissions 0006_mariadb_uuid_conversion default

It applies everything the migration depends on first, so the record does not
claim a schema that is not there. ``migrate <app> <target>`` cannot do that
part: on a database that has already applied a later sibling of the target, it
migrates the app *backwards* to it. Prints :data:`UNCHANGED` on stdout when
the migration was already recorded.
"""

from __future__ import annotations

import sys

UNCHANGED = "lehrer_bootstrap: migration already applied"


def fake(app_label: str, name: str, database: str) -> bool:
    """Apply what ``app_label.name`` depends on, then record it as applied.

    :returns: whether this recorded it, i.e. it was not applied before.
    """
    import django  # type: ignore[import-not-found]  # noqa: PLC0415

    django.setup()
    from django.db import connections  # type: ignore[import-not-found]  # noqa: PLC0415
    from django.db.migrations.executor import (  # type: ignore[import-not-found]  # noqa: PLC0415
        MigrationExecutor,
    )

    executor = MigrationExecutor(connections[database])
    graph = executor.loader.graph
    applied = executor.loader.applied_migrations
    key = (app_label, name)
    if key in applied:
        return False
    if key not in graph.nodes:
        msg = f"no migration {app_label}.{name}; fake takes the full name"
        raise ValueError(msg)
    # Every unapplied ancestor, which is a forwards-only plan by construction.
    # executor.migrate runs it in the graph's order, not this list's.
    needed = {
        node
        for parent in graph.node_map[key].parents
        for node in graph.forwards_plan(parent.key)
        if node not in applied
    }
    if needed:
        executor.migrate(
            targets=None, plan=[(graph.nodes[node], False) for node in needed]
        )
    executor.recorder.record_applied(app_label, name)
    return True


def main(argv: list[str]) -> int:
    app_label, name, database = argv
    if not fake(app_label, name, database):
        print(UNCHANGED)  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
