"""Short numbers for the long values a link would otherwise carry: a uuid, a
target, whatever a page names an object by. The table behind them does not
know what a value is; the code that puts a number in a link does."""

from __future__ import annotations

lazy from collections.abc import Iterable, Sequence
lazy from typing import cast

lazy from bazaar_contrib_storage import (
    Column,
    Conflict,
    Database,
    In,
    Insert,
    Record,
    Select,
    Session,
)

# how many digits a number can have: the table's are 64-bit
_DIGITS = 18


class Refs:
    """The numbers, kept in the process once seen: a value's number never
    changes, so what was read once holds for good."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._by_value: dict[str, int] = {}
        self._by_ref: dict[int, str] = {}

    async def load(self, values: Iterable[str]) -> None:
        """Have a number for each of these values, before a page names them."""
        unknown = tuple(dict.fromkeys(v for v in values if v not in self._by_value))
        if not unknown:
            return

        async def number(session: Session) -> tuple[Record, ...]:
            # a value seen before keeps its number; the rest take the next
            await session.insert(
                Insert(
                    table="refs",
                    rows=tuple({"value": value} for value in unknown),
                    conflict=Conflict(columns=("value",)),
                )
            )
            return await session.select(
                Select(
                    table="refs",
                    where=In(expression=Column(name="value"), values=unknown),
                )
            )

        self._keep(await self._database.transaction(number))

    def ref(self, value: str) -> int:
        """The number a loaded value goes by."""
        return self._by_value[value]

    async def expand(self, refs: Sequence[int]) -> list[str | None]:
        """The values behind numbers a link brought back; nothing for a
        number that was never given."""
        unknown = tuple(dict.fromkeys(r for r in refs if r not in self._by_ref))
        if unknown:
            self._keep(
                await self._database.read(
                    lambda session: session.select(
                        Select(
                            table="refs",
                            where=In(expression=Column(name="id"), values=unknown),
                        )
                    )
                )
            )
        return [self._by_ref.get(ref) for ref in refs]

    async def values(self, shorts: Sequence[str]) -> list[str] | None:
        """What the numbers in a link stand for, as the link spells them;
        nothing at all when one is not a number or stands for nothing."""
        # decimal digits only, and no more of them than a number can have
        if not all(short.isdecimal() and len(short) <= _DIGITS for short in shorts):
            return None
        found = await self.expand([int(short) for short in shorts])
        if None in found:
            return None
        return [value for value in found if value is not None]

    def _keep(self, rows: Iterable[Record]) -> None:
        for row in rows:
            value, ref = cast(str, row["value"]), cast(int, row["id"])
            self._by_value[value] = ref
            self._by_ref[ref] = value
