"""The shell over real HTTP, with the real database and themes behind it."""

from __future__ import annotations

from contextlib import asynccontextmanager
lazy import asyncio
lazy import sqlite3
lazy import tomllib
lazy from collections.abc import AsyncIterator, Callable
lazy from contextlib import closing
lazy from importlib.resources import files
lazy from pathlib import Path
lazy from typing import Any

import httpx
import pytest
from bazaar_contrib_http import HTTP
from bazaar_core import (
    Composition,
    Context,
    Contrib,
    ContribEntry,
    ContribHub,
    ContribSpec,
    Stopping,
    load,
)
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from bazaar_contrib_server import SERVER, THEME, Server, Theme

SERVER_ENTRIES = (
    ("timer-wheel", {}),
    ("http", {"listen": "127.0.0.1:0"}),
    ("server-database", {}),
    ("server-migrations", {}),
    ("server", {}),
    ("server-theme-night", {}),
    ("server-theme-day", {}),
)


def entry(name: str, accepts: list[Any], lifespan: Callable[..., Any]) -> ContribEntry:
    return ContribEntry(
        name=name,
        definition=Contrib(accepts=accepts, lifespan=asynccontextmanager(lifespan)),
    )


@asynccontextmanager
async def running() -> AsyncIterator[tuple[ContribHub, Server, str]]:
    """The server's entries as installed, with what they offer."""
    found: dict[str, Any] = {}

    async def look(ctx: Context):
        found["server"], found["url"] = ctx.accept(SERVER), ctx.accept(HTTP).url
        yield

    composition = await asyncio.to_thread(
        load,
        [ContribSpec(contrib=name, config=config) for name, config in SERVER_ENTRIES],
    )
    composition = composition.model_copy(
        update={"entries": (*composition.entries, entry("look", [SERVER, HTTP], look))}
    )
    async with ContribHub() as hub, hub.enable(composition):
        yield hub, found["server"], found["url"]


@asynccontextmanager
async def client() -> AsyncIterator[httpx.AsyncClient]:
    # building the client loads certificates from disk, which is not the loop's work
    async with await asyncio.to_thread(httpx.AsyncClient, timeout=30) as session:
        yield session


async def night() -> Theme:
    """The night market server-theme-night registers."""
    path = files("bazaar_contrib_server") / "resources" / "themes" / "night.toml"
    return Theme.model_validate(
        tomllib.loads(await asyncio.to_thread(path.read_text, encoding="utf-8"))
    )


def tables(path: Path) -> set[str]:
    with closing(sqlite3.connect(path)) as connection:
        return {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }


async def test_the_shell_serves_its_files_and_embedding_tools_to_anyone():
    async with running() as (_, _, url), client() as session:
        embed = await session.get(f"{url}/static/server/embed.js")
        assert embed.status_code == 200
        assert "postMessage" in embed.text
        font = await session.get(
            f"{url}/static/server/fonts/inter-latin-wght-normal.woff2"
        )
        assert font.status_code == 200
        style = await session.get(f"{url}/static/server/theme.css")
        assert style.status_code == 200
        assert style.headers["content-type"].startswith("text/css")
        for theme in ("night", "day"):
            assert f':root[data-theme="{theme}"]' in style.text
        assert "--saffron:" in style.text
        assert ".btn" in style.text


async def test_a_registered_theme_is_in_the_stylesheet_until_it_is_withdrawn():
    harbor = (await night()).model_copy(
        update={"name": "harbor", "labels": {"en": "Harbor"}}
    )

    async def register(ctx: Context):
        async with ctx.accept(THEME).register(harbor):
            yield

    async with running() as (hub, _, url), client() as session:
        async with hub.enable(
            Composition(entries=[entry("harbor", [THEME], register)])
        ):
            offered = await session.get(f"{url}/static/server/theme.css")
            assert ':root[data-theme="harbor"]' in offered.text
        withdrawn = await session.get(f"{url}/static/server/theme.css")
        assert ':root[data-theme="harbor"]' not in withdrawn.text
        assert ':root[data-theme="night"]' in withdrawn.text


async def test_a_theme_without_every_token_is_refused():
    night_market = await night()
    tokens = night_market.tokens.model_dump()
    del tokens["saffron"]
    with pytest.raises(ValidationError, match="saffron"):
        Theme.model_validate(
            night_market.model_dump() | {"name": "plain", "tokens": tokens}
        )


