"""What modules, login modules and theme plugins hold the server to."""

from __future__ import annotations

from typing import Literal, Protocol
lazy from collections.abc import Sequence
lazy from contextlib import AbstractAsyncContextManager
lazy from pathlib import Path

from bazaar_core import ServiceKey
from pydantic import BaseModel, ConfigDict, Field
lazy from starlette.requests import HTTPConnection
lazy from starlette.responses import Response
lazy from starlette.types import ASGIApp

lazy from .i18n import Translator
lazy from .pages import Pages
lazy from .refs import Refs

# one segment of an address, and a name a stylesheet can select on
NAME = r"^[a-z][a-z0-9-]*$"
# the addresses the server and the modules behind them answer themselves
RESERVED = frozenset({"ui", "api", "static", "login", "starlink"})


class _Item(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SidebarItem(_Item):
    """A link in the sidebar, for the accounts holding its permission point."""

    text: str
    # an SVG icon stroked in currentColor, as lucide's are
    icon: str
    path: str
    permission: str | None = None
    order: int = 0


class OverviewItem(_Item):
    """Content of the overview, loaded in an iframe."""

    key: str = Field(pattern=NAME)
    title: str
    src: str
    permission: str | None = None


class SettingsItem(_Item):
    """A part of the settings page, loaded in an iframe."""

    key: str = Field(pattern=NAME)
    title: str
    src: str
    permission: str | None = None
    admin: bool = False


class PermissionItem(_Item):
    """A permission point, written module.action; it is also its text key."""

    point: str = Field(pattern=r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*$")
    description: str


class Tokens(_Item):
    """Every value a theme sets, named as in the approved tokens.css."""

    bg: str
    bg_glow: str
    side_bg: str
    surface: str
    surface_2: str
    raised: str
    sunken: str
    line: str
    line_soft: str
    line_strong: str
    text: str
    text_2: str
    muted: str
    faint: str
    saffron: str
    saffron_ink: str
    saffron_soft: str
    saffron_line: str
    ember: str
    jade: str
    jade_soft: str
    crimson: str
    crimson_soft: str
    indigo: str
    indigo_soft: str
    plum: str
    plum_soft: str
    shadow: str
    codex: str


class Theme(_Item):
    """A look; its styles apply only while it is the page's theme."""

    name: str = Field(pattern=NAME)
    # what the theme is called, by language
    labels: dict[str, str] = Field(min_length=1)
    scheme: Literal["light", "dark"]
    tokens: Tokens
    styles: str = ""


class Account(Protocol):
    """Who a request is from, as the login module says."""

    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def theme(self) -> str | None: ...

    @property
    def language(self) -> str | None: ...

    @property
    def admin(self) -> bool: ...

    def allows(self, point: str) -> bool: ...


class Login(Protocol):
    """The module that says who a request is from; one at a time."""

    @property
    def app(self) -> ASGIApp:
        """Served at /login to anyone; signing out is a POST to /login/logout."""
        ...

    async def account(self, connection: HTTPConnection) -> Account | Response:
        """The account a request or a WebSocket is from, or the answer it
        gets instead."""
        ...


class Themes(Protocol):
    def register(self, theme: Theme) -> AbstractAsyncContextManager[None]:
        """Offer the theme while open."""
        ...


class Server(Protocol):
    """Where modules put their pages, links and permission points; each
    registration holds while its context is open."""

    @property
    def refs(self) -> Refs: ...

    @property
    def permissions(self) -> Sequence[PermissionItem]: ...

    def module(
        self,
        name: str,
        *,
        ui: ASGIApp | None = None,
        api: ASGIApp | None = None,
        static: Path | None = None,
        locales: Path | None = None,
    ) -> AbstractAsyncContextManager[None]:
        """Serve the module's interface at /ui/<name> inside the shell at
        /<name>, its API at /api/<name> and its files at /static/<name>; its
        locales directory holds en.toml and zh-CN.toml."""
        ...

    def sidebar(self, item: SidebarItem) -> AbstractAsyncContextManager[None]: ...

    def overview(self, item: OverviewItem) -> AbstractAsyncContextManager[None]: ...

    def settings(self, item: SettingsItem) -> AbstractAsyncContextManager[None]: ...

    def permission(self, item: PermissionItem) -> AbstractAsyncContextManager[None]: ...

    def login(self, login: Login) -> AbstractAsyncContextManager[None]: ...

    async def pages(self, module: str, package: str) -> Pages:
        """Jinja pages on the server's base template, from the package's
        templates directory."""
        ...

    def translator(self, connection: HTTPConnection) -> Translator: ...


SERVER = ServiceKey[Server]("server")
THEME = ServiceKey[Themes]("server.theme")
