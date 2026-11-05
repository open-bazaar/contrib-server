"""The page around every module, the registrations it is drawn from, and the
door to everything behind the login."""

from __future__ import annotations

import re
from contextlib import AsyncExitStack, asynccontextmanager
lazy import asyncio
lazy import mimetypes
lazy from collections.abc import AsyncIterator, Sequence
lazy from hashlib import blake2b
lazy from importlib.resources import files
lazy from pathlib import Path
lazy from typing import Literal, cast

lazy from bazaar_contrib_http import Http
lazy from bazaar_contrib_storage import (
    Column,
    Compare,
    Database,
    Delete,
    Insert,
    Select,
    Session,
    Value,
)
lazy from jinja2 import PackageLoader
lazy from pydantic import BaseModel, ValidationError
lazy from starlette.datastructures import MutableHeaders
lazy from starlette.exceptions import HTTPException
lazy from starlette.requests import HTTPConnection, Request
lazy from starlette.responses import PlainTextResponse, RedirectResponse, Response
lazy from starlette.routing import Route
lazy from starlette.staticfiles import StaticFiles
lazy from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .contracts import (
    NAME,
    RESERVED,
    Account,
    Login,
    OverviewItem,
    PermissionItem,
    SettingsItem,
    SidebarItem,
)
lazy from .i18n import Catalogs, Translator, catalogs, language
lazy from .pages import PACKAGE, Pages, build
lazy from .refs import Refs
lazy from .themes import ThemeRegistry

# the most any one request may carry; nothing a page sends comes close
MAX_BODY_BYTES = 1024 * 1024
# drawn for whoever asked and for this site's own frames only
_PERSONAL = {
    "Content-Security-Policy": "frame-ancestors 'self'",
    "Cache-Control": "private, no-store",
}


