"""Consulting component library: theme-aware building blocks for slides.

Every function in this module takes a live
:class:`~deckforge.slide.SlideBuilder` and composes native PowerPoint
primitives (rectangles, ellipses, chevrons, pies, connectors, textboxes)
into consulting-grade components: agenda, KPI tiles, harvey balls,
waterfall bridges, bar/column charts, chevron timelines, traffic lights,
comparison matrices, callout boxes, and section numbers.

Design rules (ARCHITECTURE.md section 3.12):

* All geometry is computed from ``slide.width`` / ``slide.height`` — nothing
  assumes a fixed slide size. The default content area starts at
  ``x = cm(1.2)``, ``y = cm(3.2)`` (below the title) and keeps a margin of
  ``cm(1.2)`` to the right and bottom slide edges.
* Colors are theme-true: scheme slots (``accent1``, ``bg2``, ``dk2``, …)
  are used wherever a color carries the design. Fixed hex values appear
  only for semantic status colors (green/amber/red) and neutral hairlines.
* Everything is built through the :class:`SlideBuilder` primitives
  (``add_shape``/``add_line``/``add_textbox``) plus the text helpers, so
  the output is plain, fully editable PowerPoint content.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any

from .emu import Box, cm, pt
from .errors import BuildError
from .text import ParaFormat, RunFormat
from .xmlcore import el, find, qn

if TYPE_CHECKING:  # pragma: no cover - only for annotations
    from .slide import SlideBuilder

__all__ = [
    "add_agenda",
    "add_kpi_row",
    "add_harvey",
    "add_harvey_matrix",
    "add_traffic_light",
    "add_waterfall",
    "add_bar_chart",
    "add_column_chart",
    "add_timeline",
    "add_comparison",
    "add_callout",
    "add_section_number",
]

# Semantic status colors (fixed by the contract, not theme slots).
_GREEN = "2E9E4F"
_RED = "C0392B"
_AMBER = "E8A33D"

# Neutral non-design colors (hairlines, muted/inactive states, zebra rows).
_HAIRLINE = "D9D9D9"
_CONNECTOR_GREY = "A6A6A6"
_INACTIVE_LIGHT = "EEEEEE"
_ZEBRA = "F2F2F2"
_MUTED = "595959"

# Angle units: 60000ths of a degree; 0° = 3 o'clock, clockwise positive.
_PIE_FULL = 21600000  # 360°
_PIE_TOP = 16200000  # 270° = 12 o'clock

#: Traffic light status name -> saturated color, in display order.
_STATUS_COLORS = {"red": _RED, "yellow": _AMBER, "green": _GREEN}

#: Callout kind -> accent bar color.
_CALLOUT_COLORS = {"info": "accent1", "success": _GREEN, "warning": _AMBER, "key": "dk2"}


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------


def _content_box(slide: "SlideBuilder") -> Box:
    """Default content area below the title, derived from the slide size."""
    margin = cm(1.2)
    top = cm(3.2)
    return Box(margin, top, slide.width - 2 * margin, slide.height - top - margin)


def _set_no_fill(sp: ET.Element) -> None:
    """Insert ``<a:noFill/>`` into a shape's ``p:spPr`` (before ``a:ln``)."""
    sppr = find(sp, "p:spPr")
    if sppr is None:
        raise BuildError("Shape element has no p:spPr to attach a:noFill to.")
    ln_tag = qn("a:ln")
    for index, child in enumerate(list(sppr)):
        if child.tag == ln_tag:
            sppr.insert(index, el("a:noFill"))
            return
    sppr.append(el("a:noFill"))


def _zero_insets(sp: ET.Element) -> None:
    """Set all text insets of a shape's ``a:bodyPr`` to zero (tight text)."""
    bodypr = find(sp, "p:txBody/a:bodyPr")
    if bodypr is not None:
        for attr in ("lIns", "tIns", "rIns", "bIns"):
            bodypr.set(attr, "0")


def _check_item(item: Any, what: str, required: tuple, allowed: tuple) -> None:
    """Validate that ``item`` is a dict with the required/allowed keys."""
    if not isinstance(item, dict):
        raise BuildError(f"{what} must be a dict, got {type(item).__name__}: {item!r}")
    missing = [key for key in required if key not in item]
    if missing:
        raise BuildError(f"{what} is missing required key(s) {missing}: {item!r}")
    unknown = sorted(set(item) - set(allowed))
    if unknown:
        raise BuildError(
            f"{what} has unknown key(s) {unknown}; allowed: {sorted(allowed)}"
        )


