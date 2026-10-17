from __future__ import annotations

from contextlib import asynccontextmanager
lazy from pathlib import Path

from bazaar_contrib_node_migrations import NODE_MIGRATIONS, migrations
from bazaar_contrib_schema import SCHEMA, schema
from bazaar_contrib_sqlite import sqlite
from bazaar_contrib_storage import DB, Database, Insert, Select, database, storage
from bazaar_core import Composition, Context, Contrib, ContribEntry, ContribHub

from bazaar_contrib_server import SERVER_MIGRATIONS
from bazaar_contrib_server import migrations as server_migrations


async def test_business_roots_select_only_their_migration_plugin(tmp_path: Path):
    services: list[Database] = []
    registered: list[tuple[str, ...]] = []

    @asynccontextmanager
    async def node_consumer(ctx: Context):
        ctx.accept(NODE_MIGRATIONS)
        db = ctx.accept(DB)
        services.append(db)
        registered.append(
            tuple(module.package for module in ctx.accept(SCHEMA).modules)
        )
        await db.insert(
            Insert(
                table="settings",
                rows=(
                    {
                        "agent_id": "agent",
                        "key": "welcome",
                        "value": "Ready after Node migration",
                        "updated_at_ms": 1,
                    },
                ),
            )
        )
        yield

    @asynccontextmanager
    async def server_consumer(ctx: Context):
        ctx.accept(SERVER_MIGRATIONS)
        db = ctx.accept(DB)
        services.append(db)
        registered.append(
            tuple(module.package for module in ctx.accept(SCHEMA).modules)
        )
        await db.insert(
            Insert(
                table="computers",
                rows=(
                    {
                        "id": "computer",
                        "name": "Ready after Server migration",
                        "secret_hash": "test-only",
                        "created_at_ms": 1,
                    },
                ),
            )
        )
        yield

    composition = Composition(
        entries=(
            ContribEntry(name="storage", definition=storage),
            ContribEntry(
                name="sqlite",
                definition=sqlite,
                config={"path": tmp_path / "selected.sqlite3"},
            ),
            ContribEntry(
                name="database", definition=database, config={"backend": "sqlite"}
            ),
            ContribEntry(name="schema", definition=schema),
            ContribEntry(name="node-migrations", definition=migrations),
            ContribEntry(name="server-migrations", definition=server_migrations),
            ContribEntry(
                name="node",
                definition=Contrib(
                    accepts=[DB, SCHEMA, NODE_MIGRATIONS], lifespan=node_consumer
                ),
            ),
            ContribEntry(
                name="server",
                definition=Contrib(
                    accepts=[DB, SCHEMA, SERVER_MIGRATIONS], lifespan=server_consumer
                ),
            ),
        ),
        roots=("node",),
    )
    async with ContribHub() as hub, hub.enable(composition) as enabled:
        assert registered[-1] == ("bazaar-contrib-node-migrations",)
        assert (await services[-1].select(Select(table="settings")))[0][
            "value"
        ] == "Ready after Node migration"
        await enabled.update(composition.model_copy(update={"roots": ("server",)}))
        assert registered[-1] == ("bazaar-contrib-server",)
        assert (await services[-1].select(Select(table="computers")))[0][
            "name"
        ] == "Ready after Server migration"
        assert (await services[-1].select(Select(table="settings")))[0][
            "value"
        ] == "Ready after Node migration"
