"""Text engine: DrawingML runs, paragraphs, and text bodies.

This module builds the ``<a:r>``, ``<a:p>``, and ``<p:txBody>`` structures
used everywhere text appears on a slide, and provides :class:`TextFrame`,
a mutating wrapper around an existing ``<p:txBody>`` element.

OOXML ordering rules honoured here:

* ``<a:rPr>`` children: fill (``a:solidFill``) before ``a:latin``.
* ``<a:pPr>`` children: ``a:lnSpc``, ``a:spcBef``, ``a:spcAft``, then the
  bullet element (``a:buNone`` / ``a:buChar``).
* ``<p:txBody>`` children: ``a:bodyPr``, ``a:lstStyle``, then ``a:p``
  paragraphs (at least one).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, fields, replace
from typing import Any, Dict, Tuple, Union

from .emu import hundredths_pt
from .errors import BuildError
from .theme import color_el
from .xmlcore import el, qn, sub

__all__ = [
    "RunFormat",
    "ParaFormat",
    "BulletItem",
    "run_el",
    "para_el",
    "txbody_el",
    "TextFrame",
]

#: A bullet entry: plain text, ``(text, level)``, or a dict with ``text``,
#: optional ``level`` and any :class:`RunFormat` field as override.
BulletItem = Union[str, Tuple[str, int], Dict[str, Any]]


@dataclass
class RunFormat:
    """Character-level formatting for a single text run.

    ``None`` fields are omitted from the XML so the run inherits from the
    placeholder/layout/master hierarchy.
    """

    size_pt: float | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    color: str | None = None        # scheme slot / logical name / "RRGGBB"
    font: str | None = None         # explicit typeface, or "+mj-lt"/"+mn-lt"


@dataclass
class ParaFormat:
    """Paragraph-level formatting (``<a:pPr>``)."""

    level: int = 0                  # outline level 0-8
    align: str | None = None        # "l", "ctr", "r", "just"
    space_before_pt: float | None = None
    space_after_pt: float | None = None
    line_spacing: float | None = None     # multiple, e.g. 1.0, 1.2
    bullet: str | None = None       # None=inherit, "none"=buNone, else literal char


_RUN_FIELD_NAMES = frozenset(f.name for f in fields(RunFormat))


def _has_run_formatting(fmt: RunFormat | None) -> bool:
    """Return ``True`` if any :class:`RunFormat` field is set."""
    if fmt is None:
        return False
    return any(getattr(fmt, name) is not None for name in _RUN_FIELD_NAMES)


def _rpr_el(fmt: RunFormat, lang: str) -> ET.Element:
    """Build an ``<a:rPr>`` element for a run with formatting.

    Children are emitted in OOXML order: fill first, then ``a:latin``.
    """
    rpr = el("a:rPr", {"lang": lang})
    if fmt.size_pt is not None:
        rpr.set("sz", str(hundredths_pt(fmt.size_pt)))
    if fmt.bold is not None:
        rpr.set("b", "1" if fmt.bold else "0")
    if fmt.italic is not None:
        rpr.set("i", "1" if fmt.italic else "0")
    if fmt.underline is not None:
        rpr.set("u", "sng" if fmt.underline else "none")
    if fmt.color is not None:
        fill = sub(rpr, "a:solidFill")
        fill.append(color_el(fmt.color))
    if fmt.font is not None:
        sub(rpr, "a:latin", {"typeface": fmt.font})
    return rpr


def run_el(text: str, fmt: RunFormat | None = None, lang: str = "de-DE") -> ET.Element:
    """Create an ``<a:r>`` run element containing ``text``.

    The ``<a:rPr>`` element is emitted only when ``fmt`` carries at least one
    set field; otherwise the run fully inherits its formatting. Text is never
    pre-escaped — ElementTree handles ``&``, ``<``, ``>`` etc. on serialize.
    """
    run = el("a:r")
    if fmt is not None and _has_run_formatting(fmt):
        run.append(_rpr_el(fmt, lang))
    el("a:t", parent=run, text=text)
    return run


def _ppr_el(pf: ParaFormat) -> ET.Element | None:
    """Build ``<a:pPr>`` for ``pf``; return ``None`` if nothing needs emitting.

    ``lvl`` is always emitted when ``level > 0`` and omitted when 0 (the
    OOXML default). Children appear in schema order: ``a:lnSpc``,
    ``a:spcBef``, ``a:spcAft``, bullet.
    """
    if not 0 <= pf.level <= 8:
        raise BuildError(f"Paragraph level must be 0-8, got {pf.level}")
    has_other = (
        pf.align is not None
        or pf.space_before_pt is not None
        or pf.space_after_pt is not None
        or pf.line_spacing is not None
        or pf.bullet is not None
    )
    if pf.level == 0 and not has_other:
        return None
    ppr = el("a:pPr")
    if pf.level > 0:
        ppr.set("lvl", str(pf.level))
    if pf.align is not None:
        ppr.set("algn", pf.align)
    if pf.line_spacing is not None:
        lnspc = sub(ppr, "a:lnSpc")
        sub(lnspc, "a:spcPct", {"val": str(int(round(pf.line_spacing * 100000)))})
    if pf.space_before_pt is not None:
        spcbef = sub(ppr, "a:spcBef")
        sub(spcbef, "a:spcPts", {"val": str(int(round(pf.space_before_pt * 100)))})
    if pf.space_after_pt is not None:
        spcaft = sub(ppr, "a:spcAft")
        sub(spcaft, "a:spcPts", {"val": str(int(round(pf.space_after_pt * 100)))})
    if pf.bullet is not None:
        if pf.bullet == "none":
            sub(ppr, "a:buNone")
        else:
            sub(ppr, "a:buChar", {"char": pf.bullet})
    return ppr


def para_el(
    runs: list[ET.Element] | str,
    pf: ParaFormat | None = None,
    default_fmt: RunFormat | None = None,
) -> ET.Element:
    """Create an ``<a:p>`` paragraph element.

    ``runs`` is either a list of prebuilt ``<a:r>`` elements or a plain
    string. A string is converted into runs formatted with ``default_fmt``;
    embedded ``"\\n"`` become ``<a:br/>`` soft line breaks *within* this
    paragraph (use :meth:`TextFrame.text` to map newlines to separate
    paragraphs instead). The ``<a:pPr>`` is omitted entirely when ``pf`` has
    nothing to say.
    """
    para = el("a:p")
    if pf is not None:
        ppr = _ppr_el(pf)
        if ppr is not None:
            para.append(ppr)
    if isinstance(runs, str):
        for i, line in enumerate(runs.split("\n")):
            if i:
                el("a:br", parent=para)
            if line:
                para.append(run_el(line, default_fmt))
    else:
        for run in runs:
            para.append(run)
    return para


def txbody_el(
    paragraphs: list[ET.Element],
    *,
    anchor: str | None = None,
    wrap: bool = True,
    autofit: str | None = "norm",
    insets_emu: tuple[int, int, int, int] | None = None,
) -> ET.Element:
    """Create a ``<p:txBody>`` element with ``a:bodyPr``, ``a:lstStyle``, paragraphs.

    ``anchor`` is the vertical anchor ("t", "ctr", "b"); ``wrap=False`` emits
    ``wrap="none"``. ``insets_emu`` is ``(left, top, right, bottom)`` in EMU
    mapped to ``lIns/tIns/rIns/bIns``. ``autofit`` selects the autofit child:
    ``None`` (inherit, no element), ``"norm"`` (``<a:normAutofit/>``),
    ``"shrink"`` (``<a:normAutofit>`` with a reduced font scale), or
    ``"spAuto"`` (``<a:spAutoFit/>``). At least one ``<a:p>`` is always
    present, so the body stays schema-valid even when ``paragraphs`` is empty.
    """
    body = el("p:txBody")
    bodypr = sub(body, "a:bodyPr")
    if insets_emu is not None:
        left, top, right, bottom = insets_emu
        bodypr.set("lIns", str(left))
        bodypr.set("tIns", str(top))
        bodypr.set("rIns", str(right))
        bodypr.set("bIns", str(bottom))
    if not wrap:
        bodypr.set("wrap", "none")
    if anchor is not None:
        bodypr.set("anchor", anchor)
    if autofit == "norm":
        sub(bodypr, "a:normAutofit")
    elif autofit == "shrink":
        sub(bodypr, "a:normAutofit", {"fontScale": "85000", "lnSpcReduction": "10000"})
    elif autofit == "spAuto":
        sub(bodypr, "a:spAutoFit")
    elif autofit is not None:
        raise BuildError(
            f"Unknown autofit mode {autofit!r}; expected None, 'norm', 'shrink' or 'spAuto'"
        )
    sub(body, "a:lstStyle")
    if paragraphs:
        for para in paragraphs:
            body.append(para)
    else:
        sub(body, "a:p")
    return body


def _merge_fmt(base: RunFormat | None, overrides: dict[str, Any]) -> RunFormat | None:
    """Merge ``overrides`` (RunFormat field values) onto ``base``."""
    if not overrides:
        return base
    return replace(base if base is not None else RunFormat(), **overrides)


def _parse_bullet_item(
    item: BulletItem, base_fmt: RunFormat | None
) -> tuple[str, int, RunFormat | None]:
    """Normalize a :data:`BulletItem` into ``(text, level, fmt)``."""
    if isinstance(item, str):
        return item, 0, base_fmt
    if isinstance(item, (tuple, list)):
        if len(item) != 2:
            raise BuildError(
                f"Bullet tuple must be (text, level), got {len(item)} elements: {item!r}"
            )
        text, level = item
        return str(text), int(level), base_fmt
    if isinstance(item, dict):
        if "text" not in item:
            raise BuildError(f"Bullet dict needs a 'text' key: {item!r}")
        allowed = {"text", "level"} | _RUN_FIELD_NAMES
        unknown = set(item) - allowed
        if unknown:
            raise BuildError(
                f"Unknown bullet key(s) {sorted(unknown)!r}; "
                f"allowed: {sorted(allowed)!r}"
            )
        overrides = {k: v for k, v in item.items() if k in _RUN_FIELD_NAMES}
        return str(item["text"]), int(item.get("level", 0)), _merge_fmt(base_fmt, overrides)
    raise BuildError(f"Unsupported bullet item type {type(item).__name__}: {item!r}")


class TextFrame:
    """Wrapper around an existing ``<p:txBody>`` element inside a shape.

    All methods mutate the wrapped element in place and return ``self`` for
    chaining. ``a:bodyPr`` and ``a:lstStyle`` are always preserved.
    """

    def __init__(self, txbody: ET.Element):
        """Wrap ``txbody``, an existing ``<p:txBody>`` (or ``a:txBody``) element."""
        self.element = txbody

    def clear(self) -> None:
        """Remove all ``<a:p>`` paragraphs, keeping ``a:bodyPr``/``a:lstStyle``."""
        for para in list(self.element):
            if para.tag == qn("a:p"):
                self.element.remove(para)

    def _drop_lone_empty_paragraph(self) -> None:
        """Drop the single empty placeholder ``<a:p>`` before appending content."""
        paras = [child for child in self.element if child.tag == qn("a:p")]
        if len(paras) == 1 and len(paras[0]) == 0 and not (paras[0].text or "").strip():
            self.element.remove(paras[0])

    def text(
        self,
        value: str,
        fmt: RunFormat | None = None,
        pf: ParaFormat | None = None,
    ) -> "TextFrame":
        """Replace the entire content with ``value``.

        Multi-line strings (``"a\\nb"``) become one paragraph per line; empty
        lines become empty paragraphs.
        """
        self.clear()
        for line in str(value).split("\n"):
            if line:
                self.element.append(para_el([run_el(line, fmt)], pf))
            else:
                self.element.append(para_el([], pf))
        return self

    def paragraph(
        self,
        value: str | list[tuple[str, RunFormat | None]],
        pf: ParaFormat | None = None,
    ) -> "TextFrame":
        """Append one paragraph.

        ``value`` is either a plain string (one run, newlines become soft
        breaks) or a list of ``(text, RunFormat | None)`` run tuples. A lone
        empty placeholder paragraph left from shape creation is removed first.
        """
        self._drop_lone_empty_paragraph()
        if isinstance(value, str):
            self.element.append(para_el(value, pf))
        else:
            runs = [run_el(text, fmt) for text, fmt in value]
            self.element.append(para_el(runs, pf))
        return self

    def bullets(
        self,
        items: "list[BulletItem]",
        base_fmt: RunFormat | None = None,
    ) -> "TextFrame":
        """Replace the content with a bullet list.

        Each item is a :data:`BulletItem`: a string (level 0), a
        ``(text, level)`` tuple, or a dict with ``text``, optional ``level``
        and per-item :class:`RunFormat` overrides merged onto ``base_fmt``.
        Bullet glyphs are inherited from the layout/master.
        """
        self.clear()
        for item in items:
            text, level, fmt = _parse_bullet_item(item, base_fmt)
            self.element.append(para_el(text, ParaFormat(level=level), default_fmt=fmt))
        return self
