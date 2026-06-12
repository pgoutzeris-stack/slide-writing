"""Theme parsing and theme-aware color handling for DeckForge.

This module reads ``ppt/theme/theme1.xml`` into a small design model
(:class:`Theme` with :class:`ColorScheme` and :class:`FontScheme`), resolves
color names against a theme plus a master color map (:class:`ColorResolver`),
and provides element factories for DrawingML color/fill markup
(:func:`srgb_fill`, :func:`scheme_fill`, :func:`color_el`, :func:`fill_for`).

Color values in the model are always ``"RRGGBB"`` strings — uppercase hex
without a leading ``#``. Generated elements use ``<a:schemeClr>`` for theme
slots and logical names (theme-true output) and ``<a:srgbClr>`` for literal
hex colors.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .errors import BuildError, ParseError
from .xmlcore import el, find, get, parse_xml, sub

#: The twelve color slots of an OOXML theme color scheme, in schema order.
SCHEME_SLOTS = (
    "dk1",
    "lt1",
    "dk2",
    "lt2",
    "accent1",
    "accent2",
    "accent3",
    "accent4",
    "accent5",
    "accent6",
    "hlink",
    "folHlink",
)

#: Logical color names that resolve through the master ``p:clrMap`` and are
#: valid as ``<a:schemeClr val="…"/>`` values in addition to the theme slots.
_LOGICAL_NAMES = ("bg1", "tx1", "bg2", "tx2")

#: Every name accepted as ``<a:schemeClr val="…"/>`` by :func:`color_el`.
_SCHEME_CLR_NAMES = frozenset(SCHEME_SLOTS) | frozenset(_LOGICAL_NAMES)

#: Fallback RGB values for ``<a:sysClr>`` without a ``lastClr`` attribute.
_SYS_CLR_FALLBACK = {"windowText": "000000", "window": "FFFFFF"}

_HEX_RE = re.compile(r"#?([0-9A-Fa-f]{6})\Z")


def _normalize_hex(value: str) -> str | None:
    """Return ``value`` as uppercase 6-digit hex without ``#``, or None."""
    match = _HEX_RE.match(value)
    if match is None:
        return None
    return match.group(1).upper()


@dataclass
class ColorScheme:
    """The twelve theme colors, each as an uppercase ``"RRGGBB"`` string."""

    dk1: str
    lt1: str
    dk2: str
    lt2: str
    accent1: str
    accent2: str
    accent3: str
    accent4: str
    accent5: str
    accent6: str
    hlink: str
    folHlink: str

    def get(self, slot: str) -> str:
        """Return the RGB value for a theme slot like ``"accent1"``.

        Raises :class:`ParseError` if ``slot`` is not one of
        :data:`SCHEME_SLOTS`.
        """
        if slot not in SCHEME_SLOTS:
            raise ParseError(
                f"Unknown theme color slot {slot!r}; "
                f"expected one of: {', '.join(SCHEME_SLOTS)}"
            )
        return getattr(self, slot)


@dataclass
class FontScheme:
    """Major (headings) and minor (body) latin typefaces of the theme."""

    major_latin: str
    minor_latin: str


@dataclass
class Theme:
    """Parsed theme part: name, color scheme, font scheme, and the XML root.

    ``element`` keeps the full parsed ``<a:theme>`` root so that information
    beyond the extracted model (e.g. ``a:fmtScheme``) stays available with
    full fidelity.
    """

    name: str
    colors: ColorScheme
    fonts: FontScheme
    element: ET.Element


