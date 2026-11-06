"""What modules, login modules and theme plugins hold the server to."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
lazy from collections.abc import Awaitable, Callable, Mapping, Sequence
lazy from contextlib import AbstractAsyncContextManager
lazy from pathlib import Path

from bazaar_core import ServiceKey
from pydantic import BaseModel, ConfigDict, Field
lazy from starlette.requests import HTTPConnection
lazy from starlette.responses import Response
lazy from starlette.types import ASGIApp

from .i18n import Language
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
    """A link in the sidebar, for the accounts holding its permission point,
    under its group's heading; links naming the same group share it."""

    text: str
    # an SVG icon stroked in currentColor, as lucide's are
    icon: str
    path: str
    # the heading's text key; the server's own are server.sidebar.workbench and server.sidebar.extensions
    group: str
    permission: str | None = None
    order: int = 0
    # the update bus topic whose state is the badge beside the link
    badge: str | None = None


class SidebarPanel(_Item):
    """A module's own section of the sidebar, its page loaded in an iframe:
    under its group's heading, or at the top when it names no group; on a
    narrow screen, in the strip above the bottom bar."""

    key: str = Field(pattern=NAME)
    src: str
    group: str | None = None
    permission: str | None = None
    order: int = 0


@dataclass(frozen=True, slots=True)
class Topic:
    """What pages and the sidebar follow through the update bus. Its state is
    fetched for an account and a scope naming the fields it takes; nothing
    when the account may not see it. A badge topic's state is its text and
    kind: count, unread or soon."""

    name: str
    fetch: Callable[
        [Account, Mapping[str, str]], Awaitable[Mapping[str, object] | None]
    ]
    fields: tuple[str, ...] = ()
    permission: str | None = None


class SettingsItem(_Item):
    """A part of the settings page, loaded in an iframe; it is listed under
    its group's heading, with its icon, and on a narrow screen with a line
    saying what it holds."""

    key: str = Field(pattern=NAME)
    title: str
    # an SVG icon stroked in currentColor, as lucide's are
    icon: str
    # the heading's text key; the server's own are server.settings.personal and server.settings.admin
    group: str
    description: str = ""
    src: str
    permission: str | None = None
    admin: bool = False


class PermissionItem(_Item):
    """A permission point, written module.action; it is also its text key."""

    point: str = Field(pattern=r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*$")
    description: str


class Tokens(_Item):
    """Every value a theme sets, named as in the approved tokens.css; the
    scene_ ones colour the market street on the login page."""

    bg: str
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
    scene_sky: str
    scene_star: str
    scene_moon: str
    scene_bite: str
    scene_far: str
    scene_far_roof: str
    scene_window: str
    scene_cord: str
    scene_cap: str
    scene_wood: str
    scene_wood_light: str
    scene_wood_shade: str
    scene_inside: str
    scene_inside_shade: str
    scene_alt: str
    scene_glow: str
    scene_bulb: str
    scene_ground: str
    scene_ground_light: str
    scene_ground_shade: str
    scene_pot: str
    scene_steam: str
    scene_far_fade: str


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
    def name(self) -> str:
        """What pages call the account."""
        ...

    @property
    def avatar(self) -> str | None:
        """The address of the account's picture, when it has one."""
        ...

    @property
    def theme(self) -> Literal["light", "dark"] | None:
        """Always the day theme, always the night theme, or nothing to follow
        the system."""
        ...

    @property
    def day_theme(self) -> str | None: ...

    @property
    def night_theme(self) -> str | None: ...

    @property
    def language(self) -> str | None: ...

    @property
    def admin(self) -> bool: ...

    def allows(self, point: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class Admitted:
    """The account a request is from, and headers its answer carries along,
    such as the cookie of a session the login module renewed on the way."""

    account: Account
    headers: tuple[tuple[str, str], ...] = ()


class Appearance(_Item):
    """How an account's pages look and what language they speak; nothing
    chosen follows the browser and the system."""

    language: Language | None = None
    theme: Literal["light", "dark"] | None = None
    day_theme: str | None = Field(default=None, pattern=NAME)
    night_theme: str | None = Field(default=None, pattern=NAME)


class Login(Protocol):
    """The module that says who a request is from; one at a time."""

    @property
    def app(self) -> ASGIApp:
        """Served at /login to anyone; signing out is a POST to /login/logout."""
        ...

    async def account(self, connection: HTTPConnection) -> Admitted | Response:
        """The account a request or a WebSocket is from, or the answer it
        gets instead."""
        ...

    async def dress(self, account_id: str, appearance: Appearance) -> None:
        """Keep how the account's pages look from now on."""
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

    def panel(self, item: SidebarPanel) -> AbstractAsyncContextManager[None]: ...

    def topic(self, topic: Topic) -> AbstractAsyncContextManager[None]:
        """Let pages and the sidebar follow the topic through the update bus."""
        ...

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
