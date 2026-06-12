"""Native DrawingML table builder (``p:graphicFrame`` with ``a:tbl``).

Builds fully formatted, theme-aware tables: accent header row, optional zebra
banding, hairline borders, cell margins, and automatic right-alignment of
numeric-looking cells. Column widths are distributed proportionally so they
sum *exactly* to the target box width (the last column absorbs rounding).
"""

from __future__ import annotations

import re

from dataclasses import dataclass
import xml.etree.ElementTree as ET

from .emu import Box, pt
from .errors import BuildError
from .shapes import line_props
from .text import ParaFormat, RunFormat, para_el, run_el, txbody_el
from .theme import color_el, fill_for
from .xmlcore import el, qn, sub

#: Cells fully made of these characters (and containing at least one digit)
#: are treated as numeric and right-aligned when ``align_numbers_right`` is on.
_NUMERIC_RE = re.compile(r"^[\s\d.,%+\-€$]+$")
_DIGIT_RE = re.compile(r"\d")

#: Allowed paragraph alignment codes for column specs.
_ALIGN_VALUES = ("l", "ctr", "r")

#: URI of the DrawingML table graphic data.
_TABLE_URI = "http://schemas.openxmlformats.org/drawingml/2006/table"


@dataclass
class TableStyle:
    """Visual style for :func:`table_el`.

    Colors accept theme scheme slots (``"accent1"``, ``"tx1"``, ...) or
    ``"RRGGBB"`` literals; sizes are in points.
    """

    header_fill: str = "accent1"
    header_color: str = "FFFFFF"
    header_bold: bool = True
    header_size_pt: float = 11.0
    body_size_pt: float = 11.0
    body_color: str = "tx1"
    band_fill: str | None = None
    border_color: str = "D9D9D9"
    border_w_pt: float = 0.75
    row_height_pt: float = 22.0
    cell_margin_pt: float = 4.0
    align_numbers_right: bool = True


def _is_numeric_text(value: str) -> bool:
    """Return True if ``value`` looks like a number/amount (and has a digit)."""
    return bool(_NUMERIC_RE.match(value)) and bool(_DIGIT_RE.search(value))


def _normalize_columns(
    columns: list[str | dict],
) -> tuple[list[str], list[float], list[str | None], bool]:
    """Normalize the heterogeneous ``columns`` list.

    Returns ``(labels, weights, aligns, has_explicit_widths)``; columns
    without a ``"width"`` key default to weight 1.0.

    Raises:
        BuildError: For empty column lists or malformed column dicts.
    """
    if not columns:
        raise BuildError("A table needs at least one column; got an empty list.")
    labels: list[str] = []
    weights: list[float] = []
    aligns: list[str | None] = []
    has_widths = False
    for i, col in enumerate(columns):
        if isinstance(col, dict):
            if "label" not in col:
                raise BuildError(f"Column {i} is missing the 'label' key: {col!r}")
            labels.append(str(col["label"]))
            width = col.get("width")
            if width is not None:
                has_widths = True
                weights.append(float(width))
            else:
                weights.append(1.0)
            align = col.get("align")
            if align is not None and align not in _ALIGN_VALUES:
                raise BuildError(
                    f"Column {i} has invalid align {align!r}; "
                    f"expected one of: {', '.join(_ALIGN_VALUES)}"
                )
            aligns.append(align)
        else:
            labels.append(str(col))
            weights.append(1.0)
            aligns.append(None)
    return labels, weights, aligns, has_widths


def _distribute_widths(total_w: int, weights: list[float]) -> list[int]:
    """Scale relative ``weights`` to EMU widths summing exactly to ``total_w``.

    The last column absorbs the accumulated rounding difference.

    Raises:
        BuildError: If any weight is non-positive or a resulting width
            would not be positive.
    """
    if any(w <= 0 for w in weights):
        raise BuildError(f"Column widths must be positive; got {weights!r}.")
    total_weight = sum(weights)
    widths: list[int] = []
    used = 0
    for i, weight in enumerate(weights):
        if i == len(weights) - 1:
            width = total_w - used
        else:
            width = int(round(total_w * weight / total_weight))
        widths.append(width)
        used += width
    if any(w <= 0 for w in widths):
        raise BuildError(
            f"Box width {total_w} EMU is too small for {len(weights)} columns."
        )
    return widths


def _cell_txbody(
    text: str, fmt: RunFormat, align: str | None
) -> ET.Element:
    """Build an ``<a:txBody>`` for one table cell."""
    pf = ParaFormat(align=align) if align is not None else None
    para = para_el([run_el(text, fmt)], pf)
    body = txbody_el([para], autofit=None)
    # txbody_el produces the shape variant <p:txBody>; table cells use the
    # DrawingML namespace.
    body.tag = qn("a:txBody")
    return body


