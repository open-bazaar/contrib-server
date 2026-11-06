"""The themes registered on the server."""

from __future__ import annotations

from contextlib import asynccontextmanager
lazy from collections.abc import AsyncIterator, Callable

from .contracts import Theme

# the morning and the night market, the day and night themes nobody chose
_DEFAULT = {"light": "day", "dark": "night"}


class ThemeRegistry:
    """The themes on offer, in the order they were registered."""

    def __init__(self, changed: Callable[[], None]) -> None:
        self.themes: list[Theme] = []
        self._changed = changed

    @asynccontextmanager
    async def register(self, theme: Theme) -> AsyncIterator[None]:
        if any(registered.name == theme.name for registered in self.themes):
            raise ValueError(f"theme {theme.name!r} is already registered")
        self.themes.append(theme)
        self._changed()
        try:
            yield
        finally:
            self.themes.remove(theme)
            self._changed()

    def bg(self, name: str) -> str:
        """The background a theme paints, for the browser's own chrome."""
        return next(
            (theme.tokens.bg for theme in self.themes if theme.name == name), ""
        )

    def system(self, day: str | None, night: str | None) -> dict[str, str]:
        """The themes worn by day and by night: the ones chosen while they are
        registered, else the morning and the night market, else the first
        registered of that scheme, or the first of all."""
        names = [theme.name for theme in self.themes]
        worn: dict[str, str] = {}
        for scheme, chosen in (("light", day), ("dark", night)):
            if chosen in names:
                worn[scheme] = chosen
            elif _DEFAULT[scheme] in names:
                worn[scheme] = _DEFAULT[scheme]
            else:
                worn[scheme] = next(
                    (theme.name for theme in self.themes if theme.scheme == scheme),
                    names[0] if names else "",
                )
        return worn
