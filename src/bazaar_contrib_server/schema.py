"""The server's own tables: refs, taken over from the published history, and
the order each account gave the overview."""

import bazaar_contrib_storage as s
from bazaar_contrib_schema import Dependency, Migration, ModuleSchema

REFS = s.Table(
    name="refs",
    columns=(
        s.ColumnDefinition(name="id", type="integer", nullable=True, generated=True),
        s.ColumnDefinition(name="value", type="text", unique=True),
    ),
    primary_key=("id",),
)
OVERVIEW_ORDER = s.Table(
    name="overview_order",
    columns=(
        s.ColumnDefinition(name="account_id", type="text"),
        s.ColumnDefinition(name="key", type="text"),
        s.ColumnDefinition(name="position", type="integer"),
    ),
    primary_key=("account_id", "key"),
)

BASELINE = Migration(
    version=1, name="server_schema", operations=(s.CreateTable(table=REFS),)
)

MODULE = ModuleSchema(
    tables=("refs", "overview_order"),
    migrations=(
        BASELINE,
        Migration(
            version=2,
            name="overview_order",
            operations=(s.CreateTable(table=OVERVIEW_ORDER),),
        ),
    ),
    baseline=BASELINE,
    predecessor=Dependency(package="bazaar-contrib-server-migrations", version=7),
)