def _cell_tcpr(
    style: TableStyle, fill: str | None
) -> ET.Element:
    """Build an ``<a:tcPr>`` with margins, four borders, and optional fill."""
    margin = str(pt(style.cell_margin_pt))
    tc_pr = el(
        "a:tcPr",
        {"marL": margin, "marR": margin, "marT": margin, "marB": margin},
    )
    border_w = pt(style.border_w_pt)
    for side in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
        ln = line_props(color_el(style.border_color), border_w)
        ln.tag = qn(side)
        tc_pr.append(ln)
    if fill is not None:
        tc_pr.append(fill_for(fill))
    return tc_pr


def _cell_el(
    text: str,
    fmt: RunFormat,
    align: str | None,
    style: TableStyle,
    fill: str | None,
) -> ET.Element:
    """Build one ``<a:tc>`` (txBody first, then tcPr, per the skeleton)."""
    tc = el("a:tc")
    tc.append(_cell_txbody(text, fmt, align))
    tc.append(_cell_tcpr(style, fill))
    return tc


def table_el(
    shape_id: int,
    box: Box,
    columns: list[str | dict],
    rows: list[list[str]],
    style: TableStyle | None = None,
    col_widths: list[float] | None = None,
) -> ET.Element:
    """Build a formatted table as a ``<p:graphicFrame>`` element.

    Args:
        shape_id: Numeric shape id for ``p:cNvPr``.
        box: Position and size of the frame in EMU; column widths are scaled
            so they sum exactly to ``box.w``.
        columns: Header definitions: plain strings or dicts with keys
            ``"label"`` (required), ``"width"`` (relative float), and
            ``"align"`` (``"l"``/``"ctr"``/``"r"``).
        rows: Body rows; every row must have exactly one cell per column.
            Cell values are converted with ``str()``. An empty list yields a
            header-only table.
        style: Visual style; defaults to ``TableStyle()``.
        col_widths: Optional relative widths overriding any per-column
            ``"width"`` values; must have one entry per column.

    Returns:
        The complete ``<p:graphicFrame>`` element.

    Raises:
        BuildError: For empty column lists, ragged rows, mismatched or
            non-positive width specs, or invalid alignment codes.
    """
    style = style if style is not None else TableStyle()
    labels, weights, aligns, has_widths = _normalize_columns(columns)
    n_cols = len(labels)
    if col_widths is not None:
        if len(col_widths) != n_cols:
            raise BuildError(
                f"col_widths has {len(col_widths)} entries but the table "
                f"has {n_cols} columns."
            )
        weights = [float(w) for w in col_widths]
    elif not has_widths:
        weights = [1.0] * n_cols
    widths = _distribute_widths(box.w, weights)

    for i, row in enumerate(rows):
        if len(row) != n_cols:
            raise BuildError(
                f"Row {i} has {len(row)} cells but the table has "
                f"{n_cols} columns; all rows must match the header."
            )

    frame = el("p:graphicFrame")
    nv = sub(frame, "p:nvGraphicFramePr")
    sub(nv, "p:cNvPr", {"id": str(shape_id), "name": f"Table {shape_id}"})
    sub(nv, "p:cNvGraphicFramePr")
    sub(nv, "p:nvPr")
    xfrm = sub(frame, "p:xfrm")
    sub(xfrm, "a:off", {"x": str(box.x), "y": str(box.y)})
    sub(xfrm, "a:ext", {"cx": str(box.w), "cy": str(box.h)})
    graphic = sub(frame, "a:graphic")
    graphic_data = sub(graphic, "a:graphicData", {"uri": _TABLE_URI})
    tbl = sub(graphic_data, "a:tbl")
    sub(tbl, "a:tblPr", {"firstRow": "1", "bandRow": "1"})
    grid = sub(tbl, "a:tblGrid")
    for width in widths:
        sub(grid, "a:gridCol", {"w": str(width)})

    row_h = str(pt(style.row_height_pt))
    header_fmt = RunFormat(
        size_pt=style.header_size_pt,
        bold=style.header_bold,
        color=style.header_color,
    )
    header_tr = sub(tbl, "a:tr", {"h": row_h})
    for c in range(n_cols):
        header_tr.append(
            _cell_el(labels[c], header_fmt, aligns[c], style, style.header_fill)
        )

    body_fmt = RunFormat(size_pt=style.body_size_pt, color=style.body_color)
    for i, row in enumerate(rows):
        band = style.band_fill if (style.band_fill and i % 2 == 1) else None
        tr = sub(tbl, "a:tr", {"h": row_h})
        for c in range(n_cols):
            text = str(row[c])
            align = aligns[c]
            if (
                align is None
                and style.align_numbers_right
                and _is_numeric_text(text)
            ):
                align = "r"
            tr.append(_cell_el(text, body_fmt, align, style, band))
    return frame
