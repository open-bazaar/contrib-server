# bazaar-contrib-server

The Bazaar Compute server itself. The `server` entry draws the shell around every module — the sidebar, the overview and the settings page — and offers `SERVER`, where modules register their pages, API and permission points, and `THEME`, where theme contribs register the looks the pages can wear. The `server-theme-night` and `server-theme-day` entries are the theme plugins it comes with: the night market and the morning market.

```toml
[[contribs]]
package = "bazaar-contrib-server~=0.3.0rc1"
[[contribs.enabled]]
entry = "server"
[[contribs.enabled]]
entry = "server-theme-night"
[[contribs.enabled]]
entry = "server-theme-day"
```

A module registers what it serves inside its lifespan; each registration holds while its context is open:

```python
import asyncio
from contextlib import asynccontextmanager

from bazaar_contrib_server import SERVER, PermissionItem, SidebarItem
from bazaar_core import Context, Contrib
from importlib.resources import files
from pathlib import Path
from starlette.routing import Route


@asynccontextmanager
async def lifespan(ctx: Context):
    server = ctx.accept(SERVER)
    pages = await server.pages("notes", __package__)

    async def home(request):
        return await pages.render(request, "notes.html")

    resources = Path(str(files(__package__))) / "resources"
    icon = await asyncio.to_thread((resources / "notes.svg").read_text)
    async with (
        server.module(
            "notes",
            ui=pages.application([Route("/", home)]),
            static=resources / "static",
            locales=resources / "locales",
        ),
        server.permission(
            PermissionItem(point="notes.view", description="notes.view.description")
        ),
        server.sidebar(
            SidebarItem(
                text="notes.title",
                icon=icon,
                path="/notes",
                permission="notes.view",
            )
        ),
    ):
        yield


notes = Contrib(accepts=[SERVER], lifespan=lifespan)
```

The icon is an SVG drawn as the design's are, with class `i` and a 24×24 view box. The module's interface is served at `/ui/notes` inside the shell at `/notes`, its API at `/api/notes` and its files at `/static/notes`. Its templates live in `resources/templates` of its package and extend `server/base.html`, which brings the theme stylesheet and the embedding script; pages of any other framework include `/static/server/theme.css` and `/static/server/embed.js` themselves. Everything behind the shell needs a login module, which registers itself with `server.login`; until one does, those pages and APIs answer 503.

Below 960 pixels the shell becomes one column with the sidebar as a bar along the bottom. Pages in its frames lay out as the shell does, not by their frame's width: `embed.js` marks their root `data-layout="narrow"` or `"wide"`, and their narrow-screen rules select on that. A page one level below another sets `data-back` on its root element to the address of the level above, through the `root` block of `server/base.html` or on its own `<html>`; there the shell's top bar shows a way back.
