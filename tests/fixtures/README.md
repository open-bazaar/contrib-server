# Published Server databases

These SQL dumps preserve databases produced by the original Server migration runner in
[BCN commit 074cdd8](https://github.com/yuchanns/bazaar-compute-node/tree/074cdd847ef0afcc409e494a771f9ed9170301da/src/bazaar_compute_server/contrib/sqlite/migrations).

`server-v3.sql` contains computers, accounts, roles, account-role assignments and an OIDC provider after the first three published migrations.
`server-v7.sql` is the same database upgraded through all seven published migrations by that runner.

The regression restores these snapshots into temporary databases, compares the upgraded business data and retains the original version ledger.
Keep this released bridge fixed when adding new migrations.
