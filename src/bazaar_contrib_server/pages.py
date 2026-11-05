"""A module's pages on the server's base template: the Jinja environment its
templates extend, the filters and globals 0.2's pages had, and the answer an
htmx request from a page of another build gets."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
lazy import asyncio
lazy from collections.abc import Sequence
lazy from datetime import tzinfo
lazy from hashlib import blake2b
lazy from importlib.resources import files

from jinja2 import pass_context
lazy from jinja2 import (
    BaseLoader,
    ChoiceLoader,
    Environment,
    PackageLoader,
    StrictUndefined,
    select_autoescape,
)
lazy from jinja2.runtime import Context
lazy from markupsafe import Markup
lazy from starlette.applications import Starlette
lazy from starlette.datastructures import Headers
lazy from starlette.exceptions import HTTPException
lazy from starlette.middleware import Middleware
lazy from starlette.requests import Request
lazy from starlette.responses import HTMLResponse, Response
lazy from starlette.routing import BaseRoute
lazy from starlette.types import ASGIApp, Receive, Scope, Send

lazy from .clock import clock_text, day_text, now_ms, time_text, zone
lazy from .i18n import LANGUAGES, Translator
lazy from .markdown import render

if TYPE_CHECKING:
    from .shell import Shell

# the package this module belongs to, whose templates every page extends
PACKAGE = __name__.rpartition(".")[0]


def build(*packages: str) -> str:
    """The packages - code, templates, stylesheets, scripts - as one digest: a
    page holding another is out of date as a whole, whatever piece of it asks."""
    digest = blake2b(digest_size=6)
    for package in packages:
        entries = [files(package)]
        while entries:
            entry = entries.pop()
            if entry.is_dir():
                if entry.name != "__pycache__":
                    entries.extend(sorted(entry.iterdir(), key=lambda e: e.name))
            else:
                digest.update(entry.read_bytes())
    return digest.hexdigest()


class Pages:
    """One module's templates, with the server's under server/."""

    def __init__(self, shell: Shell, module: str, loader: BaseLoader, build: str):
        self._shell = shell
        self._module = module
        self.build = build
        self.environment = Environment(
            loader=ChoiceLoader([loader, shell.loader]),
            undefined=StrictUndefined,
            autoescape=select_autoescape(("html",)),
            auto_reload=False,
        )
        self.environment.filters |= {
            "tint": tint,
            "ago": _ago,
            "clock": _clock,
            "day": _day,
            "time": _time,
            "markdown": _markdown,
        }
        self.environment.globals |= {
            "asset": self.asset,
            "ref": shell.refs.ref,
            "languages": LANGUAGES,
        }

    @classmethod
    async def open(cls, shell: Shell, module: str, package: str) -> Pages:
        loader, digest = await asyncio.to_thread(
            lambda: (
                PackageLoader(package, "resources/templates"),
                build(PACKAGE, package),
            )
        )
        return cls(shell, module, loader, digest)

    def asset(self, name: str, module: str | None = None) -> str:
        """Where a static file is, under an address that changes with its
        module's build, so a browser holding the last one comes for this one."""
        if module == "server":
            return f"/static/server/{name}?v={self._shell.build}"
        return f"/static/{module or self._module}/{name}?v={self.build}"

    async def render(
        self, request: Request, template: str, *, status_code: int = 200, **values: Any
    ) -> HTMLResponse:
        """The template for whoever asked: not for any cache to keep, and a
        different body for htmx than for a browser loading it whole."""
        account = getattr(request.state, "account", None)
        # the zone the page asks in, or the one its browser left in a cookie
        named = request.headers.get("X-Timezone") or request.cookies.get("bcs_tz")
        viewer = {
            "account": account,
            "t": self._shell.translator(request),
            "theme": self._shell.themes.chosen(
                None if account is None else account.theme
            ),
            "system": self._shell.themes.system(),
            "theme_bg": self._shell.themes.bg,
            "stylesheet": self._shell.stylesheet,
            "build": self.build,
            "request": request,
        }
        # a zone is read from disk the first time it is named
        body = await asyncio.to_thread(
            lambda: self.environment.get_template(template).render(
                **viewer, tz=zone(named), **values
            )
        )
        return HTMLResponse(
            body,
            status_code=status_code,
            headers={"Cache-Control": "private, no-store", "Vary": "HX-Request"},
        )

    def application(self, routes: Sequence[BaseRoute]) -> Starlette:
        """The module's interface: its routes, an error page for each failure,
        and a refresh asked of a page another build drew."""

        async def failed(request: Request, error: Exception) -> Response:
            status = error.status_code if isinstance(error, HTTPException) else 500
            return await self.render(
                request, "server/error.html", status_code=status, code=status
            )

        return Starlette(
            routes=list(routes),
            middleware=[Middleware(_Stale, build=self.build)],
            exception_handlers={HTTPException: failed, Exception: failed},
        )


class _Stale:
    """Tells a page from another build so, instead of handing it a piece of
    this one: what a piece needs may no longer be there."""

    def __init__(self, app: ASGIApp, build: str) -> None:
        self._app = app
        self._build = build

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = Headers(scope=scope)
            if headers.get("HX-Request") == "true" and headers.get("X-Build") not in (
                None,
                self._build,
            ):
                await Response(status_code=204, headers={"HX-Trigger": "stale"})(
                    scope, receive, send
                )
                return
        await self._app(scope, receive, send)


@pass_context
def _markdown(context: Context, text: str) -> Markup:
    """Markdown as HTML, its code blocks and pictures drawn by the module's
    own templates when it has them."""
    environment = context.environment
    code = environment.select_template(["code.html", "server/code.html"])
    image = environment.select_template(["image.html", "server/image.html"])
    return render(
        text,
        code=lambda content: code.render(**context.get_all(), code=content),
        image=lambda **fields: image.render(**context.get_all(), **fields),
    )


@pass_context
def _ago(context: Context, at_ms: int) -> str:
    """How long ago, in the words of the page's translator."""
    translator: Translator = context["t"]
    seconds = max(0, (now_ms() - at_ms) // 1000)
    if seconds < 10:
        return translator.text("server.time.just_now")
    if seconds < 60:
        return translator.text("server.time.seconds_ago", {"n": seconds})
    if seconds < 3600:
        return translator.text("server.time.minutes_ago", {"n": seconds // 60})
    if seconds < 86400:
        return translator.text("server.time.hours_ago", {"n": seconds // 3600})
    return translator.text("server.time.days_ago", {"n": seconds // 86400})


@pass_context
def _clock(context: Context, at_ms: int) -> str:
    """A time of day on the viewer's clock."""
    tz: tzinfo | None = context["tz"]
    return clock_text(at_ms, tz)


@pass_context
def _day(context: Context, at_ms: int) -> str:
    tz: tzinfo | None = context["tz"]
    return day_text(at_ms, tz)


@pass_context
def _time(context: Context, at_ms: int) -> str:
    tz: tzinfo | None = context["tz"]
    return time_text(at_ms, tz)


def tint(name: str) -> str:
    """The avatar colour a name keeps, one of the design's h1 to h6."""
    return f"h{blake2b(name.encode('utf-8'), digest_size=1).digest()[0] % 6 + 1}"
