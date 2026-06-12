"""Template parser: builds the design model from an opened OPC package.

:class:`TemplateParser` walks ``presentation.xml`` (slide size, master list,
slide list), follows the relationship graph to masters, layouts, themes, and
slides, and returns a fully populated
:class:`~slidewriting.model.TemplateInfo`. Missing optional bits are tolerated;
:class:`~slidewriting.errors.ParseError` is raised only for structurally
unusable files.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .emu import SLIDE_H_16_9, SLIDE_W_16_9, Box
from .errors import ParseError
from .model import LayoutSpec, MasterSpec, PlaceholderSpec, SlideInfo, TemplateInfo
from .opc import RT_SLIDE_LAYOUT, RT_THEME, Package, Relationships
from .theme import parse_theme
from .xmlcore import find, findall, get, parse_xml, qn

#: Placeholder types that act as a slide title (matched by type only).
_TITLE_TYPES = ("title", "ctrTitle")


def extract_placeholders(sp_tree: ET.Element) -> list[PlaceholderSpec]:
    """Collect the placeholder specs from a ``<p:spTree>``.

    Every ``<p:sp>`` child that carries ``p:nvSpPr/p:nvPr/p:ph`` is a
    placeholder; other shapes are ignored. Missing ``p:ph`` attributes
    default to type ``"body"`` and idx ``0``. The box is only set when the
    shape has an explicit ``p:spPr/a:xfrm``.
    """
    placeholders: list[PlaceholderSpec] = []
    for sp in findall(sp_tree, "p:sp"):
        ph = find(sp, "p:nvSpPr/p:nvPr/p:ph")
        if ph is None:
            continue
        cnv = find(sp, "p:nvSpPr/p:cNvPr")
        placeholders.append(
            PlaceholderSpec(
                ph_type=ph.get("type", "body"),
                idx=_int_attr(ph, "idx", 0),
                shape_id=_int_attr(cnv, "id", 0) if cnv is not None else 0,
                name=cnv.get("name", "") if cnv is not None else "",
                box=_xfrm_box(sp),
                element=sp,
            )
        )
    return placeholders


def slide_title_text(slide_root: ET.Element) -> str | None:
    """Extract the title text of a slide, or ``None`` if it has no title.

    The first shape whose placeholder type is ``title`` or ``ctrTitle`` wins;
    its text is the concatenation of all ``<a:t>`` runs in document order.
    """
    sp_tree = find(slide_root, "p:cSld/p:spTree")
    if sp_tree is None:
        return None
    for sp in findall(sp_tree, "p:sp"):
        ph = find(sp, "p:nvSpPr/p:nvPr/p:ph")
        if ph is None or ph.get("type") not in _TITLE_TYPES:
            continue
        return "".join(node.text or "" for node in findall(sp, ".//a:t"))
    return None


def effective_box(
    layout: LayoutSpec, master: MasterSpec, ph_type: str, idx: int
) -> Box | None:
    """Resolve the inherited geometry of a placeholder.

    Returns the box of the layout placeholder matching ``(ph_type, idx)``
    when it carries an explicit one; otherwise falls back to the first
    master placeholder matching by type alone. For the master lookup,
    ``title`` and ``ctrTitle`` are treated as equivalent, mirroring
    PowerPoint's title inheritance. ``None`` when neither level provides
    a box.
    """
    for ph in layout.placeholders:
        if ph.ph_type == ph_type and ph.idx == idx and ph.box is not None:
            return ph.box
    master_types = set(_TITLE_TYPES) if ph_type in _TITLE_TYPES else {ph_type}
    for ph in master.placeholders:
        if ph.ph_type in master_types:
            return ph.box
    return None


class TemplateParser:
    """Parses an opened :class:`~slidewriting.opc.Package` into a design model."""

    def __init__(self, package: Package) -> None:
        """Bind the parser to an already opened package."""
        self._package = package

    def parse(self) -> TemplateInfo:
        """Parse the package and return the complete :class:`TemplateInfo`.

        Raises :class:`~slidewriting.errors.ParseError` for structurally
        unusable files (main part is not a presentation, no slide masters,
        dangling relationship references).
        """
        main = self._package.main_part()
        root = parse_xml(main.blob)
        if root.tag != qn("p:presentation"):
            raise ParseError(
                f"Main part {main.partname!r} is not a presentation "
                f"(root element is {root.tag!r})"
            )
        width, height = self._slide_size(root)
        pres_rels = self._package.rels(main.partname)
        masters = [
            self._parse_master(
                self._resolve_rid(pres_rels, node, "p:sldMasterId", main.partname)
            )
            for node in findall(root, "p:sldMasterIdLst/p:sldMasterId")
        ]
        if not masters:
            raise ParseError(
                f"Presentation {main.partname!r} declares no slide masters"
            )
        slides = [
            self._parse_slide(
                self._resolve_rid(pres_rels, node, "p:sldId", main.partname)
            )
            for node in findall(root, "p:sldIdLst/p:sldId")
        ]
        return TemplateInfo(width, height, masters, slides)

    # --- per-part parsing --------------------------------------------------------

    def _parse_master(self, partname: str) -> MasterSpec:
        """Parse one slide master part: color map, placeholders, layouts, theme."""
        root = parse_xml(self._package.part(partname).blob)
        rels = self._package.rels(partname)
        clr_map_el = find(root, "p:clrMap")
        clr_map = dict(clr_map_el.attrib) if clr_map_el is not None else {}
        theme_rels = rels.by_type(RT_THEME)
        if not theme_rels:
            raise ParseError(f"Slide master {partname!r} has no theme relationship")
        theme = parse_theme(
            self._package.part(rels.resolve(theme_rels[0].target)).blob
        )
        layouts = [
            self._parse_layout(
                self._resolve_rid(rels, node, "p:sldLayoutId", partname), partname
            )
            for node in findall(root, "p:sldLayoutIdLst/p:sldLayoutId")
        ]
        return MasterSpec(
            partname=partname,
            clr_map=clr_map,
            placeholders=self._tree_placeholders(root),
            layouts=layouts,
            theme=theme,
            element=root,
        )

    def _parse_layout(self, partname: str, master_partname: str) -> LayoutSpec:
        """Parse one slide layout part: name, type, placeholders."""
        root = parse_xml(self._package.part(partname).blob)
        c_sld = find(root, "p:cSld")
        name = c_sld.get("name", "") if c_sld is not None else ""
        return LayoutSpec(
            partname=partname,
            name=name,
            ltype=root.get("type", ""),
            placeholders=self._tree_placeholders(root),
            element=root,
            master_partname=master_partname,
        )

    def _parse_slide(self, partname: str) -> SlideInfo:
        """Parse one existing slide part into its inventory entry."""
        root = parse_xml(self._package.part(partname).blob)
        rels = self._package.rels(partname)
        layout_rels = rels.by_type(RT_SLIDE_LAYOUT)
        if not layout_rels:
            raise ParseError(f"Slide {partname!r} has no slideLayout relationship")
        return SlideInfo(
            partname=partname,
            layout_partname=rels.resolve(layout_rels[0].target),
            title=slide_title_text(root),
        )

    # --- helpers -----------------------------------------------------------------

    @staticmethod
    def _slide_size(presentation_root: ET.Element) -> tuple[int, int]:
        """Read ``p:sldSz`` (cx, cy); default 16:9 size when the element is absent."""
        sld_sz = find(presentation_root, "p:sldSz")
        if sld_sz is None:
            return SLIDE_W_16_9, SLIDE_H_16_9
        try:
            return int(sld_sz.get("cx", "")), int(sld_sz.get("cy", ""))
        except ValueError:
            raise ParseError(
                "p:sldSz is present but its cx/cy attributes are missing or invalid"
            ) from None

    @staticmethod
    def _tree_placeholders(part_root: ET.Element) -> list[PlaceholderSpec]:
        """Placeholders of a master/layout root; ``[]`` when it has no shape tree."""
        sp_tree = find(part_root, "p:cSld/p:spTree")
        return extract_placeholders(sp_tree) if sp_tree is not None else []

    @staticmethod
    def _resolve_rid(
        rels: Relationships, node: ET.Element, label: str, source_partname: str
    ) -> str:
        """Resolve the ``r:id`` of an id-list entry to an absolute partname."""
        rid = get(node, "r:id")
        if not rid:
            raise ParseError(
                f"<{label}> in {source_partname!r} has no r:id attribute"
            )
        rel = rels.get(rid)
        if rel is None:
            raise ParseError(
                f"<{label}> in {source_partname!r} references unknown "
                f"relationship {rid!r}"
            )
        return rels.resolve(rel.target)


def _int_attr(elem: ET.Element, attr: str, default: int) -> int:
    """Integer attribute value with a default for absent or malformed values."""
    raw = elem.get(attr)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _xfrm_box(sp: ET.Element) -> Box | None:
    """Explicit geometry of a shape from ``p:spPr/a:xfrm``, or ``None``."""
    xfrm = find(sp, "p:spPr/a:xfrm")
    if xfrm is None:
        return None
    off = find(xfrm, "a:off")
    ext = find(xfrm, "a:ext")
    if off is None or ext is None:
        return None
    try:
        return Box(
            int(off.get("x", "")),
            int(off.get("y", "")),
            int(ext.get("cx", "")),
            int(ext.get("cy", "")),
        )
    except ValueError:
        return None
