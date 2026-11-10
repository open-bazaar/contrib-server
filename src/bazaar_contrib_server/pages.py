"""A module's pages on the server's base template: the Jinja environment its
templates extend, the filters and globals 0.2's pages had, the ways the
pages write times, durations and token counts, and the answer an htmx
request from a page of another build gets."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal
lazy import asyncio
lazy from collections.abc import Sequence
lazy from datetime import datetime, tzinfo
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

lazy from .clock import calendar, clock_text, day_text, now_ms, time_text, zone
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
            "stamp": _stamp,
            "dated": _dated,
            "moment": _moment,
            "duration": _duration,
            "since": _since,
            "tokens": _tokens,
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

    async def zone(self, request: Request) -> tzinfo | None:
        """The viewer's zone, as the page says it or its browser left it;
        nothing when neither does, so each moment is read on the server's own
        clock."""
        # a zone is read from disk the first time it is named
        return await asyncio.to_thread(
            zone, request.headers.get("X-Timezone") or request.cookies.get("bcs_tz")
        )

    async def render(
        self, request: Request, template: str, *, status_code: int = 200, **values: Any
    ) -> HTMLResponse:
        """The template for whoever asked: not for any cache to keep, and a
        different body for htmx than for a browser loading it whole."""
        account = getattr(request.state, "account", None)
        system = (
            self._shell.themes.system(None, None)
            if account is None
            else self._shell.themes.system(account.day_theme, account.night_theme)
        )
        mode = None if account is None else account.theme
        viewer = {
            "account": account,
            "t": self._shell.translator(request),
            # nothing for a page that follows the system
            "theme": system[mode] if mode is not None else "",
            "system": system,
            "theme_bg": self._shell.themes.bg,
            "theme_scheme": self._shell.themes.scheme,
            "stylesheet": self._shell.stylesheet,
            "build": self.build,
            "server_build": self._shell.build,
            "request": request,
        }
        tz = await self.zone(request)
        # a template is read from disk the first time it is asked for
        body = await asyncio.to_thread(
            lambda: self.environment.get_template(template).render(
                **viewer, tz=tz, **values
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


def _distance(translator: Translator, at_ms: int, suffix: str) -> str:
    """How long since then in its largest unit, in the words of the page's
    translator whose keys end with the suffix."""
    seconds = max(0, (now_ms() - at_ms) // 1000)
    if seconds < 10:
        return translator.text("server.time.just_now")
    if seconds < 60:
        unit, n = "seconds", seconds
    elif seconds < 3600:
        unit, n = "minutes", seconds // 60
    elif seconds < 86400:
        unit, n = "hours", seconds // 3600
    else:
        unit, n = "days", seconds // 86400
    return translator.text(f"server.time.{unit}{suffix}", {"n": n})


@pass_context
def _ago(context: Context, at_ms: int) -> str:
    """How long ago, as 2 分钟前."""
    return _distance(context["t"], at_ms, "_ago")


@pass_context
def _since(context: Context, at_ms: int) -> str:
    """How long since then, without the ago: 刚刚, 2 分钟, 2 小时."""
    return _distance(context["t"], at_ms, "")


# the words for the days around today, by how far they are from it
_NEAR = {-1: "server.yesterday", 0: "server.today", 1: "server.tomorrow"}


def _date(translator: Translator, moment: datetime, this_year: bool) -> str:
    """A day by its date, with its year when that is not this one."""
    return translator.text(
        "server.date" if this_year else "server.date.year",
        {"year": moment.year, "month": moment.month, "day": moment.day},
    )


@pass_context
def _stamp(context: Context, at_ms: int) -> str:
    """When something in a list happened: its time today, yesterday by
    name, any other day by its date."""
    translator: Translator = context["t"]
    moment, days, this_year = calendar(at_ms, context["tz"])
    if days == 0:
        return moment.strftime("%H:%M")
    if days == -1:
        return translator.text("server.yesterday")
    return _date(translator, moment, this_year)


@pass_context
def _dated(context: Context, at_ms: int) -> str:
    """The heading of a day's part of a list: today and yesterday named
    before their date, any other day by its date alone."""
    translator: Translator = context["t"]
    moment, days, this_year = calendar(at_ms, context["tz"])
    date = _date(translator, moment, this_year)
    if days not in (-1, 0):
        return date
    return translator.text(
        "server.dated", {"word": translator.text(_NEAR[days]), "date": date}
    )


@pass_context
def _moment(context: Context, at_ms: int) -> str:
    """A moment by its day and time: today and tomorrow by name with the
    time, any other day by its date alone."""
    translator: Translator = context["t"]
    moment, days, this_year = calendar(at_ms, context["tz"])
    if days not in (0, 1):
        return _date(translator, moment, this_year)
    return translator.text(
        "server.moment",
        {"word": translator.text(_NEAR[days]), "time": moment.strftime("%H:%M")},
    )


@pass_context
def _duration(
    context: Context, ms: int, form: Literal["text", "compact", "timer"] = "text"
) -> str:
    """How long something lasted: in words as 1 分 48 秒, compact as 3m10s,
    or as a timer reads, 03:12; under ten seconds, to a tenth of one."""
    hours, rest = divmod(ms // 1000, 3600)
    minutes, seconds = divmod(rest, 60)
    if form == "timer":
        return (
            f"{hours}:{minutes:02}:{seconds:02}"
            if hours
            else f"{minutes:02}:{seconds:02}"
        )
    if ms < 10_000:
        tenths = f"{ms / 1000:.1f}".removesuffix(".0")
        compact, key, values = f"{tenths}s", "seconds", {"n": tenths}
    elif hours:
        compact, key, values = (
            f"{hours}h{minutes:02}m",
            "hours",
            {"h": hours, "m": minutes},
        )
    elif minutes:
        compact, key, values = (
            f"{minutes}m{seconds:02}s",
            "minutes",
            {"m": minutes, "s": seconds},
        )
    else:
        compact, key, values = f"{seconds}s", "seconds", {"n": seconds}
    if form == "compact":
        return compact
    translator: Translator = context["t"]
    return translator.text(f"server.duration.{key}", values)


def _tokens(count: int) -> str:
    """A count of tokens: as it is under a hundred, in thousands to a tenth
    under a hundred thousand, in whole thousands under a million, and in
    millions to a hundredth from there."""
    if count < 100:
        return str(count)
    if count < 100_000:
        return f"{count / 1000:.1f}".removesuffix(".0") + "k"
    if (thousands := round(count / 1000)) < 1000:
        return f"{thousands}k"
    return f"{count / 1_000_000:.2f}M"


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