def _as_number(value: Any, what: str) -> float:
    """Coerce ``value`` to ``float`` or raise :class:`BuildError`."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BuildError(f"{what} must be a number, got {type(value).__name__}: {value!r}")
    return float(value)


def _fmt_value(value: float) -> str:
    """Format a numeric label: integers without decimals, else one decimal."""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}"


def _delta_color(delta: str) -> str:
    """Color for a KPI delta: ``+…`` green, ``-…`` red, anything else tx1."""
    stripped = delta.strip()
    if stripped.startswith("+"):
        return _GREEN
    if stripped.startswith(("-", "−", "–")):
        return _RED
    return "tx1"


def _quarter(fraction: float) -> float:
    """Round a harvey fraction to the nearest quarter (ties round up).

    Raises :class:`BuildError` when ``fraction`` is not a number in [0, 1].
    """
    value = _as_number(fraction, "Harvey fraction")
    if not 0.0 <= value <= 1.0:
        raise BuildError(f"Harvey fraction must be within 0..1, got {fraction!r}")
    return int(value * 4 + 0.5) / 4.0


def _harvey_angles(fraction: float) -> tuple:
    """Return ``(adj1, adj2)`` pie angles for a harvey ball fraction.

    Angles are in 60000ths of a degree with 0° at 3 o'clock, clockwise.
    The wedge starts at 12 o'clock (``adj1 = 16200000``) and sweeps
    ``fraction * 21600000`` clockwise; the end angle wraps modulo 360°.
    A full circle (fraction 1.0) is rendered as a filled ellipse instead,
    so this helper is only meaningful for ``0 < fraction < 1``.
    """
    sweep = int(round(fraction * _PIE_FULL))
    return _PIE_TOP, (_PIE_TOP + sweep) % _PIE_FULL


def _waterfall_levels(values: list) -> tuple:
    """Cumulative ``(start, end)`` levels per waterfall item plus the total."""
    levels = []
    cumulative = 0.0
    for value in values:
        levels.append((cumulative, cumulative + value))
        cumulative += value
    return levels, cumulative


def _validate_matrix(options: list, criteria: list, rows: list, what: str) -> None:
    """Validate an options × criteria grid input."""
    if not options:
        raise BuildError(f"{what} needs at least one option (column).")
    if not criteria:
        raise BuildError(f"{what} needs at least one criterion (row).")
    if not isinstance(rows, list) or len(rows) != len(criteria):
        raise BuildError(
            f"{what} needs exactly one row per criterion: "
            f"expected {len(criteria)} rows, got {len(rows)}."
        )
    for index, row in enumerate(rows):
        if not isinstance(row, (list, tuple)) or len(row) != len(options):
            raise BuildError(
                f"{what} row {index} must have {len(options)} cells "
                f"(one per option), got {row!r}."
            )


def _grid_lines(
    slide: "SlideBuilder",
    box: Box,
    header_h: int,
    label_w: int,
    col_w: float,
    row_h: float,
    n_rows: int,
    n_cols: int,
) -> None:
    """Draw thin neutral grid hairlines for a header/label matrix layout."""
    for i in range(n_rows + 1):
        y = box.y + box.h if i == n_rows else int(round(box.y + header_h + i * row_h))
        slide.add_line(box.x, y, box.x + box.w, y, color=_HAIRLINE, w_pt=0.75)
    for j in range(n_cols + 1):
        x = box.x + box.w if j == n_cols else int(round(box.x + label_w + j * col_w))
        slide.add_line(x, box.y + header_h, x, box.y + box.h, color=_HAIRLINE, w_pt=0.75)


# ---------------------------------------------------------------------------
# components
# ---------------------------------------------------------------------------


def add_agenda(
    slide: "SlideBuilder",
    items: list,
    active: int = None,
    box: Box = None,
) -> None:
    """Add a numbered agenda with an optionally highlighted active item.

    Each item gets a numbered accent1 circle and its text, vertically
    distributed over ``box`` (default: content area). The active item is
    emphasized with a filled accent1 bar (white bold text, inverted number
    circle); when an active item is set, the other items are muted.

    Args:
        slide: Target slide builder.
        items: Agenda item texts (at least one).
        active: Index of the active item, or ``None`` for a plain agenda.
        box: Layout area; defaults to the content area.

    Raises:
        BuildError: For an empty item list or an out-of-range ``active``.
    """
    if not items:
        raise BuildError("add_agenda needs at least one agenda item.")
    if active is not None and not 0 <= active < len(items):
        raise BuildError(
            f"Active agenda index {active} is out of range 0..{len(items) - 1}."
        )
    if box is None:
        box = _content_box(slide)
    row_h = box.h // len(items)
    diameter = min(cm(0.9), int(row_h * 0.6))
    circle_x = box.x + cm(0.3)
    text_x = circle_x + diameter + cm(0.4)
    for i, item in enumerate(items):
        row_y = box.y + i * row_h
        center_y = row_y + row_h // 2
        is_active = active == i
        if is_active:
            bar_h = min(int(row_h * 0.86), diameter + cm(0.5))
            slide.add_shape(
                "roundRect",
                Box(box.x, center_y - bar_h // 2, box.w, bar_h),
                fill="accent1",
            )
        circle_box = Box(circle_x, center_y - diameter // 2, diameter, diameter)
        number_fmt = RunFormat(
            size_pt=11.0, bold=True, color="accent1" if is_active else "bg1"
        )
        circle = slide.add_shape(
            "ellipse",
            circle_box,
            fill="bg1" if is_active else "accent1",
            text=str(i + 1),
            text_fmt=number_fmt,
        )
        _zero_insets(circle)
        if is_active:
            item_fmt = RunFormat(size_pt=14.0, bold=True, color="bg1")
        elif active is not None:
            item_fmt = RunFormat(size_pt=14.0, color=_MUTED)
        else:
            item_fmt = RunFormat(size_pt=14.0, color="tx1")
        frame = slide.add_textbox(
            Box(text_x, row_y, box.x + box.w - text_x - cm(0.3), row_h),
            anchor="ctr",
        )
        frame.text(str(item), item_fmt)


def add_kpi_row(slide: "SlideBuilder", kpis: list, box: Box = None) -> None:
    """Add a row of evenly spaced KPI tiles.

    Each KPI is a dict ``{"value": "42 %", "label": "Marktanteil",
    "delta": "+3 pp" | None, "color": scheme-slot | None}``. Tiles are
    light rounded rectangles (``bg2``); the value is rendered 30 pt bold in
    ``accent1`` (or the KPI's ``color``), the label 11 pt ``tx1``, and the
    delta 11 pt — green for ``+…``, red for ``-…``.

    Args:
        slide: Target slide builder.
        kpis: KPI dicts (at least one).
        box: Layout band; defaults to a band at the top of the content area.

    Raises:
        BuildError: For an empty list or malformed KPI dicts.
    """
    if not kpis:
        raise BuildError("add_kpi_row needs at least one KPI.")
    for kpi in kpis:
        _check_item(kpi, "KPI", ("value", "label"), ("value", "label", "delta", "color"))
    if box is None:
        content = _content_box(slide)
        box = Box(content.x, content.y, content.w, min(cm(3.4), content.h))
    gap = cm(0.4)
    tile_w = (box.w - gap * (len(kpis) - 1)) // len(kpis)
    for i, kpi in enumerate(kpis):
        tile = Box(box.x + i * (tile_w + gap), box.y, tile_w, box.h)
        slide.add_shape("roundRect", tile, fill="bg2", adj={"adj": 8000})
        frame = slide.add_textbox(tile.inset(cm(0.2), cm(0.15)), anchor="ctr")
        value_color = kpi.get("color") or "accent1"
        frame.paragraph(
            [(str(kpi["value"]), RunFormat(size_pt=30.0, bold=True, color=value_color))],
            ParaFormat(align="ctr"),
        )
        frame.paragraph(
            [(str(kpi["label"]), RunFormat(size_pt=11.0, color="tx1"))],
            ParaFormat(align="ctr", space_before_pt=2.0),
        )
        delta = kpi.get("delta")
        if delta:
            delta_text = str(delta)
            frame.paragraph(
                [
                    (
                        delta_text,
                        RunFormat(size_pt=11.0, bold=True, color=_delta_color(delta_text)),
                    )
                ],
                ParaFormat(align="ctr", space_before_pt=2.0),
            )


def add_harvey(
    slide: "SlideBuilder", box: Box, fraction: float, color: str = "accent1"
) -> None:
    """Add a harvey ball (0/25/50/75/100 %) centered in ``box``.

    ``fraction`` is rounded to the nearest quarter. 0 % renders as an
    outline-only ellipse, 100 % as a filled ellipse, and the quarters in
    between as the outline plus a pie wedge starting at 12 o'clock and
    sweeping clockwise.

    Args:
        slide: Target slide builder.
        box: Bounding box; the ball uses the largest centered square.
        fraction: Fill fraction in [0, 1].
        color: Theme color of outline and fill (default ``accent1``).

    Raises:
        BuildError: For a non-numeric or out-of-range ``fraction``.
    """
    quarter = _quarter(fraction)
    diameter = min(box.w, box.h)
    if diameter <= 0:
        raise BuildError(f"Harvey box must have a positive size, got {box!r}.")
    square = Box(
        box.x + (box.w - diameter) // 2,
        box.y + (box.h - diameter) // 2,
        diameter,
        diameter,
    )
    if quarter >= 1.0:
        slide.add_shape("ellipse", square, fill=color, line=color, line_w_pt=1.25)
        return
    ring = slide.add_shape("ellipse", square, line=color, line_w_pt=1.25)
    _set_no_fill(ring)
    if quarter > 0.0:
        adj1, adj2 = _harvey_angles(quarter)
        slide.add_shape(
            "pie",
            square,
            fill=color,
            line=color,
            line_w_pt=1.0,
            adj={"adj1": adj1, "adj2": adj2},
        )


def add_harvey_matrix(
    slide: "SlideBuilder",
    options: list,
    criteria: list,
    scores: list,
    box: Box = None,
) -> None:
    """Add a criteria × options matrix of harvey balls with a hairline grid.

    Option names form the header row (bold), criteria label the rows, and
    each cell holds a harvey ball for ``scores[row][col]``.

    Args:
        slide: Target slide builder.
        options: Column headers (at least one).
        criteria: Row labels (at least one).
        scores: ``len(criteria)`` rows of ``len(options)`` fractions each.
        box: Layout area; defaults to the content area.

    Raises:
        BuildError: For mismatched dimensions or invalid fractions.
    """
    _validate_matrix(options, criteria, scores, "add_harvey_matrix")
    if box is None:
        box = _content_box(slide)
    header_h = cm(0.8)
    label_w = int(box.w * 0.28)
    col_w = (box.w - label_w) / len(options)
    row_h = (box.h - header_h) / len(criteria)
    if row_h <= 0 or col_w <= 0:
        raise BuildError(f"Harvey matrix box {box!r} is too small for its grid.")
    for j, option in enumerate(options):
        frame = slide.add_textbox(
            Box(int(round(box.x + label_w + j * col_w)), box.y, int(round(col_w)), header_h),
            anchor="ctr",
        )
        frame.text(str(option), RunFormat(size_pt=11.0, bold=True, color="tx1"), ParaFormat(align="ctr"))
    for i, criterion in enumerate(criteria):
        frame = slide.add_textbox(
            Box(
                box.x + cm(0.1),
                int(round(box.y + header_h + i * row_h)),
                label_w - cm(0.2),
                int(round(row_h)),
            ),
            anchor="ctr",
        )
        frame.text(str(criterion), RunFormat(size_pt=11.0, color="tx1"), ParaFormat(align="l"))
    diameter = min(int(min(col_w, row_h) * 0.55), cm(1.0))
    for i in range(len(criteria)):
        for j in range(len(options)):
            cell_x = int(round(box.x + label_w + j * col_w))
            cell_y = int(round(box.y + header_h + i * row_h))
            ball = Box(
                cell_x + (int(round(col_w)) - diameter) // 2,
                cell_y + (int(round(row_h)) - diameter) // 2,
                diameter,
                diameter,
            )
            add_harvey(slide, ball, scores[i][j])
    _grid_lines(slide, box, header_h, label_w, col_w, row_h, len(criteria), len(options))


def add_traffic_light(slide: "SlideBuilder", box: Box, status: str) -> None:
    """Add a red/yellow/green traffic light indicator.

    Three small ellipses are drawn side by side; only the active one is
    saturated, the others stay very light grey. If ``box`` is narrower than
    ``cm(1.5)``, a single saturated dot is drawn instead.

    Args:
        slide: Target slide builder.
        box: Layout area for the lights.
        status: ``"red"``, ``"yellow"``, or ``"green"``.

    Raises:
        BuildError: For an unknown ``status``.
    """
    try:
        active_color = _STATUS_COLORS[status]
    except KeyError:
        raise BuildError(
            f"Unknown traffic light status {status!r}; "
            f"expected one of: {', '.join(_STATUS_COLORS)}."
        ) from None
    if box.w < cm(1.5):
        diameter = min(box.w, box.h)
        dot = Box(
            box.x + (box.w - diameter) // 2,
            box.y + (box.h - diameter) // 2,
            diameter,
            diameter,
        )
        slide.add_shape("ellipse", dot, fill=active_color)
        return
    gap = cm(0.12)
    diameter = min(box.h, (box.w - 2 * gap) // 3)
    x = box.x + (box.w - (3 * diameter + 2 * gap)) // 2
    y = box.y + (box.h - diameter) // 2
    for name, saturated in _STATUS_COLORS.items():
        light = Box(x, y, diameter, diameter)
        if name == status:
            slide.add_shape("ellipse", light, fill=saturated)
        else:
            slide.add_shape(
                "ellipse", light, fill=_INACTIVE_LIGHT, line=_HAIRLINE, line_w_pt=0.75
            )
        x += diameter + gap


def add_waterfall(
    slide: "SlideBuilder", box: Box, items: list, total_label: str = "Summe"
) -> None:
    """Add a shape-based waterfall (bridge) chart with a trailing total bar.

    Each item is ``{"label": str, "value": float}``. Positive bars are
    ``accent1``, negative bars ``accent2``, and the total bar ``dk2``.
    Floating bars are connected by dashed grey lines at their hand-over
    level, value labels sit above (or, for negatives, below) the bars,
    category labels run under the chart, and a solid baseline marks zero.
    The vertical scale is ``chart height / (cumulative range * 1.1)``
    (10 % headroom).

    Args:
        slide: Target slide builder.
        box: Layout area for the whole chart including category labels.
        items: Waterfall items in order (at least one).
        total_label: Category label of the total bar.

    Raises:
        BuildError: For empty/malformed items or a too-small box.
    """
    if not items:
        raise BuildError("add_waterfall needs at least one item.")
    values = []
    for item in items:
        _check_item(item, "Waterfall item", ("label", "value"), ("label", "value"))
        values.append(_as_number(item["value"], "Waterfall item value"))
    levels, total = _waterfall_levels(values)
    points = [0.0] + [end for _, end in levels]
    low = min(0.0, min(points))
    high = max(0.0, max(points))
    value_range = (high - low) or 1.0
    cat_h = cm(0.7)
    chart_h = box.h - cat_h
    if chart_h <= 0:
        raise BuildError(f"Waterfall box {box!r} is too small for a chart.")
    scale = chart_h / (value_range * 1.1)

    def y_of(value: float) -> float:
        return box.y + chart_h - ((value - low) + 0.05 * value_range) * scale

    bars = levels + [(0.0, total)]
    labels = [str(item["label"]) for item in items] + [str(total_label)]
    colors = ["accent1" if value >= 0 else "accent2" for value in values] + ["dk2"]
    label_values = values + [total]
    slot_w = box.w / len(bars)
    bar_w = slot_w * 0.6
    geometry = []
    for i, (start, end) in enumerate(bars):
        x = int(round(box.x + i * slot_w + (slot_w - bar_w) / 2))
        top = y_of(max(start, end))
        bottom = y_of(min(start, end))
        y = int(round(top))
        h = max(int(round(bottom - top)), pt(0.75))
        geometry.append((x, y, int(round(bar_w)), h))
        slide.add_shape("rect", Box(x, y, int(round(bar_w)), h), fill=colors[i])
    label_h = cm(0.5)
    for i, value in enumerate(label_values):
        x, y, w, h = geometry[i]
        slot_x = int(round(box.x + i * slot_w))
        label_y = y - label_h - pt(2) if value >= 0 else y + h + pt(2)
        frame = slide.add_textbox(
            Box(slot_x, label_y, int(round(slot_w)), label_h), anchor="ctr"
        )
        frame.text(
            _fmt_value(value),
            RunFormat(size_pt=10.0, bold=True, color="tx1"),
            ParaFormat(align="ctr"),
        )
    for i in range(len(values)):
        level_y = int(round(y_of(levels[i][1])))
        x_from = geometry[i][0] + geometry[i][2]
        x_to = geometry[i + 1][0]
        slide.add_line(
            x_from, level_y, x_to, level_y, color=_CONNECTOR_GREY, w_pt=0.75, dash="dash"
        )
    baseline_y = int(round(y_of(0.0)))
    slide.add_line(box.x, baseline_y, box.x + box.w, baseline_y, color="tx2", w_pt=1.0)
    for i, label in enumerate(labels):
        slot_x = int(round(box.x + i * slot_w))
        frame = slide.add_textbox(
            Box(slot_x, box.y + chart_h + pt(2), int(round(slot_w)), cat_h - pt(2)),
            anchor="t",
        )
        frame.text(label, RunFormat(size_pt=10.0, color="tx1"), ParaFormat(align="ctr"))


def _validate_chart(categories: list, values: list, what: str) -> float:
    """Validate chart inputs and return the (positive) maximum value."""
    if not categories or not values:
        raise BuildError(f"{what} needs at least one category and one value.")
    if len(categories) != len(values):
        raise BuildError(
            f"{what} needs as many values as categories: "
            f"{len(categories)} categories vs {len(values)} values."
        )
    numbers = [_as_number(value, f"{what} value") for value in values]
    if any(number < 0 for number in numbers):
        raise BuildError(
            f"{what} supports non-negative values only; use add_waterfall "
            f"for positive/negative bridges."
        )
    maximum = max(numbers)
    if maximum <= 0:
        raise BuildError(f"{what} needs at least one positive value.")
    return maximum


def add_bar_chart(
    slide: "SlideBuilder",
    box: Box,
    categories: list,
    values: list,
    color: str = "accent1",
    show_values: bool = True,
    horizontal: bool = True,
) -> None:
    """Add a shape-based bar chart (horizontal by default).

    Bars are scaled to the maximum value, take 60 % of their slot, and
    carry value labels at the bar ends. Category labels sit left of the
    bars and a thin neutral hairline marks the axis. With
    ``horizontal=False`` this delegates to :func:`add_column_chart`.

    Args:
        slide: Target slide builder.
        box: Layout area for the whole chart.
        categories: Category labels.
        values: Non-negative values, one per category, at least one > 0.
        color: Bar color (theme slot or hex).
        show_values: Render value labels at the bar ends.
        horizontal: Horizontal bars (default) or vertical columns.

    Raises:
        BuildError: For mismatched or invalid inputs.
    """
    if not horizontal:
        add_column_chart(slide, box, categories, values, color=color, show_values=show_values)
        return
    maximum = _validate_chart(categories, values, "add_bar_chart")
    label_w = min(int(box.w * 0.28), cm(4.5))
    value_w = cm(1.4) if show_values else 0
    plot_w = box.w - label_w - value_w
    if plot_w <= 0:
        raise BuildError(f"Bar chart box {box!r} is too narrow for its labels.")
    x0 = box.x + label_w
    slot_h = box.h / len(values)
    bar_h = slot_h * 0.6
    for i, value in enumerate(values):
        slot_y = box.y + i * slot_h
        bar_y = int(round(slot_y + (slot_h - bar_h) / 2))
        length = max(int(round(float(value) / maximum * plot_w)), 1)
        slide.add_shape("rect", Box(x0, bar_y, length, int(round(bar_h))), fill=color)
        frame = slide.add_textbox(
            Box(box.x, int(round(slot_y)), label_w - cm(0.25), int(round(slot_h))),
            anchor="ctr",
        )
        frame.text(
            str(categories[i]), RunFormat(size_pt=11.0, color="tx1"), ParaFormat(align="r")
        )
        if show_values:
            frame = slide.add_textbox(
                Box(x0 + length + pt(3), int(round(slot_y)), cm(1.25), int(round(slot_h))),
                anchor="ctr",
            )
            frame.text(
                _fmt_value(float(value)),
                RunFormat(size_pt=10.0, bold=True, color="tx1"),
                ParaFormat(align="l"),
            )
    slide.add_line(x0, box.y, x0, box.y + box.h, color=_HAIRLINE, w_pt=1.0)


def add_column_chart(
    slide: "SlideBuilder",
    box: Box,
    categories: list,
    values: list,
    color: str = "accent1",
    show_values: bool = True,
) -> None:
    """Add a shape-based column (vertical bar) chart.

    Columns are scaled to the maximum value and take 60 % of their slot;
    value labels sit above the columns, category labels below the axis,
    and a thin neutral hairline marks the baseline.

    Args:
        slide: Target slide builder.
        box: Layout area for the whole chart including labels.
        categories: Category labels.
        values: Non-negative values, one per category, at least one > 0.
        color: Column color (theme slot or hex).
        show_values: Render value labels above the columns.

    Raises:
        BuildError: For mismatched or invalid inputs.
    """
    maximum = _validate_chart(categories, values, "add_column_chart")
    cat_h = cm(0.7)
    top_pad = cm(0.55) if show_values else 0
    plot_h = box.h - cat_h - top_pad
    if plot_h <= 0:
        raise BuildError(f"Column chart box {box!r} is too small for its labels.")
    baseline = box.y + top_pad + plot_h
    slot_w = box.w / len(values)
    bar_w = slot_w * 0.6
    for i, value in enumerate(values):
        slot_x = box.x + i * slot_w
        bar_x = int(round(slot_x + (slot_w - bar_w) / 2))
        height = max(int(round(float(value) / maximum * plot_h)), 1)
        bar_y = baseline - height
        slide.add_shape("rect", Box(bar_x, bar_y, int(round(bar_w)), height), fill=color)
        frame = slide.add_textbox(
            Box(int(round(slot_x)), baseline + pt(2), int(round(slot_w)), cat_h - pt(2)),
            anchor="t",
        )
        frame.text(
            str(categories[i]), RunFormat(size_pt=10.0, color="tx1"), ParaFormat(align="ctr")
        )
        if show_values:
            frame = slide.add_textbox(
                Box(int(round(slot_x)), bar_y - cm(0.55), int(round(slot_w)), cm(0.5)),
                anchor="b",
            )
            frame.text(
                _fmt_value(float(value)),
                RunFormat(size_pt=10.0, bold=True, color="tx1"),
                ParaFormat(align="ctr"),
            )
    slide.add_line(box.x, baseline, box.x + box.w, baseline, color=_HAIRLINE, w_pt=1.0)


def add_timeline(slide: "SlideBuilder", phases: list, box: Box = None) -> None:
    """Add a full-width chevron phase band (timeline / roadmap).

    Each phase is ``{"label": str, "sub": str | None, "active": bool}``.
    Chevrons have equal widths with a slight overlap; the first uses the
    ``homePlate`` preset, the rest ``chevron``. Active phases are filled
    ``accent1`` with white bold text, inactive ones ``bg2`` with ``tx1``
    text. Truthy ``sub`` values become small labels under their chevron.

    Args:
        slide: Target slide builder.
        phases: Phase dicts in order (at least one).
        box: Layout area; defaults to the content area.

    Raises:
        BuildError: For empty/malformed phases or a too-small box.
    """
    if not phases:
        raise BuildError("add_timeline needs at least one phase.")
    for phase in phases:
        _check_item(phase, "Timeline phase", ("label",), ("label", "sub", "active"))
    if box is None:
        box = _content_box(slide)
    has_sub = any(phase.get("sub") for phase in phases)
    sub_h = cm(0.8) if has_sub else 0
    band_h = min(cm(1.7), box.h - sub_h)
    if band_h <= 0:
        raise BuildError(f"Timeline box {box!r} is too small for a chevron band.")
    n = len(phases)
    overlap = band_h // 3
    width = (box.w + overlap * (n - 1)) // n
    adj_val = int(round(overlap / band_h * 100000))
    for i, phase in enumerate(phases):
        x = box.x + i * (width - overlap)
        chevron_w = width if i < n - 1 else box.x + box.w - x
        active = bool(phase.get("active"))
        if active:
            text_fmt = RunFormat(size_pt=12.0, bold=True, color="bg1")
        else:
            text_fmt = RunFormat(size_pt=12.0, color="tx1")
        slide.add_shape(
            "homePlate" if i == 0 else "chevron",
            Box(x, box.y, chevron_w, band_h),
            fill="accent1" if active else "bg2",
            line="bg1",
            line_w_pt=1.0,
            text=str(phase["label"]),
            text_fmt=text_fmt,
            adj={"adj": adj_val},
        )
        sub = phase.get("sub")
        if sub:
            frame = slide.add_textbox(
                Box(x, box.y + band_h + pt(2), chevron_w, sub_h - pt(2)), anchor="t"
            )
            frame.text(
                str(sub), RunFormat(size_pt=10.0, color="tx2"), ParaFormat(align="ctr")
            )


def add_comparison(
    slide: "SlideBuilder",
    options: list,
    criteria: list,
    cells: list,
    box: Box = None,
) -> None:
    """Add an options × criteria comparison matrix with text/harvey cells.

    The header row (option names, white bold on an ``accent1`` band) tops a
    manually drawn grid: criteria labels on the left, zebra striping on
    every second row, and thin hairlines between rows and columns. String
    cells render as centered text; numeric cells render as harvey balls
    (which is why this is built from shapes, not a native ``a:tbl``).

    Args:
        slide: Target slide builder.
        options: Column headers (at least one).
        criteria: Row labels (at least one).
        cells: ``len(criteria)`` rows of ``len(options)`` cells; each cell
            is a string (text) or a number in [0, 1] (harvey ball).
        box: Layout area; defaults to the content area.

    Raises:
        BuildError: For mismatched dimensions or invalid harvey fractions.
    """
    _validate_matrix(options, criteria, cells, "add_comparison")
    if box is None:
        box = _content_box(slide)
    header_h = cm(0.9)
    label_w = int(box.w * 0.30)
    col_w = (box.w - label_w) / len(options)
    row_h = (box.h - header_h) / len(criteria)
    if row_h <= 0 or col_w <= 0:
        raise BuildError(f"Comparison box {box!r} is too small for its grid.")
    slide.add_shape("rect", Box(box.x, box.y, box.w, header_h), fill="accent1")
    for i in range(len(criteria)):
        if i % 2 == 1:
            slide.add_shape(
                "rect",
                Box(
                    box.x,
                    int(round(box.y + header_h + i * row_h)),
                    box.w,
                    int(round(row_h)),
                ),
                fill=_ZEBRA,
            )
    _grid_lines(slide, box, header_h, label_w, col_w, row_h, len(criteria), len(options))
    for j, option in enumerate(options):
        frame = slide.add_textbox(
            Box(int(round(box.x + label_w + j * col_w)), box.y, int(round(col_w)), header_h),
            anchor="ctr",
        )
        frame.text(
            str(option), RunFormat(size_pt=11.0, bold=True, color="bg1"), ParaFormat(align="ctr")
        )
    for i, criterion in enumerate(criteria):
        frame = slide.add_textbox(
            Box(
                box.x + cm(0.2),
                int(round(box.y + header_h + i * row_h)),
                label_w - cm(0.3),
                int(round(row_h)),
            ),
            anchor="ctr",
        )
        frame.text(str(criterion), RunFormat(size_pt=11.0, color="tx1"), ParaFormat(align="l"))
    ball = min(int(min(col_w, row_h) * 0.5), cm(0.9))
    for i in range(len(criteria)):
        for j in range(len(options)):
            cell_x = int(round(box.x + label_w + j * col_w))
            cell_y = int(round(box.y + header_h + i * row_h))
            cell_w = int(round(col_w))
            cell_h = int(round(row_h))
            value = cells[i][j]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                add_harvey(
                    slide,
                    Box(
                        cell_x + (cell_w - ball) // 2,
                        cell_y + (cell_h - ball) // 2,
                        ball,
                        ball,
                    ),
                    float(value),
                )
            else:
                frame = slide.add_textbox(
                    Box(cell_x, cell_y, cell_w, cell_h), anchor="ctr"
                )
                frame.text(
                    str(value), RunFormat(size_pt=11.0, color="tx1"), ParaFormat(align="ctr")
                )


def add_callout(
    slide: "SlideBuilder", text: str, kind: str = "info", box: Box = None
) -> None:
    """Add a callout box: rounded rectangle with a colored left accent bar.

    ``kind`` selects the accent bar color: ``info`` → ``accent1``,
    ``success`` → green, ``warning`` → amber, ``key`` → ``dk2``. The body
    is a subtle neutral fill (``bg2``) with 12 pt ``tx1`` text.

    Args:
        slide: Target slide builder.
        text: Callout text (newlines become separate paragraphs).
        kind: ``"info"``, ``"success"``, ``"warning"``, or ``"key"``.
        box: Layout area; defaults to a band at the bottom of the content
            area (full content width, ``cm(1.5)`` high).

    Raises:
        BuildError: For an unknown ``kind``.
    """
    try:
        bar_color = _CALLOUT_COLORS[kind]
    except KeyError:
        raise BuildError(
            f"Unknown callout kind {kind!r}; "
            f"expected one of: {', '.join(_CALLOUT_COLORS)}."
        ) from None
    if box is None:
        margin = cm(1.2)
        height = cm(1.5)
        box = Box(
            margin, slide.height - margin - height, slide.width - 2 * margin, height
        )
    slide.add_shape("roundRect", box, fill="bg2", adj={"adj": 10000})
    inset = cm(0.18)
    slide.add_shape(
        "rect",
        Box(box.x + inset, box.y + inset, cm(0.12), box.h - 2 * inset),
        fill=bar_color,
    )
    frame = slide.add_textbox(
        Box(box.x + cm(0.6), box.y + pt(2), box.w - cm(0.9), box.h - pt(4)),
        anchor="ctr",
    )
    frame.text(str(text), RunFormat(size_pt=12.0, color="tx1"), ParaFormat(align="l"))


def add_section_number(slide: "SlideBuilder", current: int, total: int) -> None:
    """Add a small ``"3 / 12"`` section indicator in the top-right corner.

    Args:
        slide: Target slide builder.
        current: Current section/slide number.
        total: Total number of sections/slides.
    """
    width = cm(2.2)
    frame = slide.add_textbox(
        Box(slide.width - cm(0.5) - width, cm(0.4), width, cm(0.6)), anchor="t"
    )
    frame.text(
        f"{current} / {total}",
        RunFormat(size_pt=10.0, color="tx2"),
        ParaFormat(align="r"),
    )