async def test_reserved_and_taken_names_cannot_name_a_module(tmp_path: Path):
    async def notes(request: Request) -> PlainTextResponse:
        return PlainTextResponse("notes")

    def taking(name: str) -> ContribEntry:
        async def lifespan(ctx: Context):
            async with ctx.accept(SERVER).module(
                name, ui=Starlette(routes=[Route("/", notes)])
            ):
                yield

        return entry(f"takes-{name}", [SERVER], lifespan)

    names = ("ui", "api", "static", "login", "starlink", "overview", "Notes")
    async with (
        running() as (hub, _, url),
        client() as session,
        hub.enable(
            Composition(entries=[taking(name) for name in names], isolate_errors=True)
        ),
    ):
        failed = {
            record.name
            for record in hub.snapshots
            if isinstance(record.state, Stopping) and record.state.error
        }
        assert {f"takes-{name}" for name in names} <= failed
        assert (await session.get(f"{url}/ui/api/")).status_code == 404
        assert (await session.get(f"{url}/Notes")).status_code == 404


async def test_pages_and_apis_behind_the_login_are_refused_without_a_login_module(
    tmp_path: Path,
):
    static = tmp_path / "notes-static"
    await asyncio.to_thread(static.mkdir)
    await asyncio.to_thread((static / "note.txt").write_text, "a note")

    async def page(request: Request) -> PlainTextResponse:
        return PlainTextResponse("notes")

    async def items(request: Request) -> JSONResponse:
        return JSONResponse([])

    async def live(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.close()

    async def module(ctx: Context):
        async with ctx.accept(SERVER).module(
            "notes",
            ui=Starlette(routes=[Route("/", page), WebSocketRoute("/live", live)]),
            api=Starlette(routes=[Route("/items", items, methods=["GET", "POST"])]),
            static=static,
        ):
            yield

    async with (
        running() as (hub, _, url),
        client() as session,
        hub.enable(Composition(entries=[entry("notes", [SERVER], module)])),
    ):
        for method, path in (
            ("GET", "/notes"),
            ("GET", "/notes/today"),
            ("GET", "/ui/notes/"),
            ("GET", "/api/notes/items"),
            ("POST", "/api/notes/items"),
            ("GET", "/overview"),
            ("GET", "/settings"),
            ("GET", "/ui/overview/"),
        ):
            refused = await session.request(method, f"{url}{path}")
            assert refused.status_code == 503, path
            assert (
                "frame-ancestors 'self'" in refused.headers["content-security-policy"]
            )
            assert "no-store" in refused.headers["cache-control"]
        with pytest.raises(InvalidStatus) as refused:
            async with connect(f"ws{url.removeprefix('http')}/ui/notes/live"):
                pass
        assert refused.value.response.status_code == 503
        note = await session.get(f"{url}/static/notes/note.txt")
        assert note.status_code == 200
        assert "a note" in note.text


async def test_refs_keep_the_numbers_a_published_database_gave(home: Path):
    data = home / ".bcn"
    dump = await asyncio.to_thread(
        (Path(__file__).parent / "fixtures" / "server-v7.sql").read_text,
        encoding="utf-8",
    )

    def restore() -> None:
        data.mkdir(parents=True)
        with closing(sqlite3.connect(data / "bcs.sqlite3")) as connection:
            connection.executescript(dump)
            connection.execute("INSERT INTO refs (id, value) VALUES (41, 'agent:kana')")
            connection.commit()

    await asyncio.to_thread(restore)
    async with running() as (_, server, _):
        await server.refs.load(["agent:kana", "agent:aqua"])
        assert server.refs.ref("agent:kana") == 41
        assert server.refs.ref("agent:aqua") != 41
        assert await server.refs.values(["41"]) == ["agent:kana"]
        assert await server.refs.values([str(server.refs.ref("agent:aqua"))]) == [
            "agent:aqua"
        ]
        assert await server.refs.values(["41", "4041"]) is None
        assert await server.refs.values(["agent:kana"]) is None

    assert {"refs", "overview_order", "accounts"} <= await asyncio.to_thread(
        tables, data / "bcs.sqlite3"
    )


async def test_a_new_server_database_gets_the_shell_tables(home: Path):
    async with running():
        pass

    assert {"refs", "overview_order"} <= await asyncio.to_thread(
        tables, home / ".bcn" / "bcs.sqlite3"
    )