def _slot_rgb(slot_element: ET.Element, slot: str) -> str:
    """Extract the RGB value from one ``a:clrScheme`` slot child element."""
    srgb = find(slot_element, "a:srgbClr")
    if srgb is not None:
        raw = get(srgb, "val", "") or ""
        rgb = _normalize_hex(raw)
        if rgb is None:
            raise ParseError(
                f"Theme slot a:{slot} has invalid a:srgbClr value {raw!r}; "
                f"expected six hex digits"
            )
        return rgb
    sysclr = find(slot_element, "a:sysClr")
    if sysclr is not None:
        last = get(sysclr, "lastClr")
        if last is not None:
            rgb = _normalize_hex(last)
            if rgb is None:
                raise ParseError(
                    f"Theme slot a:{slot} has invalid a:sysClr lastClr "
                    f"value {last!r}; expected six hex digits"
                )
            return rgb
        sys_val = get(sysclr, "val", "") or ""
        fallback = _SYS_CLR_FALLBACK.get(sys_val)
        if fallback is None:
            raise ParseError(
                f"Theme slot a:{slot} uses a:sysClr val={sys_val!r} without "
                f"a lastClr attribute and no known fallback"
            )
        return fallback
    raise ParseError(
        f"Theme slot a:{slot} contains neither a:srgbClr nor a:sysClr; "
        f"other color definitions are not supported"
    )


def _latin_typeface(root: ET.Element, font_tag: str) -> str:
    """Read ``a:latin@typeface`` from ``a:majorFont`` or ``a:minorFont``."""
    latin = find(root, f"a:themeElements/a:fontScheme/{font_tag}/a:latin")
    if latin is None:
        raise ParseError(
            f"Theme font scheme is missing a:themeElements/a:fontScheme/"
            f"{font_tag}/a:latin"
        )
    return get(latin, "typeface", "") or ""


def parse_theme(blob: bytes) -> Theme:
    """Parse a theme part (``theme1.xml``) into a :class:`Theme`.

    Reads ``a:themeElements/a:clrScheme`` (each slot child holding
    ``a:srgbClr@val`` or ``a:sysClr`` — ``lastClr`` preferred, with the
    fallbacks ``windowText`` → ``000000`` and ``window`` → ``FFFFFF``) and
    ``a:fontScheme`` (``a:majorFont``/``a:minorFont`` latin typefaces).
    The parsed XML root is kept on :attr:`Theme.element`.

    Raises :class:`ParseError` for malformed XML, missing scheme elements,
    missing slots, or unsupported color definitions.
    """
    root = parse_xml(blob)
    clr_scheme = find(root, "a:themeElements/a:clrScheme")
    if clr_scheme is None:
        raise ParseError("Theme is missing a:themeElements/a:clrScheme")
    values: dict[str, str] = {}
    for slot in SCHEME_SLOTS:
        child = find(clr_scheme, f"a:{slot}")
        if child is None:
            raise ParseError(f"Theme color scheme is missing slot a:{slot}")
        values[slot] = _slot_rgb(child, slot)
    fonts = FontScheme(
        major_latin=_latin_typeface(root, "a:majorFont"),
        minor_latin=_latin_typeface(root, "a:minorFont"),
    )
    return Theme(
        name=get(root, "name", "") or "",
        colors=ColorScheme(**values),
        fonts=fonts,
        element=root,
    )


class ColorResolver:
    """Resolves color names to ``"RRGGBB"`` values against a theme.

    Accepted names, in resolution order:

    1. theme slots (``"dk1"`` … ``"folHlink"``) — read directly from the
       theme's :class:`ColorScheme`;
    2. logical names (``"tx1"``, ``"bg1"``, ``"tx2"``, ``"bg2"``, accents,
       ``"hlink"``/``"folHlink"``) — mapped to a theme slot through the
       master's ``p:clrMap`` dictionary;
    3. literal ``"RRGGBB"`` / ``"#RRGGBB"`` hex values — normalized to
       uppercase six-digit hex.

    Anything else raises :class:`ParseError`.
    """

    def __init__(self, theme: Theme, clr_map: dict[str, str]):
        """Create a resolver from a theme and a logical→slot color map."""
        self.theme = theme
        self.clr_map: dict[str, str] = dict(clr_map)

    def rgb(self, name: str) -> str:
        """Resolve ``name`` to an uppercase ``"RRGGBB"`` string.

        Raises :class:`ParseError` (naming the input) if ``name`` is neither
        a theme slot, a mapped logical name, nor a valid hex literal.
        """
        if name in SCHEME_SLOTS:
            return self.theme.colors.get(name)
        if name in self.clr_map:
            return self.theme.colors.get(self.clr_map[name])
        rgb = _normalize_hex(name)
        if rgb is not None:
            return rgb
        known = ", ".join(list(SCHEME_SLOTS) + sorted(self.clr_map))
        raise ParseError(
            f"Cannot resolve color {name!r}; expected one of: {known}, "
            f"or an 'RRGGBB'/'#RRGGBB' literal"
        )