class Shell:
    """The server itself: what the modules registered, and the pages drawn
    from it."""

    def __init__(
        self,
        http: Http,
        database: Database,
        loader: PackageLoader,
        build: str,
        style: tuple[str, str],
    ) -> None:
        self._http = http
        self._database = database
        self.loader = loader
        self.build = build
        self.refs = Refs(database)
        self.themes = ThemeRegistry(self._restyle)
        self._catalogs = Catalogs()
        self._modules: set[str] = set()
        self._sidebar: list[SidebarItem] = []
        self._overview: list[OverviewItem] = []
        self._settings: list[SettingsItem] = []
        self._permissions: list[PermissionItem] = []
        self._login: Login | None = None
        self._own = Pages(self, "server", loader, build)
        source, self._base_style = style
        self._style_template = self._own.environment.from_string(source)
        self._style = ""
        self._style_version = ""
        self._restyle()

    @classmethod
    async def open(cls, http: Http, database: Database) -> Shell:
        def read() -> tuple[PackageLoader, str, tuple[str, str]]:
            # the first file served would otherwise read the system's types
            mimetypes.init()
            mimetypes.add_type("application/manifest+json", ".webmanifest")
            package = files(PACKAGE)
            style = (
                (
                    package / "resources" / "templates" / "server" / "theme.css"
                ).read_text(encoding="utf-8"),
                (package / "resources" / "static" / "base.css").read_text(
                    encoding="utf-8"
                ),
            )
            return (
                PackageLoader(PACKAGE, "resources/templates"),
                build(PACKAGE),
                style,
            )

        loader, digest, style = await asyncio.to_thread(read)
        return cls(http, database, loader, digest, style)

    @property
    def permissions(self) -> Sequence[PermissionItem]:
        return tuple(self._permissions)

    @property
    def stylesheet(self) -> str:
        return f"/static/server/theme.css?v={self._style_version}"

    @asynccontextmanager
    async def serving(self) -> AsyncIterator[None]:
        resources = files(PACKAGE) / "resources"
        overview = await asyncio.to_thread(
            (
                resources / "templates" / "server" / "icons" / "layout-dashboard.svg"
            ).read_text,
            encoding="utf-8",
        )
        async with (
            self._http.route("/", self._home, methods=["GET"]),
            # answered before the files of the same directory
            self._http.route("/static/server/theme.css", self._theme, methods=["GET"]),
            self.module(
                "server",
                static=Path(str(resources / "static")),
                locales=Path(str(resources / "locales")),
            ),
            self.module(
                "overview",
                ui=self._own.application(
                    [
                        Route("/", self._overview_page),
                        Route("/move", self._overview_move, methods=["POST"]),
                    ]
                ),
            ),
            self.module(
                "settings",
                ui=self._own.application(
                    [
                        Route("/", self._settings_page),
                        Route("/{key}", self._settings_page),
                        Route("/{key}/{rest:path}", self._settings_page),
                    ]
                ),
            ),
            self.sidebar(
                SidebarItem(text="server.overview", icon=overview, path="/overview")
            ),
        ):
            yield

    @asynccontextmanager
    async def module(
        self,
        name: str,
        *,
        ui: ASGIApp | None = None,
        api: ASGIApp | None = None,
        static: Path | None = None,
        locales: Path | None = None,
    ) -> AsyncIterator[None]:
        if not re.fullmatch(NAME, name) or name in RESERVED:
            raise ValueError(f"{name!r} cannot name a module")
        if name in self._modules:
            raise ValueError(f"module {name!r} is already registered")
        self._modules.add(name)
        try:
            async with AsyncExitStack() as stack:
                if locales is not None:
                    self._catalogs.add(name, await asyncio.to_thread(catalogs, locales))
                    stack.callback(self._catalogs.remove, name)
                if static is not None:
                    served = await asyncio.to_thread(StaticFiles, directory=static)
                    await stack.enter_async_context(
                        self._http.mount(f"/static/{name}", served)
                    )
                if ui is not None:
                    for path in (f"/{name}", f"/{name}/{{path:path}}"):
                        await stack.enter_async_context(
                            self._http.route(path, self._shell, methods=["GET"])
                        )
                    await stack.enter_async_context(
                        self._http.mount(f"/ui/{name}", _Gate(self, ui))
                    )
                if api is not None:
                    await stack.enter_async_context(
                        self._http.mount(f"/api/{name}", _Gate(self, api))
                    )
                yield
        finally:
            self._modules.discard(name)

    @asynccontextmanager
    async def sidebar(self, item: SidebarItem) -> AsyncIterator[None]:
        self._sidebar.append(item)
        try:
            yield
        finally:
            self._sidebar.remove(item)

    @asynccontextmanager
    async def overview(self, item: OverviewItem) -> AsyncIterator[None]:
        if any(registered.key == item.key for registered in self._overview):
            raise ValueError(f"overview content {item.key!r} is already registered")
        self._overview.append(item)
        try:
            yield
        finally:
            self._overview.remove(item)

    @asynccontextmanager
    async def settings(self, item: SettingsItem) -> AsyncIterator[None]:
        if any(registered.key == item.key for registered in self._settings):
            raise ValueError(f"settings part {item.key!r} is already registered")
        self._settings.append(item)
        try:
            yield
        finally:
            self._settings.remove(item)

    @asynccontextmanager
    async def permission(self, item: PermissionItem) -> AsyncIterator[None]:
        if any(registered.point == item.point for registered in self._permissions):
            raise ValueError(f"permission point {item.point!r} is already registered")
        self._permissions.append(item)
        try:
            yield
        finally:
            self._permissions.remove(item)

    @asynccontextmanager
    async def login(self, login: Login) -> AsyncIterator[None]:
        if self._login is not None:
            raise ValueError("a login module is already registered")
        self._login = login
        try:
            async with self._http.mount("/login", _Gate(self, login.app, public=True)):
                yield
        finally:
            self._login = None

    async def pages(self, module: str, package: str) -> Pages:
        return await Pages.open(self, module, package)

    def translator(self, connection: HTTPConnection) -> Translator:
        account: Account | None = getattr(connection.state, "account", None)
        return self._catalogs.translator(
            language(
                None if account is None else account.language,
                connection.headers.get("Accept-Language"),
            )
        )

    async def admit(self, connection: HTTPConnection) -> Account | Response:
        """Who a request or a WebSocket is from, or what it gets instead:
        nothing behind the login passes while there is no login module."""
        if self._login is None:
            return PlainTextResponse("No login module is enabled.", status_code=503)
        answer = await self._login.account(connection)
        if isinstance(answer, Response):
            return answer
        if not _same_origin(connection):
            # a session's cookie proves the browser, not the page that made
            # the browser send it; a write comes from this site's own pages
            return Response(status_code=403)
        return answer

    def _restyle(self) -> None:
        self._style = (
            self._style_template.render(themes=self.themes.themes) + self._base_style
        )
        self._style_version = blake2b(
            self._style.encode("utf-8"), digest_size=6
        ).hexdigest()

    async def _home(self, request: Request) -> Response:
        del request
        return RedirectResponse("/overview")

    async def _theme(self, request: Request) -> Response:
        del request
        return Response(
            self._style,
            media_type="text/css",
            headers={"Cache-Control": "no-cache"},
        )

    async def _shell(self, request: Request) -> Response:
        answer = await self.admit(request)
        if isinstance(answer, Response):
            response = answer
        else:
            request.state.account = answer
            module, _, rest = request.url.path.removeprefix("/").partition("/")
            query = f"?{request.url.query}" if request.url.query else ""
            current = f"/{module}/{rest}"
            links = sorted(
                (
                    item
                    for item in self._sidebar
                    if item.permission is None or answer.allows(item.permission)
                ),
                key=lambda item: item.order,
            )
            response = await self._own.render(
                request,
                "server/shell.html",
                src=f"/ui/{module}/{rest}{query}",
                links=links,
                active=max(
                    (
                        item.path
                        for item in links
                        if current.startswith(item.path.rstrip("/") + "/")
                    ),
                    key=len,
                    default=None,
                ),
            )
        for name, value in _PERSONAL.items():
            response.headers.setdefault(name, value)
        return response

    async def _ordered(self, account: Account) -> list[OverviewItem]:
        """The overview content the account may see, in the order it chose;
        what it never placed follows, in the order it was registered."""
        rows = await self._database.read(
            lambda session: session.select(
                Select(
                    table="overview_order",
                    where=Compare(
                        left=Column(name="account_id"),
                        operator="=",
                        right=Value(value=account.id),
                    ),
                )
            )
        )
        positions = {cast(str, row["key"]): cast(int, row["position"]) for row in rows}
        return sorted(
            (
                item
                for item in self._overview
                if item.permission is None or account.allows(item.permission)
            ),
            key=lambda item: (item.key not in positions, positions.get(item.key, 0)),
        )

    async def _overview_page(self, request: Request) -> Response:
        return await self._own.render(
            request,
            "server/overview.html",
            items=await self._ordered(request.state.account),
        )

    async def _overview_move(self, request: Request) -> Response:
        account: Account = request.state.account
        try:
            move = _Move.model_validate(dict(await request.form()))
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        items = await self._ordered(account)
        keys = [item.key for item in items]
        if move.key not in keys:
            raise HTTPException(status_code=404)
        index = keys.index(move.key)
        step = -1 if move.toward == "earlier" else 1
        items.insert(min(max(index + step, 0), len(items) - 1), items.pop(index))

        async def save(session: Session) -> None:
            mine = Compare(
                left=Column(name="account_id"),
                operator="=",
                right=Value(value=account.id),
            )
            await session.delete(Delete(table="overview_order", where=mine))
            await session.insert(
                Insert(
                    table="overview_order",
                    rows=tuple(
                        {"account_id": account.id, "key": item.key, "position": place}
                        for place, item in enumerate(items)
                    ),
                )
            )

        await self._database.transaction(save)
        return await self._own.render(
            request, "server/overview_board.html", items=items
        )

    async def _settings_page(self, request: Request) -> Response:
        account: Account = request.state.account
        parts = [
            item
            for item in self._settings
            if (
                account.admin
                if item.admin
                else item.permission is None or account.allows(item.permission)
            )
        ]
        # under each heading, in the order the parts were registered
        groups: dict[str, list[SettingsItem]] = {}
        for item in parts:
            groups.setdefault(item.group, []).append(item)
        key = request.path_params.get("key")
        if key is None:
            # the directory: a narrow screen shows it alone, a wide one beside
            # the first part
            part = parts[0] if parts else None
            return await self._own.render(
                request,
                "server/settings.html",
                groups=groups,
                part=part,
                view="directory",
                src=part.src if part else "",
            )
        part = next((item for item in parts if item.key == key), None)
        if part is None:
            raise HTTPException(status_code=404)
        rest = request.path_params.get("rest", "")
        query = f"?{request.url.query}" if request.url.query else ""
        return await self._own.render(
            request,
            "server/settings.html",
            groups=groups,
            part=part,
            view="part",
            src=part.src.rstrip("/") + (f"/{rest}" if rest else "") + query,
        )


