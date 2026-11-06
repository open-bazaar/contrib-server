"""The server itself: the shell modules put their pages in, its registrations,
the themes, and the two themes it comes with."""

from __future__ import annotations

from contextlib import asynccontextmanager
lazy import asyncio
lazy import tomllib
lazy from collections.abc import AsyncIterator
lazy from importlib.resources import files

from bazaar_contrib_http import HTTP
from bazaar_contrib_server_database import SERVER_DB, SERVER_SCHEMA
from bazaar_contrib_server_migrations import SERVER_MIGRATIONS
from bazaar_core import Context, Contrib
lazy from starlette.exceptions import HTTPException
lazy from starlette.requests import HTTPConnection

from .contracts import (
    SERVER,
    THEME,
    Account,
    Admitted,
    Appearance,
    Login,
    PermissionItem,
    Server,
    SettingsItem,
    SidebarItem,
    SidebarPanel,
    Theme,
    Themes,
    Tokens,
    Topic,
)
lazy from .i18n import LANGUAGES, Translator
lazy from .pages import Pages
lazy from .refs import Refs
lazy from .schema import MODULE
lazy from .shell import Shell

__all__ = [
    "LANGUAGES",
    "SERVER",
    "THEME",
    "Account",
    "Admitted",
    "Appearance",
    "Login",
    "Pages",
    "PermissionItem",
    "Refs",
    "Server",
    "SettingsItem",
    "SidebarItem",
    "SidebarPanel",
    "Theme",
    "Themes",
    "Tokens",
    "Topic",
    "Translator",
    "account",
    "day",
    "night",
    "permitted",
    "server",
]


def account(connection: HTTPConnection) -> Account:
    """The account a request or a WebSocket behind the login is from; a
    FastAPI dependency."""
    return connection.state.account


def permitted(point: str):
    """A FastAPI dependency refusing accounts without the permission point."""

    def check(connection: HTTPConnection) -> None:
        if not account(connection).allows(point):
            raise HTTPException(status_code=403)

    return check


@asynccontextmanager
async def _server(ctx: Context) -> AsyncIterator[None]:
    async with ctx.accept(SERVER_SCHEMA).register(MODULE):
        shell = await Shell.open(ctx.accept(HTTP), ctx.accept(SERVER_DB))
        async with shell.serving():
            ctx.offer(SERVER, shell)
            ctx.offer(THEME, shell.themes)
            yield


def _theme(name: str) -> Contrib:
    """A theme plugin for the theme in resources/themes/<name>.toml."""

    @asynccontextmanager
    async def lifespan(ctx: Context) -> AsyncIterator[None]:
        path = files(__name__) / "resources" / "themes" / f"{name}.toml"
        theme = Theme.model_validate(
            tomllib.loads(await asyncio.to_thread(path.read_text, encoding="utf-8"))
        )
        async with ctx.accept(THEME).register(theme):
            yield

    return Contrib(accepts=[THEME], lifespan=lifespan)


server = Contrib(
    accepts=[HTTP, SERVER_DB, SERVER_SCHEMA, SERVER_MIGRATIONS],
    offers=[SERVER, THEME],
    lifespan=_server,
)
# the night market and the morning market of the approved design
night = _theme("night")
day = _theme("day")
