"""Every module's words, in the language of whoever is looking."""

from __future__ import annotations

from dataclasses import dataclass, field
lazy import tomllib
lazy from collections.abc import Mapping
lazy from pathlib import Path

from jinja2 import Environment, StrictUndefined, Template

ENGLISH = "en"
SIMPLIFIED_CHINESE = "zh-CN"
LANGUAGES = (ENGLISH, SIMPLIFIED_CHINESE)

_environment = Environment(undefined=StrictUndefined, autoescape=False)


def catalogs(directory: Path) -> dict[str, dict[str, Template]]:
    """The languages a locales directory has, every entry a template."""
    return {
        language: {
            key: _environment.from_string(source)
            for key, source in tomllib.loads(path.read_text(encoding="utf-8")).items()
        }
        for language in LANGUAGES
        if (path := directory / f"{language}.toml").is_file()
    }


def language(chosen: str | None, accept_language: str | None) -> str:
    """The account's language, else the first one the browser asks for that
    the pages speak, else English."""
    if chosen in LANGUAGES:
        return chosen
    for part in (accept_language or "").split(","):
        tag = part.split(";")[0].strip().lower()
        if tag.startswith("zh"):
            return SIMPLIFIED_CHINESE
        if tag.startswith("en"):
            return ENGLISH
    return ENGLISH


@dataclass(frozen=True, slots=True)
class Translator:
    language: str
    _messages: Mapping[str, Template] = field(repr=False)

    def text(self, key: str, arguments: Mapping[str, object] | None = None) -> str:
        template = self._messages.get(key)
        if template is None:
            return key
        return template.render(**(arguments or {}))

    def has(self, key: str) -> bool:
        return key in self._messages


class Catalogs:
    """The registered modules' catalogs, merged per language."""

    def __init__(self) -> None:
        self._modules: dict[str, dict[str, dict[str, Template]]] = {}
        self._translators: dict[str, Translator] = {}

    def add(self, module: str, languages: dict[str, dict[str, Template]]) -> None:
        self._modules[module] = languages
        self._translators.clear()

    def remove(self, module: str) -> None:
        del self._modules[module]
        self._translators.clear()

    def translator(self, language: str) -> Translator:
        if language not in self._translators:
            messages: dict[str, Template] = {}
            for languages in self._modules.values():
                # a module that speaks one language is read in it
                messages |= languages.get(language) or next(
                    iter(languages.values()), {}
                )
            self._translators[language] = Translator(language, messages)
        return self._translators[language]
