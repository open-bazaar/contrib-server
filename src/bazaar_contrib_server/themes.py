"""The themes registered on the server."""

from __future__ import annotations

from contextlib import asynccontextmanager
lazy from collections.abc import AsyncIterator, Callable

from .contracts import Theme

# what 0.2 stored for an account's look
_LEGACY = {"light": "day", "dark": "night"}


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

    def chosen(self, name: str | None) -> str:
        """The registered theme an account chose, or nothing to follow the
        system."""
        name = _LEGACY.get(name or "", name or "")
        return name if any(theme.name == name for theme in self.themes) else ""

    def system(self) -> dict[str, str]:
        """The theme followed for a light and for a dark system: the first
        registered of that scheme, or the first of all."""
        return {
            scheme: next(
                (theme.name for theme in self.themes if theme.scheme == scheme),
                self.themes[0].name if self.themes else "",
            )
            for scheme in ("light", "dark")
        }
