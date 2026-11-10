"""The page around every module, the registrations it is drawn from, and the
door to everything behind the login."""

from __future__ import annotations

import re
from contextlib import AsyncExitStack, asynccontextmanager
lazy import asyncio
lazy import json
lazy import mimetypes
lazy from collections.abc import AsyncIterator, Mapping, Sequence
lazy from hashlib import blake2b
lazy from importlib.resources import files
lazy from pathlib import Path
lazy from typing import Any

lazy from bazaar_contrib_http import Http
lazy from bazaar_contrib_storage import Database
lazy from jinja2 import PackageLoader
lazy from pydantic import BaseModel, ConfigDict, Field, ValidationError
lazy from starlette.applications import Starlette
lazy from starlette.datastructures import MutableHeaders
lazy from starlette.exceptions import HTTPException
lazy from starlette.requests import HTTPConnection, Request
lazy from starlette.responses import (
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
lazy from starlette.routing import Route
lazy from starlette.staticfiles import StaticFiles
lazy from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .contracts import (
    NAME,
    RESERVED,
    Account,
    Admitted,
    Appearance,
    Login,
    PermissionItem,
    SettingsItem,
    SidebarItem,
    SidebarPanel,
    Topic,
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
        self._panels: list[SidebarPanel] = []
        self._topics: dict[str, Topic] = {}
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
        icons = resources / "templates" / "server" / "icons"
        appearance = await asyncio.to_thread(
            (icons / "sun.svg").read_text, encoding="utf-8"
        )
        async with (
            self._http.route("/", self._home, methods=["GET"]),
            # answered before the files of the same directory
            self._http.route("/static/server/theme.css", self._theme, methods=["GET"]),
            self.module(
                "server",
                api=Starlette(routes=[Route("/poll", self._poll, methods=["POST"])]),
                static=Path(str(resources / "static")),
                locales=Path(str(resources / "locales")),
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
            self.module(
                "appearance",
                ui=self._own.application(
                    [
                        Route("/", self._appearance_page),
                        Route("/", self._appearance_save, methods=["POST"]),
                    ]
                ),
            ),
            self.settings(
                SettingsItem(
                    key="appearance",
                    title="server.appearance",
                    icon=appearance,
                    group="server.settings.personal",
                    description="server.appearance.description",
                    src="/ui/appearance/",
                )
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
    async def panel(self, item: SidebarPanel) -> AsyncIterator[None]:
        if any(registered.key == item.key for registered in self._panels):
            raise ValueError(f"sidebar panel {item.key!r} is already registered")
        self._panels.append(item)
        try:
            yield
        finally:
            self._panels.remove(item)

    @asynccontextmanager
    async def topic(self, topic: Topic) -> AsyncIterator[None]:
        if topic.name in self._topics:
            raise ValueError(f"topic {topic.name!r} is already registered")
        self._topics[topic.name] = topic
        try:
            yield
        finally:
            del self._topics[topic.name]

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

    async def admit(self, connection: HTTPConnection) -> Admitted | Response:
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
        """The first place in the account's sidebar, or its settings."""
        answer = await self.admit(request)
        if isinstance(answer, Response):
            return answer
        entries, _ = self._sidebar_of(answer.account)
        response = RedirectResponse(
            next(
                (item.path for _, item, _ in entries if isinstance(item, SidebarItem)),
                "/settings",
            )
        )
        for name, value in answer.headers:
            response.headers.append(name, value)
        return response

    async def _theme(self, request: Request) -> Response:
        del request
        return Response(
            self._style,
            media_type="text/css",
            headers={"Cache-Control": "no-cache"},
        )

    def _sidebar_of(
        self, account: Account
    ) -> tuple[
        list[tuple[str, SidebarItem | SidebarPanel, str | None]], list[SidebarPanel]
    ]:
        """What the account's sidebar holds: links and panels under their
        groups, with the heading a group opens with, each group where its
        first entry would be; and the panels at the top."""

        def visible(item: SidebarItem | SidebarPanel) -> bool:
            return item.permission is None or account.allows(item.permission)

        grouped: list[SidebarItem | SidebarPanel] = sorted(
            [item for item in self._sidebar if visible(item)]
            + [panel for panel in self._panels if panel.group and visible(panel)],
            key=lambda item: item.order,
        )
        first: dict[str, int] = {}
        for place, item in enumerate(grouped):
            first.setdefault(item.group or "", place)
        entries: list[tuple[str, SidebarItem | SidebarPanel, str | None]] = []
        opened: set[str] = set()
        for item in sorted(grouped, key=lambda item: first[item.group or ""]):
            group = item.group or ""
            kind = "link" if isinstance(item, SidebarItem) else "panel"
            entries.append((kind, item, None if group in opened else group))
            opened.add(group)
        top = sorted(
            (panel for panel in self._panels if not panel.group and visible(panel)),
            key=lambda panel: panel.order,
        )
        return entries, top

    async def _shell(self, request: Request) -> Response:
        answer = await self.admit(request)
        if isinstance(answer, Response):
            response = answer
        else:
            account = request.state.account = answer.account
            module, _, rest = request.url.path.removeprefix("/").partition("/")
            query = f"?{request.url.query}" if request.url.query else ""
            current = f"/{module}/{rest}"
            entries, top = self._sidebar_of(account)
            links = [item for _, item, _ in entries if isinstance(item, SidebarItem)]
            # a bottom bar holds five; with more, the fifth opens the rest
            crowded = len(links) + 1 > 5
            split = (
                entries.index(next(entry for entry in entries if entry[1] is links[4]))
                if crowded
                else len(entries)
            )
            response = await self._own.render(
                request,
                "server/shell.html",
                src=f"/ui/{module}/{rest}{query}",
                entries=entries,
                split=split,
                crowded=crowded,
                top=top,
                # the groups holding a link, whose heading stays whatever their panels draw
                linked={item.group for item in links},
                # on a narrow screen, every panel in the strip above the bar
                strip=top + [item for kind, item, _ in entries if kind == "panel"],
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
            for name, value in answer.headers:
                response.headers.append(name, value)
        for name, value in _PERSONAL.items():
            response.headers.setdefault(name, value)
        return response

    async def _poll(self, request: Request) -> Response:
        """One check of everything a window follows: the states changed since
        it last saw them, and what it may no longer see."""
        account: Account = request.state.account
        if request.headers.get("X-Build") not in (None, self.build):
            return JSONResponse({"stale": True})
        try:
            asked = _Poll.model_validate_json(await request.body())
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        states: dict[str, Mapping[str, object] | None] = {}
        changes: list[dict[str, object]] = []
        for subscription in asked.subscriptions:
            key = json.dumps([subscription.topic, subscription.scope], sort_keys=True)
            if key not in states:
                topic = self._topics.get(subscription.topic)
                states[key] = (
                    None
                    if topic is None
                    or set(subscription.scope) != set(topic.fields)
                    or (
                        topic.permission is not None
                        and not account.allows(topic.permission)
                    )
                    else await topic.fetch(account, subscription.scope)
                )
            state = states[key]
            if state is None:
                changes.append({"id": subscription.id, "unavailable": True})
            elif state != subscription.seen:
                changes.append({"id": subscription.id, "state": state})
        return JSONResponse({"changes": changes})

    async def _appearance_page(self, request: Request) -> Response:
        return await self._own.render(
            request, "server/appearance.html", themes=self.themes.themes
        )

    async def _appearance_save(self, request: Request) -> Response:
        account: Account = request.state.account
        try:
            # an empty choice is no choice: the browser's language, the system's look
            appearance = Appearance.model_validate(
                {key: value or None for key, value in (await request.form()).items()}
            )
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if self._login is None:
            raise HTTPException(status_code=503)
        await self._login.dress(account.id, appearance)
        # the shell around the page wears the old look until it is drawn again
        return Response(status_code=204, headers={"HX-Trigger": "dressed"})

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
            src=(f"{part.src.rstrip('/')}/{rest}" if rest else part.src) + query,
        )


class _Subscription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)
    topic: str = Field(max_length=200)
    scope: dict[str, str] = Field(default_factory=dict)
    seen: Any = None


class _Poll(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscriptions: list[_Subscription] = Field(max_length=500)


class _Gate:
    """The door to an application: the login module says who a request is
    from before anything behind it is reached."""

    def __init__(self, shell: Shell, app: ASGIApp, *, public: bool = False) -> None:
        self._shell = shell
        self._app = app
        self._public = public

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        started = False
        carried: tuple[tuple[str, str], ...] = ()

        async def sending(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = MutableHeaders(scope=message)
                for name, value in carried:
                    headers.append(name, value)
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
                scope.setdefault("state", {})["account"] = answer.account
                carried = answer.headers
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
