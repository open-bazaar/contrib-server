# bazaar-contrib-server

The Bazaar Compute server itself. The `server` entry draws the shell around every module — the sidebar and the settings page — and offers `SERVER`, where modules register their pages, API, sidebar links and panels, update topics and permission points, and `THEME`, where theme contribs register the looks the pages can wear. The `server-theme-night` and `server-theme-day` entries are the theme plugins it comes with: the night market and the morning market.

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
                group="server.sidebar.workbench",
                permission="notes.view",
            )
        ),
    ):
        yield


notes = Contrib(accepts=[SERVER], lifespan=lifespan)
```

The icon is an SVG drawn as the design's are, with class `i` and a 24×24 view box. The module's interface is served at `/ui/notes` inside the shell at `/notes`, its API at `/api/notes` and its files at `/static/notes`. Its templates live in `resources/templates` of its package and extend `server/base.html`, which brings the theme stylesheet and the embedding script; pages of any other framework include `/static/server/theme.css` and `/static/server/embed.js` themselves. Everything behind the shell needs a login module, which registers itself with `server.login`; until one does, those pages and APIs answer 503.

The login module describes each request's account with `Account`: the name pages show, the address of its picture if it has one, its language, its theme mode and its day and night themes. It answers with `Admitted`, which also carries headers the response should get, such as the cookie of a session it renewed on the way. The settings page's appearance part, open to every account, lets the account choose the language, the theme mode and the day and night themes, and passes the choice to the login module's `dress`; the whole window is then drawn again in the new look. A day or night theme that is not registered falls back to the morning or the night market.

A page draws its own top bar from `server/base.html`: its title, a way back on a narrow screen (the `back` block), crumbs on a wide one (`crumbs`) and its actions (`actions`); a part of the settings page empties the `top` block. Sidebar links sit under their group's heading; links of different modules naming one group share it. A link may name an update topic as its `badge`, whose state is a text and a kind (`count`, `unread` or `soon`). `server.panel` adds a module's own section to the sidebar, its page loaded in an iframe under a group or at the top, and on a narrow screen in the strip above the bottom bar; the page draws itself for either layout. The overview is a module of its own, `server-overview`.

What changes while a page is open reaches it through the update bus, as 0.2's `/poll` did. A module registers a `Topic` with `server.topic`: its name, the scope fields it takes, its permission point and how to fetch its state for an account. An element naming `data-topic` (with `data-scope` and `data-seen` as JSON) is followed once its page loads, and hears `bazaar:change` when the state changes; scripts follow topics with `window.top.bazaarBus.follow`, which answers with the way to stop; a subscription given its `element` stops once the element leaves its page. The outermost window asks the server about everything its frames follow in one request a round.

Below 960 pixels the shell becomes one column with the sidebar as a bar along the bottom. Pages in its frames lay out as the shell does, not by their frame's width: `embed.js` marks their root `data-layout="narrow"` or `"wide"`, and their narrow-screen rules select on that. 
