"""English Metric Unit (EMU) conversions and geometry primitives.

All DeckForge coordinates and sizes are integers in EMU:
1 inch = 914400 EMU, 1 cm = 360000 EMU, 1 pt = 12700 EMU.
DrawingML font sizes are expressed in hundredths of a point
(``sz="1800"`` means 18 pt); use :func:`hundredths_pt` for those.
"""

from __future__ import annotations

from typing import NamedTuple

EMU_PER_INCH: int = 914400
EMU_PER_CM: int = 360000
EMU_PER_PT: int = 12700

SLIDE_W_16_9: int = 12192000
SLIDE_H_16_9: int = 6858000


def inches(v: float) -> int:
    """Convert inches to EMU, rounded to the nearest integer."""
    return int(round(v * EMU_PER_INCH))


def cm(v: float) -> int:
    """Convert centimetres to EMU, rounded to the nearest integer."""
    return int(round(v * EMU_PER_CM))


def pt(v: float) -> int:
    """Convert points to EMU, rounded to the nearest integer."""
    return int(round(v * EMU_PER_PT))


def emu_to_pt(v: int) -> float:
    """Convert EMU to points."""
    return v / EMU_PER_PT


def hundredths_pt(size_pt: float) -> int:
    """Convert a point size to hundredths of a point (18 -> 1800).

    This is the unit DrawingML uses for run sizes (``a:rPr sz=...``).
    """
    return int(round(size_pt * 100))


class Box(NamedTuple):
    """Axis-aligned rectangle; all fields in EMU."""

    x: int
    y: int
    w: int
    h: int

    def inset(self, dx: int, dy: int) -> "Box":
        """Return a new :class:`Box` shrunk by ``dx`` left/right and ``dy`` top/bottom."""
        return Box(self.x + dx, self.y + dy, self.w - 2 * dx, self.h - 2 * dy)
