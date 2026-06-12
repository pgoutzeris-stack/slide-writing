"""High-level facade for Slide Writing: the :class:`Deck` class.

A :class:`Deck` wraps an OPC package plus its parsed design model
(:class:`~slidewriting.model.TemplateInfo`) and offers the three core
operations of the library:

* ``Deck.open(path)`` — load an existing ``.pptx`` template,
* ``Deck.create()`` — bootstrap a clean default template from scratch,
* ``deck.add_slide(...)`` / ``deck.save(path)`` — queue new slides built
  with :class:`~slidewriting.slide.SlideBuilder` and flush them into the
  package on save.

Slides are *queued*: ``add_slide`` returns a builder immediately and only
``save`` materializes the slide parts (via ``writer.SlideWriter``), sets
the core document properties, and writes the package to disk.
"""

from __future__ import annotations

import io
import os
from typing import Any, Union

from .errors import ParseError
from .model import LayoutSpec, MasterSpec, SlideInfo, TemplateInfo
from .opc import Package
from .parser import TemplateParser, slide_title_text
from .slide import SlideBuilder
from .theme import SCHEME_SLOTS, Theme
from .xmlcore import parse_xml

__all__ = ["Deck", "DEFAULT_DECK_TITLE"]

#: Core-properties title used when no deck title has been set.
DEFAULT_DECK_TITLE = "Slide Writing Präsentation"


