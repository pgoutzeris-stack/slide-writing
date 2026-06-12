"""Free-shape, connector, and picture element factories plus image sniffing.

This module builds the DrawingML/PresentationML elements for free shapes
(``p:sp``), straight-line connectors (``p:cxnSp``), and pictures (``p:pic``)
exactly as specified in ARCHITECTURE.md section 1. It also provides
:func:`detect_image`, a pure-``struct`` PNG/JPEG header sniffer used by the
writer to register media parts without any imaging library.
"""

from __future__ import annotations

import struct

import xml.etree.ElementTree as ET

from .emu import Box
from .errors import BuildError
from .opc import CT_JPEG, CT_PNG
from .xmlcore import el, sub

#: PNG file signature (first 8 bytes of every PNG).
_PNG_SIGNATURE: bytes = b"\x89PNG\r\n\x1a\n"

#: JPEG SOI marker (first 2 bytes of every JPEG).
_JPEG_SOI: bytes = b"\xff\xd8"

#: SOFn marker bytes that carry frame dimensions (0xC0-0xCF minus C4/C8/CC).
_JPEG_SOF_MARKERS: frozenset[int] = frozenset(
    m for m in range(0xC0, 0xD0) if m not in (0xC4, 0xC8, 0xCC)
)

#: JPEG markers without a length field (standalone): TEM, RST0-7, SOI, EOI.
_JPEG_STANDALONE_MARKERS: frozenset[int] = frozenset(
    [0x01] + list(range(0xD0, 0xDA))
)

#: Accepted line-cap spellings mapped to the OOXML ``cap`` attribute values.
_CAP_VALUES: dict[str, str] = {
    "flat": "flat",
    "round": "rnd",
    "rnd": "rnd",
    "square": "sq",
    "sq": "sq",
}


def _xfrm_attrs(rot: int | None, flip_h: bool, flip_v: bool) -> dict[str, str]:
    """Build the optional attribute dict for an ``a:xfrm`` element."""
    attrs: dict[str, str] = {}
    if rot is not None:
        attrs["rot"] = str(rot)
    if flip_h:
        attrs["flipH"] = "1"
    if flip_v:
        attrs["flipV"] = "1"
    return attrs


def _add_xfrm(
    parent: ET.Element,
    box: Box,
    *,
    rot: int | None = None,
    flip_h: bool = False,
    flip_v: bool = False,
) -> ET.Element:
    """Append ``<a:xfrm><a:off/><a:ext/></a:xfrm>`` for ``box`` to ``parent``."""
    xfrm = sub(parent, "a:xfrm", _xfrm_attrs(rot, flip_h, flip_v))
    sub(xfrm, "a:off", {"x": str(box.x), "y": str(box.y)})
    sub(xfrm, "a:ext", {"cx": str(box.w), "cy": str(box.h)})
    return xfrm


def _add_prst_geom(
    parent: ET.Element, preset: str, adj: dict[str, int] | None = None
) -> ET.Element:
    """Append ``<a:prstGeom prst="..."><a:avLst/></a:prstGeom>`` to ``parent``.

    Each ``adj`` entry becomes ``<a:gd name="K" fmla="val V"/>`` inside the
    ``a:avLst`` (insertion order preserved).
    """
    geom = sub(parent, "a:prstGeom", {"prst": preset})
    av_lst = sub(geom, "a:avLst")
    if adj:
        for name, value in adj.items():
            sub(av_lst, "a:gd", {"name": name, "fmla": f"val {value}"})
    return geom


