"""Exception hierarchy for DeckForge.

All errors raised by DeckForge derive from :class:`DeckForgeError`, so callers
can catch a single base class. Subclasses signal the layer where the problem
occurred (package, template parsing, slide building, JSON spec).
"""

from __future__ import annotations


class DeckForgeError(Exception):
    """Base class for every error raised by DeckForge."""


class PackageError(DeckForgeError):
    """ZIP/OPC-level problem (bad zip, missing part, malformed rels/content types)."""


class ParseError(DeckForgeError):
    """Malformed or unsupported template content (XML, theme, master, layout)."""


class BuildError(DeckForgeError):
    """Invalid build-time input while constructing slides, shapes, or media."""


class SpecError(DeckForgeError):
    """Invalid JSON deck specification."""
