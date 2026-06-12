"""Design model for parsed PPTX templates.

The dataclasses in this module describe everything DeckForge knows about a
template after :class:`~deckforge.parser.TemplateParser` has run: slide size,
slide masters (with color map and theme), their layouts, the placeholders
declared on masters and layouts, and an inventory of the existing slides.

The model is read-only by convention: ``element`` fields reference the parsed
XML of the original parts and must not be mutated.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .emu import Box
from .errors import ParseError
from .theme import ColorResolver, Theme


@dataclass
class PlaceholderSpec:
    """One placeholder shape (``<p:sp>`` with ``<p:ph>``) on a layout or master."""

    ph_type: str
    """Placeholder type: ``"title"``, ``"ctrTitle"``, ``"subTitle"``, ``"body"``,
    ``"ftr"``, ``"dt"``, ``"sldNum"``, ``"pic"``, ... (``"body"`` when absent)."""

    idx: int
    """Placeholder index from ``p:ph@idx`` (0 when absent)."""

    shape_id: int
    """Numeric shape id from ``p:cNvPr@id``."""

    name: str
    """Shape name from ``p:cNvPr@name``."""

    box: Box | None
    """Explicit geometry from ``p:spPr/a:xfrm`` on this element, else ``None``."""

    element: ET.Element
    """The original ``<p:sp>`` element from the layout/master (read-only)."""


@dataclass
class LayoutSpec:
    """One slide layout part and its placeholder inventory."""

    partname: str
    """Absolute partname, e.g. ``"/ppt/slideLayouts/slideLayout1.xml"``."""

    name: str
    """Human-readable layout name from ``p:cSld@name`` (``""`` when absent)."""

    ltype: str
    """Layout type from ``p:sldLayout@type``; ``""`` when absent ("custom")."""

    placeholders: list[PlaceholderSpec]
    """Placeholders declared in the layout's shape tree."""

    element: ET.Element
    """The parsed ``<p:sldLayout>`` root element (read-only)."""

    master_partname: str
    """Partname of the slide master this layout belongs to."""


@dataclass
class MasterSpec:
    """One slide master with its color map, placeholders, layouts, and theme."""

    partname: str
    """Absolute partname, e.g. ``"/ppt/slideMasters/slideMaster1.xml"``."""

    clr_map: dict[str, str]
    """Logical color name -> theme slot mapping from ``p:clrMap`` attributes."""

    placeholders: list[PlaceholderSpec]
    """Placeholders declared in the master's shape tree."""

    layouts: list[LayoutSpec]
    """Layouts of this master, in ``p:sldLayoutIdLst`` order."""

    theme: Theme
    """The master's theme (colors and fonts)."""

    element: ET.Element
    """The parsed ``<p:sldMaster>`` root element (read-only)."""


@dataclass
class SlideInfo:
    """Inventory entry for one slide that already exists in the template."""

    partname: str
    """Absolute partname, e.g. ``"/ppt/slides/slide1.xml"``."""

    layout_partname: str
    """Partname of the layout the slide is based on."""

    title: str | None
    """Concatenated title text, or ``None`` if the slide has no title placeholder."""


@dataclass
class TemplateInfo:
    """The complete design model of a parsed template."""

    slide_width: int
    """Slide width in EMU."""

    slide_height: int
    """Slide height in EMU."""

    masters: list[MasterSpec]
    """All slide masters, in ``p:sldMasterIdLst`` order."""

    slides: list[SlideInfo]
    """Existing slides, in ``p:sldIdLst`` order."""

    @property
    def layouts(self) -> list[LayoutSpec]:
        """All layouts of all masters, flattened in master order."""
        return [layout for master in self.masters for layout in master.layouts]

    def find_layout(self, query: str | int) -> LayoutSpec:
        """Find a layout by index, name, type, or name substring.

        An ``int`` query selects by position in :attr:`layouts`. A ``str``
        query is matched case-insensitively in this order: exact layout name,
        then layout type (``ltype``), then name substring. Raises
        :class:`~deckforge.errors.ParseError` listing the available layouts
        when nothing matches.
        """
        layouts = self.layouts
        if isinstance(query, int):
            try:
                return layouts[query]
            except IndexError:
                raise ParseError(self._no_match_message(query)) from None
        folded = str(query).casefold()
        for layout in layouts:
            if layout.name.casefold() == folded:
                return layout
        for layout in layouts:
            if layout.ltype.casefold() == folded:
                return layout
        if folded:
            for layout in layouts:
                if folded in layout.name.casefold():
                    return layout
        raise ParseError(self._no_match_message(query))

    def resolver(self, layout: LayoutSpec) -> ColorResolver:
        """Build a :class:`~deckforge.theme.ColorResolver` for a layout.

        The resolver combines the theme and color map of the master the
        layout belongs to. Raises :class:`~deckforge.errors.ParseError` if
        the layout references a master unknown to this template.
        """
        for master in self.masters:
            if master.partname == layout.master_partname:
                return ColorResolver(master.theme, master.clr_map)
        raise ParseError(
            f"Layout {layout.partname!r} references unknown master "
            f"{layout.master_partname!r}"
        )

    def _no_match_message(self, query: str | int) -> str:
        """Error message for a failed layout lookup, listing what is available."""
        available = ", ".join(
            f"{layout.name!r} ({layout.ltype or 'custom'})" for layout in self.layouts
        )
        return (
            f"No layout matches {query!r}; available layouts: "
            f"{available or '(none)'}"
        )