class Deck:
    """A presentation under construction: template + queued new slides."""

    def __init__(self, package: Package, info: TemplateInfo) -> None:
        """Bind the deck to an opened package and its parsed design model.

        Use :meth:`open` or :meth:`create` instead of calling this directly.
        """
        self.package: Package = package
        self.info: TemplateInfo = info
        self._queued: list[tuple[SlideBuilder, str]] = []
        self._title: Union[str, None] = None
        self._author: Union[str, None] = None

    # --- constructors --------------------------------------------------------------

    @classmethod
    def open(cls, path: Union[str, os.PathLike, io.BytesIO]) -> "Deck":
        """Open an existing ``.pptx`` file (or file-like object) as a deck.

        The package is read via :meth:`slidewriting.opc.Package.open` and its
        design model is parsed with
        :class:`~slidewriting.parser.TemplateParser`. Raises
        :class:`~slidewriting.errors.PackageError` or
        :class:`~slidewriting.errors.ParseError` for unusable files.
        """
        package = Package.open(path)
        info = TemplateParser(package).parse()
        return cls(package, info)

    @classmethod
    def create(cls, accent: str = "206EFB", **kw: Any) -> "Deck":
        """Create a deck from the built-in bootstrap template.

        ``accent`` is the ``accent1`` theme color as ``"RRGGBB"`` hex;
        additional keyword arguments (``name``, ``major_font``,
        ``minor_font``) are forwarded to
        :func:`slidewriting.bootstrap.create_default_template`.
        """
        from .bootstrap import create_default_template  # deferred: sibling module

        package = create_default_template(accent=accent, **kw)
        info = TemplateParser(package).parse()
        return cls(package, info)

    # --- template introspection ----------------------------------------------------

    @property
    def theme(self) -> Theme:
        """The theme of the first slide master."""
        return self.info.masters[0].theme

    @property
    def layouts(self) -> list[LayoutSpec]:
        """All layouts of all masters, flattened in master order."""
        return self.info.layouts

    def layout(self, query: Union[str, int]) -> LayoutSpec:
        """Find a layout by index, name, type, or name substring.

        See :meth:`slidewriting.model.TemplateInfo.find_layout`; raises
        :class:`~slidewriting.errors.ParseError` listing the available layouts
        when nothing matches.
        """
        return self.info.find_layout(query)

    # --- document properties -------------------------------------------------------

    @property
    def title(self) -> Union[str, None]:
        """Deck title written to the core properties on :meth:`save`."""
        return self._title

    @title.setter
    def title(self, value: Union[str, None]) -> None:
        self._title = value

    @property
    def author(self) -> Union[str, None]:
        """Deck author written as core-properties creator on :meth:`save`."""
        return self._author

    @author.setter
    def author(self, value: Union[str, None]) -> None:
        self._author = value

    # --- building ------------------------------------------------------------------

    def add_slide(
        self, layout: Union[str, int, LayoutSpec, None] = None
    ) -> SlideBuilder:
        """Queue a new slide and return its :class:`~slidewriting.slide.SlideBuilder`.

        ``layout`` selects the slide layout: a :class:`LayoutSpec`, a layout
        query (name, type, substring, or index — see :meth:`layout`), or
        ``None`` for the default layout (type ``"obj"`` if present, else the
        first layout). The slide part itself is only created on :meth:`save`.
        """
        if isinstance(layout, LayoutSpec):
            layout_spec = layout
        elif layout is None:
            layout_spec = self._default_layout()
        else:
            layout_spec = self.info.find_layout(layout)
        master = self._master_of(layout_spec)
        builder = SlideBuilder(
            layout_spec, master, self.info.slide_width, self.info.slide_height
        )
        self._queued.append((builder, layout_spec.partname))
        return builder

    def save(self, path: Union[str, os.PathLike, io.BytesIO]) -> None:
        """Flush all queued slides into the package and write it to ``path``.

        Queued builders are materialized in order via
        ``writer.SlideWriter.add_slide`` (which registers slide parts,
        relationships, content types, and pending images), the core
        properties are set (title defaults to :data:`DEFAULT_DECK_TITLE`),
        and the package is saved. The queue is emptied; newly written
        slides appear in :attr:`info` and :meth:`inspect` afterwards.
        """
        from .writer import (  # deferred: sibling module
            SlideWriter,
            set_app_properties,
            set_core_properties,
        )

        writer = SlideWriter(self.package, self.info)
        for builder, layout_partname in self._queued:
            blob = builder.to_xml()
            partname = writer.add_slide(blob, layout_partname, builder.pending_images)
            self.info.slides.append(
                SlideInfo(
                    partname=partname,
                    layout_partname=layout_partname,
                    title=slide_title_text(parse_xml(blob)),
                )
            )
        self._queued.clear()
        set_core_properties(
            self.package,
            title=self._title or DEFAULT_DECK_TITLE,
            creator=self._author or "Slide Writing",
        )
        set_app_properties(
            self.package,
            slide_count=len(self.info.slides),
            title=self._title or DEFAULT_DECK_TITLE,
        )
        self.package.save(path)

    # --- inspection ----------------------------------------------------------------

    def inspect(self) -> dict:
        """Return a JSON-serializable summary of the template and its slides.

        Shape::

            {"slide_size": [w, h], "masters": n,
             "layouts": [{"name": ..., "type": ...,
                          "placeholders": [{"type": ..., "idx": ..., "name": ...}]}],
             "theme": {"colors": {"dk1": "RRGGBB", ...},
                       "fonts": {"major_latin": ..., "minor_latin": ...}},
             "slides": [{"partname": ..., "layout": ..., "title": ...}]}
        """
        theme = self.theme
        return {
            "slide_size": [self.info.slide_width, self.info.slide_height],
            "masters": len(self.info.masters),
            "layouts": [
                {
                    "name": layout.name,
                    "type": layout.ltype,
                    "placeholders": [
                        {"type": ph.ph_type, "idx": ph.idx, "name": ph.name}
                        for ph in layout.placeholders
                    ],
                }
                for layout in self.info.layouts
            ],
            "theme": {
                "colors": {slot: theme.colors.get(slot) for slot in SCHEME_SLOTS},
                "fonts": {
                    "major_latin": theme.fonts.major_latin,
                    "minor_latin": theme.fonts.minor_latin,
                },
            },
            "slides": [
                {
                    "partname": slide.partname,
                    "layout": slide.layout_partname,
                    "title": slide.title,
                }
                for slide in self.info.slides
            ],
        }

    # --- internals -----------------------------------------------------------------

    def _default_layout(self) -> LayoutSpec:
        """Default layout for :meth:`add_slide`: type ``"obj"``, else the first."""
        layouts = self.info.layouts
        for layout in layouts:
            if layout.ltype == "obj":
                return layout
        if layouts:
            return layouts[0]
        raise ParseError("Template has no slide layouts")

    def _master_of(self, layout: LayoutSpec) -> MasterSpec:
        """The master a layout belongs to; raises ParseError when unknown."""
        for master in self.info.masters:
            if master.partname == layout.master_partname:
                return master
        raise ParseError(
            f"Layout {layout.partname!r} references unknown master "
            f"{layout.master_partname!r}"
        )