def shape_el(
    shape_id: int,
    name: str,
    preset: str,
    box: Box,
    *,
    fill: ET.Element | None = None,
    line: ET.Element | None = None,
    txbody: ET.Element | None = None,
    adj: dict[str, int] | None = None,
    rot: int | None = None,
    flip_h: bool = False,
    flip_v: bool = False,
) -> ET.Element:
    """Build a free shape ``<p:sp>`` per the section 1 skeleton.

    Args:
        shape_id: Numeric shape id for ``p:cNvPr``.
        name: Shape name for ``p:cNvPr``.
        preset: Preset geometry name (e.g. ``"roundRect"``).
        box: Position and size in EMU.
        fill: Optional fill element (e.g. from ``theme.fill_for`` or
            :func:`no_fill`); appended to ``p:spPr`` as given.
        line: Optional ``<a:ln>`` element (see :func:`line_props`).
        txbody: Optional ``<p:txBody>`` element; appended last.
        adj: Geometry adjust values; each entry becomes
            ``<a:gd name="K" fmla="val V"/>`` in ``a:avLst``.
        rot: Rotation in 60000ths of a degree (``a:xfrm@rot``).
        flip_h: Set ``a:xfrm@flipH="1"``.
        flip_v: Set ``a:xfrm@flipV="1"``.

    Returns:
        The complete ``<p:sp>`` element.
    """
    sp = el("p:sp")
    nv = sub(sp, "p:nvSpPr")
    sub(nv, "p:cNvPr", {"id": str(shape_id), "name": name})
    sub(nv, "p:cNvSpPr")
    sub(nv, "p:nvPr")
    sp_pr = sub(sp, "p:spPr")
    _add_xfrm(sp_pr, box, rot=rot, flip_h=flip_h, flip_v=flip_v)
    _add_prst_geom(sp_pr, preset, adj)
    if fill is not None:
        sp_pr.append(fill)
    if line is not None:
        sp_pr.append(line)
    if txbody is not None:
        sp.append(txbody)
    return sp


def line_props(
    color_el_: ET.Element,
    w_emu: int,
    dash: str | None = None,
    cap: str = "flat",
) -> ET.Element:
    """Build an ``<a:ln>`` element for shape outlines and connectors.

    Args:
        color_el_: A color element (``a:srgbClr``/``a:schemeClr``); wrapped in
            ``<a:solidFill>``.
        w_emu: Line width in EMU (``a:ln@w``).
        dash: Optional preset dash name (``"dash"``, ``"sysDot"``, ...);
            emitted as ``<a:prstDash val="..."/>``.
        cap: Line cap: ``"flat"`` (default), ``"round"``/``"rnd"``, or
            ``"square"``/``"sq"``; emitted as the ``cap`` attribute on
            ``a:ln``.

    Returns:
        The ``<a:ln>`` element.

    Raises:
        BuildError: If ``cap`` is not a recognized cap style.
    """
    try:
        cap_val = _CAP_VALUES[cap]
    except KeyError:
        raise BuildError(
            f"Unknown line cap {cap!r}; expected one of: "
            f"{', '.join(sorted(_CAP_VALUES))}"
        ) from None
    ln = el("a:ln", {"w": str(w_emu), "cap": cap_val})
    solid = sub(ln, "a:solidFill")
    solid.append(color_el_)
    if dash is not None:
        sub(ln, "a:prstDash", {"val": dash})
    return ln


def no_fill() -> ET.Element:
    """Return ``<a:noFill/>``, usable as the ``fill`` argument of :func:`shape_el`."""
    return el("a:noFill")


