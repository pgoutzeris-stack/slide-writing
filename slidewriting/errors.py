"""Exception hierarchy for Slide Writing.

All errors raised by Slide Writing derive from :class:`SlideWritingError`, so callers
can catch a single base class. Subclasses signal the layer where the problem
occurred (package, template parsing, slide building, JSON spec).
"""

from __future__ import annotations


class SlideWritingError(Exception):
    """Base class for every error raised by Slide Writing."""


class PackageError(SlideWritingError):
    """ZIP/OPC-level problem (bad zip, missing part, malformed rels/content types)."""


class ParseError(SlideWritingError):
    """Malformed or unsupported template content (XML, theme, master, layout)."""


class BuildError(SlideWritingError):
    """Invalid build-time input while constructing slides, shapes, or media."""


class SpecError(SlideWritingError):
    """Invalid JSON deck specification."""
