"""Slide construction: :class:`SlideBuilder` and :class:`PlaceholderShape`.

A :class:`SlideBuilder` owns the canonical ``<p:sld>`` element tree for one
new slide (see ARCHITECTURE.md section 1) and appends shapes to its
``p:spTree``: layout placeholders, free textboxes, preset shapes, connector
lines, pictures, and tables. Pictures use the temp-rid contract: the builder
stores ``("img:N", blob)`` pairs in :attr:`SlideBuilder.pending_images` and
``writer.add_slide`` later replaces every ``img:N`` token with a real rId.

Imports of the sibling modules ``shapes`` and ``table`` are deferred to the
methods that need them so this module stays importable while siblings are
still being written in parallel.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import fields, replace
from typing import TYPE_CHECKING, Any

from . import xmlcore
from .emu import Box
from .emu import pt as pt_to_emu
from .errors import BuildError
from .text import ParaFormat, RunFormat, TextFrame, para_el, run_el, txbody_el
from .theme import ColorResolver, color_el, fill_for
from .xmlcore import el, sub

if TYPE_CHECKING:  # only for annotations; wired by the integrator
    from .model import LayoutSpec, MasterSpec, PlaceholderSpec

__all__ = ["PlaceholderShape", "SlideBuilder"]

_RUN_FIELD_NAMES = frozenset(f.name for f in fields(RunFormat))


def _run_format_from_kwargs(kwargs: dict[str, Any]) -> RunFormat | None:
    """Build a :class:`RunFormat` from keyword arguments; ``None`` if empty."""
    unknown = set(kwargs) - _RUN_FIELD_NAMES
    if unknown:
        raise BuildError(
            f"Unknown text format option(s) {sorted(unknown)!r}; "
            f"allowed: {sorted(_RUN_FIELD_NAMES)!r}"
        )
    return RunFormat(**kwargs) if kwargs else None


def _append_xfrm(parent: ET.Element, box: Box) -> ET.Element:
    """Append an explicit ``<a:xfrm>`` with offset/extent from ``box``."""
    xfrm = sub(parent, "a:xfrm")
    sub(xfrm, "a:off", {"x": str(box.x), "y": str(box.y)})
    sub(xfrm, "a:ext", {"cx": str(box.w), "cy": str(box.h)})
    return xfrm


class PlaceholderShape:
    """A ``<p:sp>`` with ``<p:ph>`` on a slide under construction."""

    def __init__(self, element: ET.Element, frame: TextFrame):
        """Wrap the placeholder ``<p:sp>`` and its text frame."""
        self.element = element
        self.frame = frame

    def text(self, value: str, **fmt_kwargs: Any) -> "PlaceholderShape":
        """Replace the placeholder text; ``fmt_kwargs`` are :class:`RunFormat` fields."""
        self.frame.text(value, fmt=_run_format_from_kwargs(fmt_kwargs))
        return self

    def bullets(self, items: list, **kwargs: Any) -> "PlaceholderShape":
        """Replace the placeholder content with bullets.

        ``kwargs`` may contain ``base_fmt`` (a :class:`RunFormat`) and/or
        individual :class:`RunFormat` fields, which override ``base_fmt``.
        """
        base_fmt = kwargs.pop("base_fmt", None)
        if kwargs:
            fmt = _run_format_from_kwargs(kwargs)  # validates the field names
            base_fmt = replace(base_fmt, **kwargs) if base_fmt is not None else fmt
        self.frame.bullets(items, base_fmt=base_fmt)
        return self


class SlideBuilder:
    """Builds the XML for one new slide against a layout and its master."""

    def __init__(
        self,
        layout: "LayoutSpec",
        master: "MasterSpec",
        slide_width: int,
        slide_height: int,
    ):
        """Create the canonical empty ``<p:sld>`` skeleton for ``layout``."""
        self._layout = layout
        self._master = master
        self.width = slide_width
        self.height = slide_height
        #: Color resolver built from the master's theme and color map.
        self.resolver = ColorResolver(master.theme, master.clr_map)
        #: ``[(temp_rid, blob)]`` pairs consumed by ``writer.add_slide``.
        self.pending_images: list[tuple[str, bytes]] = []
        self._shape_id = 2
        self._root, self._sp_tree = self._build_skeleton()

    @staticmethod
    def _build_skeleton() -> tuple[ET.Element, ET.Element]:
        """Build the canonical empty ``<p:sld>`` tree (ARCHITECTURE.md section 1).

        Returns the ``<p:sld>`` root and its ``p:spTree`` element.
        """
        root = el("p:sld")
        csld = sub(root, "p:cSld")
        sp_tree = sub(csld, "p:spTree")
        nv = sub(sp_tree, "p:nvGrpSpPr")
        sub(nv, "p:cNvPr", {"id": "1", "name": ""})
        sub(nv, "p:cNvGrpSpPr")
        sub(nv, "p:nvPr")
        grp = sub(sp_tree, "p:grpSpPr")
        xfrm = sub(grp, "a:xfrm")
        sub(xfrm, "a:off", {"x": "0", "y": "0"})
        sub(xfrm, "a:ext", {"cx": "0", "cy": "0"})
        sub(xfrm, "a:chOff", {"x": "0", "y": "0"})
        sub(xfrm, "a:chExt", {"cx": "0", "cy": "0"})
        clr_map_ovr = sub(root, "p:clrMapOvr")
        sub(clr_map_ovr, "a:masterClrMapping")
        return root, sp_tree

    def next_id(self) -> int:
        """Return the next free shape id (2, 3, ...) and advance the counter."""
        shape_id = self._shape_id
        self._shape_id += 1
        return shape_id

    def _find_placeholder(self, ref: str | int) -> "PlaceholderSpec":
        """Resolve ``ref`` against the layout's placeholders or raise BuildError."""
        placeholders = list(self._layout.placeholders)
        if isinstance(ref, bool):
            pass  # bools are ints; fall through to the error below
        elif isinstance(ref, int):
            for ph in placeholders:
                if ph.idx == ref:
                    return ph
        elif ref == "title":
            for ph in placeholders:
                if ph.ph_type in ("title", "ctrTitle"):
                    return ph
        elif ref == "subtitle":
            for ph in placeholders:
                if ph.ph_type == "subTitle":
                    return ph
        elif ref == "body":
            for ph in placeholders:
                if ph.ph_type == "body":
                    return ph
        elif isinstance(ref, str):
            for ph in placeholders:
                if ph.name.lower() == ref.lower():
                    return ph
        available = ", ".join(
            f"{ph.ph_type} (idx={ph.idx}, name={ph.name!r})" for ph in placeholders
        ) or "none"
        layout_name = getattr(self._layout, "name", "") or "?"
        raise BuildError(
            f"Layout {layout_name!r} has no placeholder matching {ref!r}; "
            f"available: {available}"
        )

    def placeholder(self, ref: str | int) -> PlaceholderShape:
        """Append a placeholder shape inheriting from the layout placeholder ``ref``.

        ``ref`` is ``"title"`` (matches ``title``/``ctrTitle``), ``"subtitle"``
        (``subTitle``), ``"body"`` (first body), an ``int`` placeholder idx, or
        a layout-placeholder name (case-insensitive). The new ``<p:sp>``
        carries the same (type, idx) as the layout placeholder and an *empty*
        ``<p:spPr>`` so geometry and formatting are inherited. Raises
        :class:`BuildError` listing the available placeholders on a miss.
        """
        spec = self._find_placeholder(ref)
        shape_id = self.next_id()
        sp = el("p:sp")
        nv = sub(sp, "p:nvSpPr")
        sub(nv, "p:cNvPr", {"id": str(shape_id), "name": spec.name or f"Placeholder {shape_id}"})
        cnv = sub(nv, "p:cNvSpPr")
        sub(cnv, "a:spLocks", {"noGrp": "1"})
        nvpr = sub(nv, "p:nvPr")
        ph_attrs = {"type": spec.ph_type}
        if spec.idx:
            ph_attrs["idx"] = str(spec.idx)
        sub(nvpr, "p:ph", ph_attrs)
        sub(sp, "p:spPr")  # intentionally empty: inherit everything from the layout
        txbody = sub(sp, "p:txBody")
        sub(txbody, "a:bodyPr")
        sub(txbody, "a:lstStyle")
        sub(txbody, "a:p")
        self._sp_tree.append(sp)
        return PlaceholderShape(sp, TextFrame(txbody))

    def title(self, value: str, **fmt: Any) -> PlaceholderShape:
        """Fill the title placeholder (``title`` or ``ctrTitle``) with ``value``."""
        return self.placeholder("title").text(value, **fmt)

    def add_textbox(self, box: Box, *, anchor: str | None = None) -> TextFrame:
        """Append a free textbox (``<p:sp>`` with ``txBox="1"``) and return its frame."""
        shape_id = self.next_id()
        sp = el("p:sp")
        nv = sub(sp, "p:nvSpPr")
        sub(nv, "p:cNvPr", {"id": str(shape_id), "name": f"TextBox {shape_id}"})
        sub(nv, "p:cNvSpPr", {"txBox": "1"})
        sub(nv, "p:nvPr")
        sppr = sub(sp, "p:spPr")
        _append_xfrm(sppr, box)
        geom = sub(sppr, "a:prstGeom", {"prst": "rect"})
        sub(geom, "a:avLst")
        sub(sppr, "a:noFill")
        txbody = txbody_el([], anchor=anchor)
        sp.append(txbody)
        self._sp_tree.append(sp)
        return TextFrame(txbody)

    def add_shape(
        self,
        preset: str,
        box: Box,
        *,
        fill: str | None = None,
        line: str | None = None,
        line_w_pt: float = 1.0,
        text: str | None = None,
        text_fmt: RunFormat | None = None,
        anchor: str = "ctr",
        align: str = "ctr",
        adj: dict[str, int] | None = None,
        rot: int | None = None,
    ) -> ET.Element:
        """Append a preset-geometry shape and return its ``<p:sp>`` element.

        ``fill``/``line`` are color names (scheme slot, logical name, or hex)
        resolved theme-true via ``theme.fill_for``/``theme.color_el``;
        ``line_w_pt`` is the outline width in points. Optional ``text`` is
        placed centered (``anchor``/``align``) with ``text_fmt``.
        """
        from . import shapes  # deferred: sibling module

        fill_el = fill_for(fill) if fill is not None else None
        line_el = (
            shapes.line_props(color_el(line), pt_to_emu(line_w_pt))
            if line is not None
            else None
        )
        txbody = None
        if text is not None:
            pf = ParaFormat(align=align)
            paragraphs = []
            for line_text in text.split("\n"):
                runs = [run_el(line_text, text_fmt)] if line_text else []
                paragraphs.append(para_el(runs, pf))
            txbody = txbody_el(paragraphs, anchor=anchor)
        shape_id = self.next_id()
        shape = shapes.shape_el(
            shape_id,
            f"Shape {shape_id}",
            preset,
            box,
            fill=fill_el,
            line=line_el,
            txbody=txbody,
            adj=adj,
            rot=rot,
        )
        self._sp_tree.append(shape)
        return shape

    def add_line(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        color: str = "tx1",
        w_pt: float = 1.0,
        dash: str | None = None,
    ) -> ET.Element:
        """Append a straight connector line and return its ``<p:cxnSp>`` element."""
        from . import shapes  # deferred: sibling module

        line_el = shapes.line_props(color_el(color), pt_to_emu(w_pt), dash=dash)
        shape_id = self.next_id()
        connector = shapes.connector_el(
            shape_id, f"Connector {shape_id}", x1, y1, x2, y2, line_el
        )
        self._sp_tree.append(connector)
        return connector

    def add_pending_image(self, blob: bytes) -> str:
        """Register an image blob and return its temp rid (``"img:1"``, ``"img:2"``, ...).

        ``writer.add_slide`` adds the media part and relationship, then
        replaces every ``img:N`` token in the slide XML with the real rId.
        """
        temp_rid = f"img:{len(self.pending_images) + 1}"
        self.pending_images.append((temp_rid, bytes(blob)))
        return temp_rid

    def add_picture(self, image: bytes | str, box: Box) -> ET.Element:
        """Append a picture fitted into ``box`` and return its ``<p:pic>`` element.

        ``image`` is raw PNG/JPEG bytes or a file path. The pixel dimensions
        from ``shapes.detect_image`` are used to scale the picture to fit
        inside ``box`` preserving aspect ratio (centered). The picture is
        referenced via the temp-rid mechanism (see :meth:`add_pending_image`).
        """
        from . import shapes  # deferred: sibling module

        if isinstance(image, str):
            try:
                with open(image, "rb") as fh:
                    blob = fh.read()
            except OSError as exc:
                raise BuildError(f"Cannot read image file {image!r}: {exc}") from exc
        elif isinstance(image, (bytes, bytearray)):
            blob = bytes(image)
        else:
            raise BuildError(
                f"Image must be bytes or a file path, got {type(image).__name__}"
            )
        _ext, _content_type, px_w, px_h = shapes.detect_image(blob)
        fitted = self._fit_box(box, px_w, px_h)
        temp_rid = self.add_pending_image(blob)
        shape_id = self.next_id()
        picture = shapes.picture_el(shape_id, f"Picture {shape_id}", temp_rid, fitted)
        self._sp_tree.append(picture)
        return picture

    @staticmethod
    def _fit_box(box: Box, px_w: int, px_h: int) -> Box:
        """Fit an image of ``px_w`` x ``px_h`` pixels into ``box``, centered."""
        if box.w <= 0 or box.h <= 0:
            raise BuildError(f"Picture box must have positive size, got {box!r}")
        if px_w <= 0 or px_h <= 0:
            return box
        scale = min(box.w / px_w, box.h / px_h)
        w = max(1, int(round(px_w * scale)))
        h = max(1, int(round(px_h * scale)))
        return Box(box.x + (box.w - w) // 2, box.y + (box.h - h) // 2, w, h)

    def add_table(
        self,
        box: Box,
        columns: list,
        rows: list,
        style: Any = None,
    ) -> ET.Element:
        """Append a formatted table and return its ``<p:graphicFrame>`` element."""
        from . import table as table_mod  # deferred: sibling module

        shape_id = self.next_id()
        frame = table_mod.table_el(shape_id, box, columns, rows, style)
        self._sp_tree.append(frame)
        return frame

    def to_xml(self) -> bytes:
        """Serialize the ``<p:sld>`` tree to bytes with the XML declaration."""
        return xmlcore.serialize(self._root)
