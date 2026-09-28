"""The contract for migrations this fork adds on top of upstream's chain.

Upstream numbers its migrations sequentially from 0001 and never renames a shipped
one. A migration this fork adds is numbered from 8001 instead, so an upstream sync
can never mint the same number and force a rename. A rename is what does the harm:
the migration re-runs on every database that applied it under the old id, and the
old id stays in that database's ledger, where the preset engine reads it as a
migration from a newer build and rejects every snapshot cloned from that database
on the merge and upload paths.

Two rules keep a fork id stable for good, and the tests below hold them:

* A shipped fork migration is never renamed or deleted. When its feature lands
  upstream under one of upstream's numbers, the fork file stays and ``migrate``
  becomes a no-op, so every ledger that recorded the id still names a migration
  this build ships.
* A fork migration changes nothing in a database that already has its effect,
  because it guards on the effect itself and not on the ledger. That is what makes
  it harmless next to upstream's copy of the same change, whichever runs first.
"""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path

import pytest

from backend.database.migrations import MIGRATIONS
from backend.features.presets import engine

# Every fork migration id this fork has shipped. Append only.
_SHIPPED = ("8001_direction_notes_enabled", "8002_director_individual_speakers", "8003_endpoint_profiles")


def _fork_migrations() -> list[str]:
    return [name for name in MIGRATIONS if "8000" <= name[:4] < "9000"]


def test_every_shipped_fork_migration_still_has_its_file():
    missing = [name for name in _SHIPPED if name not in MIGRATIONS]
    assert not missing, (
        f"fork migrations renamed or deleted: {missing}. Databases that applied them keep the id in "
        "schema_migrations, and the preset engine then rejects their snapshots as made by a newer build. "
        "Restore the file under its shipped name; if upstream now carries the change, reduce migrate() to a no-op."
    )


def test_every_fork_migration_is_listed_as_shipped():
    unlisted = [name for name in _fork_migrations() if name not in _SHIPPED]
    assert not unlisted, f"add {unlisted} to _SHIPPED so a later rename or deletion fails the check above"


def _state(conn: sqlite3.Connection) -> dict:
    """Everything a re-run could disturb: schema objects, every row, and the preset
    engine's verdict on the schema."""
    objects = conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name").fetchall()
    rows = {
        name: sorted(conn.execute(f'SELECT * FROM "{name}"').fetchall(), key=repr)  # nosec B608 -- from sqlite_master
        for kind, name, _table, _sql in objects
        if kind == "table"
    }
    return {"objects": objects, "rows": rows, "gate": engine.schema_safety_problems(conn)}


@pytest.mark.parametrize("name", _fork_migrations())
async def test_fork_migration_changes_nothing_in_a_current_database(name: str, db_path: Path):
    """The seeded template only proves the guards hold against the current schema. A
    fork migration that transforms rows needs its own re-run test over representative
    data."""
    conn = sqlite3.connect(db_path)
    try:
        before = _state(conn)
        importlib.import_module(f"backend.database.migrations.{name}").migrate(conn)
        conn.commit()
        assert _state(conn) == before
    finally:
        conn.close()