def connector_el(
    shape_id: int,
    name: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    line: ET.Element,
) -> ET.Element:
    """Build a straight-line connector ``<p:cxnSp>`` between two points.

    The transform is computed from the two endpoints: ``a:off`` is the
    top-left (minimum) corner, ``a:ext`` the absolute delta, and ``flipH`` /
    ``flipV`` are set when ``x2 < x1`` / ``y2 < y1`` so the line runs in the
    intended direction.

    Args:
        shape_id: Numeric shape id for ``p:cNvPr``.
        name: Shape name for ``p:cNvPr``.
        x1: Start point x in EMU.
        y1: Start point y in EMU.
        x2: End point x in EMU.
        y2: End point y in EMU.
        line: The ``<a:ln>`` element to apply (see :func:`line_props`).

    Returns:
        The complete ``<p:cxnSp>`` element with ``prstGeom prst="line"``.
    """
    cxn = el("p:cxnSp")
    nv = sub(cxn, "p:nvCxnSpPr")
    sub(nv, "p:cNvPr", {"id": str(shape_id), "name": name})
    sub(nv, "p:cNvCxnSpPr")
    sub(nv, "p:nvPr")
    sp_pr = sub(cxn, "p:spPr")
    box = Box(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
    _add_xfrm(sp_pr, box, flip_h=x2 < x1, flip_v=y2 < y1)
    _add_prst_geom(sp_pr, "line")
    sp_pr.append(line)
    return cxn


def picture_el(shape_id: int, name: str, rid: str, box: Box) -> ET.Element:
    """Build a picture ``<p:pic>`` per the section 1 skeleton.

    Args:
        shape_id: Numeric shape id for ``p:cNvPr``.
        name: Shape name for ``p:cNvPr``.
        rid: Relationship id for the image part (``a:blip@r:embed``); may be a
            temporary ``"img:N"`` token replaced later by the writer.
        box: Position and size in EMU.

    Returns:
        The complete ``<p:pic>`` element.
    """
    pic = el("p:pic")
    nv = sub(pic, "p:nvPicPr")
    sub(nv, "p:cNvPr", {"id": str(shape_id), "name": name})
    sub(nv, "p:cNvPicPr")
    sub(nv, "p:nvPr")
    blip_fill = sub(pic, "p:blipFill")
    sub(blip_fill, "a:blip", {"r:embed": rid})
    stretch = sub(blip_fill, "a:stretch")
    sub(stretch, "a:fillRect")
    sp_pr = sub(pic, "p:spPr")
    _add_xfrm(sp_pr, box)
    _add_prst_geom(sp_pr, "rect")
    return pic


def _detect_png(blob: bytes) -> tuple[str, str, int, int]:
    """Extract pixel dimensions from a PNG IHDR chunk."""
    if len(blob) < 24:
        raise BuildError(
            "Invalid PNG: file is truncated before the IHDR dimensions."
        )
    width, height = struct.unpack(">II", blob[16:24])
    return ("png", CT_PNG, width, height)


def _detect_jpeg(blob: bytes) -> tuple[str, str, int, int]:
    """Extract pixel dimensions from a JPEG stream by walking to a SOFn marker."""
    pos = 2
    n = len(blob)
    while pos < n:
        # Skip fill bytes; every marker is 0xFF followed by a non-0xFF byte.
        if blob[pos] != 0xFF:
            raise BuildError(
                f"Invalid JPEG: expected marker at byte {pos}, "
                f"found 0x{blob[pos]:02X}."
            )
        while pos < n and blob[pos] == 0xFF:
            pos += 1
        if pos >= n:
            break
        marker = blob[pos]
        pos += 1
        if marker in _JPEG_STANDALONE_MARKERS:
            continue
        if pos + 2 > n:
            break
        (seg_len,) = struct.unpack(">H", blob[pos : pos + 2])
        if seg_len < 2:
            raise BuildError(
                f"Invalid JPEG: segment 0x{marker:02X} has length {seg_len}."
            )
        if marker in _JPEG_SOF_MARKERS:
            if pos + 7 > n:
                break
            height, width = struct.unpack(">HH", blob[pos + 3 : pos + 7])
            return ("jpeg", CT_JPEG, width, height)
        pos += seg_len
    raise BuildError(
        "Invalid JPEG: no SOF frame header found (file truncated or corrupt)."
    )


def detect_image(blob: bytes) -> tuple[str, str, int, int]:
    """Sniff an image blob and return ``(ext, content_type, px_width, px_height)``.

    Supports PNG (signature ``\\x89PNG\\r\\n\\x1a\\n``; dimensions from IHDR
    bytes 16:24) and JPEG (``\\xff\\xd8``; dimensions from the first SOFn
    segment, markers 0xC0-0xCF excluding C4/C8/CC).

    Args:
        blob: Raw image file bytes.

    Returns:
        Tuple of file extension (``"png"``/``"jpeg"``), content type,
        pixel width, and pixel height.

    Raises:
        BuildError: For unsupported formats or corrupt/truncated image data.
    """
    if blob.startswith(_PNG_SIGNATURE):
        return _detect_png(blob)
    if blob.startswith(_JPEG_SOI):
        return _detect_jpeg(blob)
    raise BuildError(
        "Unsupported image format: only PNG and JPEG are supported "
        f"(got leading bytes {blob[:8]!r})."
    )