class _Move(BaseModel):
    key: str
    toward: Literal["earlier", "later"]


class _Gate:
    """The door to an application: the login module says who a request is
    from before anything behind it is reached."""

    def __init__(self, shell: Shell, app: ASGIApp, *, public: bool = False) -> None:
        self._shell = shell
        self._app = app
        self._public = public

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        started = False

        async def sending(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = MutableHeaders(scope=message)
                for name, value in _PERSONAL.items():
                    headers.setdefault(name, value)
            await send(message)

        size = 0

        async def receiving() -> Message:
            # a request's body is counted through the limit before anything
            # parses it, and the application answers the limit as it answers
            # any HTTP error; a WebSocket's messages carry no body
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > MAX_BODY_BYTES:
                raise HTTPException(status_code=413)
            return message

        try:
            if not self._public:
                answer = await self._shell.admit(HTTPConnection(scope, receiving))
                if isinstance(answer, Response):
                    await answer(scope, receiving, sending)
                    return
                scope.setdefault("state", {})["account"] = answer
            await self._app(scope, receiving, sending)
        except HTTPException as error:
            # an application that answers no HTTP errors of its own
            if error.status_code != 413 or started:
                raise
            await Response(status_code=413)(scope, receive, sending)


def _same_origin(connection: HTTPConnection) -> bool:
    """Whether a request that changes something, or a WebSocket that stays
    open, came from this site: what the browser says of where it was sent
    from, when it says anything."""
    if connection.scope.get("method") in ("GET", "HEAD", "OPTIONS"):
        return True
    site = connection.headers.get("Sec-Fetch-Site")
    if site is not None:
        return site in ("same-origin", "none")
    origin = connection.headers.get("Origin")
    if origin is None:
        return True
    return origin.partition("://")[2] == connection.headers.get("Host", "")