def srgb_fill(rgb: str) -> ET.Element:
    """Return ``<a:solidFill><a:srgbClr val="RRGGBB"/></a:solidFill>``.

    ``rgb`` must be a hex literal (``"RRGGBB"`` or ``"#RRGGBB"``); it is
    normalized to uppercase. Raises :class:`ParseError` otherwise.
    """
    value = _normalize_hex(rgb)
    if value is None:
        raise ParseError(
            f"Invalid RGB literal {rgb!r}; expected 'RRGGBB' or '#RRGGBB'"
        )
    fill = el("a:solidFill")
    sub(fill, "a:srgbClr", {"val": value})
    return fill


def scheme_fill(slot: str) -> ET.Element:
    """Return ``<a:solidFill><a:schemeClr val="…"/></a:solidFill>``.

    ``slot`` may be a theme slot (``"accent1"``) or a logical name
    (``"tx1"``, ``"bg1"``, …). Raises :class:`ParseError` for unknown names.
    """
    if slot not in _SCHEME_CLR_NAMES:
        raise ParseError(
            f"Unknown scheme color {slot!r}; expected one of: "
            f"{', '.join(SCHEME_SLOTS + _LOGICAL_NAMES)}"
        )
    fill = el("a:solidFill")
    sub(fill, "a:schemeClr", {"val": slot})
    return fill


def color_el(color: str) -> ET.Element:
    """Return a color element for ``color``.

    Theme slots and logical names yield ``<a:schemeClr val="…"/>``; hex
    literals (``"RRGGBB"`` or ``"#RRGGBB"``) yield ``<a:srgbClr val="…"/>``
    with the value normalized to uppercase. Raises :class:`ParseError`
    (naming the input) for anything else.
    """
    if color in _SCHEME_CLR_NAMES:
        return el("a:schemeClr", {"val": color})
    rgb = _normalize_hex(color)
    if rgb is not None:
        return el("a:srgbClr", {"val": rgb})
    raise ParseError(
        f"Unknown color {color!r}; expected one of: "
        f"{', '.join(SCHEME_SLOTS + _LOGICAL_NAMES)}, "
        f"or an 'RRGGBB'/'#RRGGBB' literal"
    )


def fill_for(color: str, alpha_pct: int | None = None) -> ET.Element:
    """Return an ``<a:solidFill>`` wrapping :func:`color_el` for ``color``.

    If ``alpha_pct`` is given (opacity in percent, 0–100), an
    ``<a:alpha val="alpha_pct * 1000"/>`` child is added inside the color
    element. Raises :class:`ParseError` for unknown colors and
    :class:`BuildError` for an out-of-range ``alpha_pct``.
    """
    if alpha_pct is not None and not 0 <= alpha_pct <= 100:
        raise BuildError(
            f"alpha_pct must be between 0 and 100, got {alpha_pct}"
        )
    fill = el("a:solidFill")
    color_node = color_el(color)
    fill.append(color_node)
    if alpha_pct is not None:
        sub(color_node, "a:alpha", {"val": str(alpha_pct * 1000)})
    return fill
