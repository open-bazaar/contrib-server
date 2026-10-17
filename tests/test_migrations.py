from __future__ import annotations

lazy import asyncio
lazy from pathlib import Path

import aiosqlite
from bazaar_contrib_schema import ModuleSchema, Schema
from bazaar_contrib_sqlite import SqliteConfig, open_database
from bazaar_contrib_storage import Select

from bazaar_contrib_server import MODULE


async def test_published_auth_upgrade_preserves_business_data_and_original_ledger(
    tmp_path: Path,
):
    fixtures = (await asyncio.to_thread(Path(__file__).resolve)).parent / "fixtures"
    path = tmp_path / "server.sqlite3"
    expected = tmp_path / "expected.sqlite3"
    for target, version in ((path, 3), (expected, 7)):
        dump = await asyncio.to_thread((fixtures / f"server-v{version}.sql").read_text)
        async with aiosqlite.connect(target) as connection:
            await connection.executescript(dump)
    async with (
        open_database(SqliteConfig(path=path)) as database,
        open_database(SqliteConfig(path=expected)) as reference,
    ):
        original = await database.select(Select(table="schema_migrations"))
        # Keep the released bridge fixed when new business migrations are added.
        published = ModuleSchema(
            package=MODULE.package,
            tables=MODULE.tables,
            migrations=MODULE.migrations[:7],
            progress=MODULE.progress,
        )
        schema = Schema(database)
        await schema.start()
        async with schema.register(published):
            for table in published.tables:
                if await reference.table_exists(table):
                    rows = await database.select(Select(table=table))
                    expected_rows = await reference.select(Select(table=table))
                    assert sorted(map(repr, rows)) == sorted(
                        map(repr, expected_rows)
                    ), table
        assert await database.select(Select(table="schema_migrations")) == original


async def test_new_database_uses_current_baseline_and_retains_new_data(tmp_path: Path):
    from bazaar_contrib_storage import Insert

    path = tmp_path / "fresh.sqlite3"
    async with open_database(SqliteConfig(path=path)) as database:
        schema = Schema(database)
        await schema.start()
        async with schema.register(MODULE):
            await database.insert(
                Insert(
                    table="computers",
                    rows=(
                        {
                            "id": "computer",
                            "name": "Workshop",
                            "secret_hash": "test-only",
                            "created_at_ms": 1,
                        },
                    ),
                )
            )
        async with schema.register(MODULE):
            rows = await database.select(Select(table="computers"))
            assert rows
            history = await database.select(Select(table="contrib_schema_migrations"))
            assert len(history) == 1
            assert history[0]["version"] == MODULE.version
