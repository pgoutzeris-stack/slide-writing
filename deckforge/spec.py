"""JSON deck specification engine: declarative deck building.

A *spec* is a plain JSON object describing a whole deck; DeckForge renders
it against any template (or the bootstrap default). Unknown keys anywhere
in the spec are ignored, so specs stay forward compatible.

Top-level keys (all optional except ``slides``)::

    {
      "template": "pfad/zum/template.pptx",   # overridden by the function argument
      "accent":   "206EFB",                   # accent1 when no template is given
      "title":    "Deck-Titel",               # docProps core title
      "author":   "ROOTS",                    # docProps core creator
      "slides":   [ ... ]                     # required: list of slide objects
    }

Slide types (each slide object needs ``"type"``; ``"layout"`` may override
the layout choice on any type):

``title``
    ``{"type": "title", "title": str, "subtitle"?: str}``
``section``
    ``{"type": "section", "title": str, "number"?: str|int}``
``bullets``
    ``{"type": "bullets", "title": str,
       "bullets": [str | {"text": str, "level"?: 0-8, ...RunFormat}],
       "callout"?: {"text": str, "kind"?: "info"|"success"|"warning"|"key"}}``
``agenda``
    ``{"type": "agenda", "title"?: str, "items": [str], "active"?: int}``
``kpi``
    ``{"type": "kpi", "title": str,
       "kpis": [{"value": str, "label": str, "delta"?: str|null, "color"?: str}]}``
``table``
    ``{"type": "table", "title": str, "columns": [str | {"label": str,
       "width"?: number, "align"?: "l"|"ctr"|"r"}], "rows": [[cell]]}``
``waterfall``
    ``{"type": "waterfall", "title": str, "total_label"?: str,
       "items": [{"label": str, "value": number}]}``
``bars``
    ``{"type": "bars", "title": str, "categories": [str],
       "values": [number], "horizontal"?: bool}``
``timeline``
    ``{"type": "timeline", "title": str,
       "phases": [{"label": str, "sub"?: str|null, "active"?: bool}]}``
``comparison``
    ``{"type": "comparison", "title": str, "options": [str],
       "criteria": [str], "cells": [[str | number]]}``  (number → Harvey ball)
``blank``
    ``{"type": "blank", "layout"?: str|int}``
"""

from __future__ import annotations

import re
from typing import Any, Callable, Union

from .api import Deck
from .emu import Box, cm
from .errors import ParseError, SpecError
from .model import LayoutSpec
from .slide import SlideBuilder
from .text import RunFormat

__all__ = ["build_from_spec", "validate_spec", "SLIDE_TYPES"]

#: All slide types understood by the spec engine.
SLIDE_TYPES = (
    "title",
    "section",
    "bullets",
    "agenda",
    "kpi",
    "table",
    "waterfall",
    "bars",
    "timeline",
    "comparison",
    "blank",
)

#: Required keys per slide type (besides ``type`` itself).
_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "title": ("title",),
    "section": ("title",),
    "bullets": ("title", "bullets"),
    "agenda": ("items",),
    "kpi": ("title", "kpis"),
    "table": ("title", "columns", "rows"),
    "waterfall": ("title", "items"),
    "bars": ("title", "categories", "values"),
    "timeline": ("title", "phases"),
    "comparison": ("title", "options", "criteria", "cells"),
    "blank": (),
}

_CALLOUT_KINDS = ("info", "success", "warning", "key")
_DEFAULT_ACCENT = "206EFB"
_HEX_RE = re.compile(r"#?[0-9A-Fa-f]{6}\Z")
_SCHEME_NAMES = (
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
    "bg1",
    "tx1",
    "bg2",
    "tx2",
)

#: Keys forwarded from spec bullet objects into TextFrame bullet items.
_BULLET_KEYS = ("text", "level", "size_pt", "bold", "italic", "underline", "color", "font")

#: Default content geometry (see ARCHITECTURE.md section 3.12).
_MARGIN = cm(1.2)
_CONTENT_TOP = cm(3.2)


# --- type predicates ---------------------------------------------------------------


def _is_str(value: Any) -> bool:
    """True for ``str`` values."""
    return isinstance(value, str)


def _is_int(value: Any) -> bool:
    """True for ``int`` values, excluding ``bool``."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    """True for ``int``/``float`` values, excluding ``bool``."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_color(value: Any) -> bool:
    """True for theme/logical color names or hex literals accepted by builders."""
    return _is_str(value) and (value in _SCHEME_NAMES or _HEX_RE.match(value) is not None)


def _is_cell(value: Any) -> bool:
    """True for values allowed in table cells: str, number, or null."""
    return value is None or _is_str(value) or _is_number(value)


# --- validation --------------------------------------------------------------------


def validate_spec(spec: dict) -> list[str]:
    """Validate a deck spec and return a list of human-readable problems.

    Each problem names its location (``"slides[3]: ..."``); an empty list
    means the spec is valid. Unknown keys are ignored (forward compatible);
    only unknown *types*, missing required keys, and wrong value types are
    reported.
    """
    if not isinstance(spec, dict):
        return ["spec: muss ein JSON-Objekt sein"]
    problems: list[str] = []
    for key in ("template", "title", "author"):
        if key in spec and not _is_str(spec[key]):
            problems.append(f"{key}: muss eine Zeichenkette sein")
    if "accent" in spec and not (
        _is_str(spec["accent"]) and _HEX_RE.match(spec["accent"])
    ):
        problems.append("accent: muss ein Hex-Farbwert 'RRGGBB' sein")
    slides = spec.get("slides")
    if slides is None:
        problems.append("slides: Pflichtschlüssel fehlt")
    elif not isinstance(slides, list):
        problems.append("slides: muss eine Liste sein")
    else:
        for i, slide_spec in enumerate(slides):
            problems.extend(_validate_slide(i, slide_spec))
    return problems


def _validate_slide(i: int, sd: Any) -> list[str]:
    """Validate one slide object; every problem is prefixed ``slides[i]:``."""
    where = f"slides[{i}]"
    if not isinstance(sd, dict):
        return [f"{where}: muss ein JSON-Objekt sein"]
    stype = sd.get("type")
    if stype is None:
        return [f"{where}: Pflichtschlüssel 'type' fehlt"]
    if not _is_str(stype) or stype not in SLIDE_TYPES:
        return [
            f"{where}: unbekannter Folientyp {stype!r}; "
            f"erlaubt: {', '.join(SLIDE_TYPES)}"
        ]
    problems: list[str] = []
    for key in _REQUIRED_KEYS[stype]:
        if key not in sd:
            problems.append(
                f"{where}: Pflichtschlüssel '{key}' für Typ '{stype}' fehlt"
            )
    if "layout" in sd and not (_is_str(sd["layout"]) or _is_int(sd["layout"])):
        problems.append(f"{where}: 'layout' muss Zeichenkette oder ganze Zahl sein")
    for key in ("title", "subtitle"):
        if key in sd and not _is_str(sd[key]):
            problems.append(f"{where}: '{key}' muss eine Zeichenkette sein")
    _TYPE_CHECKERS[stype](where, sd, problems)
    return problems


def _check_title(where: str, sd: dict, problems: list[str]) -> None:
    """Type ``title``: only the generic title/subtitle checks apply."""


def _check_section(where: str, sd: dict, problems: list[str]) -> None:
    """Type ``section``: optional ``number`` must be a string or integer."""
    if "number" in sd and not (_is_str(sd["number"]) or _is_int(sd["number"])):
        problems.append(f"{where}: 'number' muss Zeichenkette oder ganze Zahl sein")


def _check_bullets(where: str, sd: dict, problems: list[str]) -> None:
    """Type ``bullets``: bullet list entries and the optional callout."""
    if "bullets" in sd:
        bullets = sd["bullets"]
        if not isinstance(bullets, list) or not bullets:
            problems.append(f"{where}: 'bullets' muss eine nicht-leere Liste sein")
        else:
            for j, item in enumerate(bullets):
                if _is_str(item):
                    continue
                if isinstance(item, dict):
                    if not _is_str(item.get("text")):
                        problems.append(
                            f"{where}: bullets[{j}] benötigt ein 'text'-Feld "
                            f"(Zeichenkette)"
                        )
                    if "level" in item and not (
                        _is_int(item["level"]) and 0 <= item["level"] <= 8
                    ):
                        problems.append(
                            f"{where}: bullets[{j}]: 'level' muss eine ganze "
                            f"Zahl von 0 bis 8 sein"
                        )
                else:
                    problems.append(
                        f"{where}: bullets[{j}] muss Zeichenkette oder Objekt "
                        f"mit 'text' sein"
                    )
    if "callout" in sd:
        callout = sd["callout"]
        if not isinstance(callout, dict):
            problems.append(f"{where}: 'callout' muss ein JSON-Objekt sein")
        else:
            if not _is_str(callout.get("text")):
                problems.append(
                    f"{where}: callout benötigt ein 'text'-Feld (Zeichenkette)"
                )
            if "kind" in callout and callout["kind"] not in _CALLOUT_KINDS:
                problems.append(
                    f"{where}: callout 'kind' muss eines von "
                    f"{', '.join(_CALLOUT_KINDS)} sein"
                )


def _check_agenda(where: str, sd: dict, problems: list[str]) -> None:
    """Type ``agenda``: items are strings; ``active`` indexes into items."""
    items = sd.get("items")
    if "items" in sd:
        if not isinstance(items, list) or not items:
            problems.append(f"{where}: 'items' muss eine nicht-leere Liste sein")
        else:
            for j, item in enumerate(items):
                if not _is_str(item):
                    problems.append(f"{where}: items[{j}] muss eine Zeichenkette sein")
    if "active" in sd and sd["active"] is not None:
        active = sd["active"]
        if not _is_int(active):
            problems.append(f"{where}: 'active' muss eine ganze Zahl sein")
        elif isinstance(items, list) and items and not 0 <= active < len(items):
            problems.append(
                f"{where}: 'active' muss zwischen 0 und {len(items) - 1} liegen"
            )


def _check_kpi(where: str, sd: dict, problems: list[str]) -> None:
    """Type ``kpi``: each tile needs string ``value`` and ``label``."""
    if "kpis" not in sd:
        return
    kpis = sd["kpis"]
    if not isinstance(kpis, list) or not kpis:
        problems.append(f"{where}: 'kpis' muss eine nicht-leere Liste sein")
        return
    for j, kpi in enumerate(kpis):
        if not isinstance(kpi, dict):
            problems.append(f"{where}: kpis[{j}] muss ein JSON-Objekt sein")
            continue
        for key in ("value", "label"):
            if not _is_str(kpi.get(key)):
                problems.append(
                    f"{where}: kpis[{j}] benötigt ein '{key}'-Feld (Zeichenkette)"
                )
        if "delta" in kpi and kpi["delta"] is not None and not _is_str(kpi["delta"]):
            problems.append(
                f"{where}: kpis[{j}]: 'delta' muss Zeichenkette oder null sein"
            )
        if "color" in kpi and not _is_color(kpi["color"]):
            problems.append(
                f"{where}: kpis[{j}]: 'color' muss Theme-Farbe oder Hex-Farbwert sein"
            )


def _check_table(where: str, sd: dict, problems: list[str]) -> None:
    """Type ``table``: column definitions and rectangular row data."""
    n_columns: Union[int, None] = None
    if "columns" in sd:
        columns = sd["columns"]
        if not isinstance(columns, list) or not columns:
            problems.append(f"{where}: 'columns' muss eine nicht-leere Liste sein")
        else:
            n_columns = len(columns)
            for j, col in enumerate(columns):
                if _is_str(col):
                    continue
                if isinstance(col, dict):
                    if not _is_str(col.get("label")):
                        problems.append(
                            f"{where}: columns[{j}] benötigt ein 'label'-Feld "
                            f"(Zeichenkette)"
                        )
                    if "width" in col and not _is_number(col["width"]):
                        problems.append(
                            f"{where}: columns[{j}]: 'width' muss eine Zahl sein"
                        )
                    if "align" in col and col["align"] not in ("l", "ctr", "r"):
                        problems.append(
                            f"{where}: columns[{j}]: 'align' muss 'l', 'ctr' "
                            f"oder 'r' sein"
                        )
                else:
                    problems.append(
                        f"{where}: columns[{j}] muss Zeichenkette oder Objekt sein"
                    )
    if "rows" in sd:
        rows = sd["rows"]
        if not isinstance(rows, list):
            problems.append(f"{where}: 'rows' muss eine Liste sein")
            return
        for j, row in enumerate(rows):
            if not isinstance(row, list):
                problems.append(f"{where}: rows[{j}] muss eine Liste sein")
                continue
            if n_columns is not None and len(row) != n_columns:
                problems.append(
                    f"{where}: rows[{j}] hat {len(row)} Zellen, "
                    f"erwartet {n_columns}"
                )
            for k, cell in enumerate(row):
                if not _is_cell(cell):
                    problems.append(
                        f"{where}: rows[{j}][{k}] muss Zeichenkette, Zahl "
                        f"oder null sein"
                    )


def _check_waterfall(where: str, sd: dict, problems: list[str]) -> None:
    """Type ``waterfall``: items need a label and a numeric value."""
    if "total_label" in sd and not _is_str(sd["total_label"]):
        problems.append(f"{where}: 'total_label' muss eine Zeichenkette sein")
    if "items" not in sd:
        return
    items = sd["items"]
    if not isinstance(items, list) or not items:
        problems.append(f"{where}: 'items' muss eine nicht-leere Liste sein")
        return
    for j, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"{where}: items[{j}] muss ein JSON-Objekt sein")
            continue
        if not _is_str(item.get("label")):
            problems.append(
                f"{where}: items[{j}] benötigt ein 'label'-Feld (Zeichenkette)"
            )
        if not _is_number(item.get("value")):
            problems.append(f"{where}: items[{j}] benötigt ein 'value'-Feld (Zahl)")


def _check_bars(where: str, sd: dict, problems: list[str]) -> None:
    """Type ``bars``: parallel category/value lists, optional orientation."""
    categories = sd.get("categories")
    values = sd.get("values")
    categories_ok = False
    if "categories" in sd:
        if not isinstance(categories, list) or not categories:
            problems.append(f"{where}: 'categories' muss eine nicht-leere Liste sein")
        else:
            categories_ok = True
            for j, cat in enumerate(categories):
                if not _is_str(cat):
                    problems.append(
                        f"{where}: categories[{j}] muss eine Zeichenkette sein"
                    )
    values_ok = False
    if "values" in sd:
        if not isinstance(values, list) or not values:
            problems.append(f"{where}: 'values' muss eine nicht-leere Liste sein")
        else:
            values_ok = True
            has_positive = False
            for j, value in enumerate(values):
                if not _is_number(value):
                    problems.append(f"{where}: values[{j}] muss eine Zahl sein")
                elif value < 0:
                    problems.append(
                        f"{where}: values[{j}] darf nicht negativ sein; "
                        f"für Brückenlogik 'waterfall' nutzen"
                    )
                elif value > 0:
                    has_positive = True
            if not has_positive:
                problems.append(f"{where}: 'values' braucht mindestens einen Wert > 0")
    if categories_ok and values_ok and len(categories) != len(values):
        problems.append(
            f"{where}: 'categories' ({len(categories)}) und 'values' "
            f"({len(values)}) müssen gleich lang sein"
        )
    if "horizontal" in sd and not isinstance(sd["horizontal"], bool):
        problems.append(f"{where}: 'horizontal' muss true oder false sein")


def _check_timeline(where: str, sd: dict, problems: list[str]) -> None:
    """Type ``timeline``: phases need a label; sub/active are typed."""
    if "phases" not in sd:
        return
    phases = sd["phases"]
    if not isinstance(phases, list) or not phases:
        problems.append(f"{where}: 'phases' muss eine nicht-leere Liste sein")
        return
    for j, phase in enumerate(phases):
        if not isinstance(phase, dict):
            problems.append(f"{where}: phases[{j}] muss ein JSON-Objekt sein")
            continue
        if not _is_str(phase.get("label")):
            problems.append(
                f"{where}: phases[{j}] benötigt ein 'label'-Feld (Zeichenkette)"
            )
        if "sub" in phase and phase["sub"] is not None and not _is_str(phase["sub"]):
            problems.append(
                f"{where}: phases[{j}]: 'sub' muss Zeichenkette oder null sein"
            )
        if "active" in phase and not isinstance(phase["active"], bool):
            problems.append(
                f"{where}: phases[{j}]: 'active' muss true oder false sein"
            )


def _check_comparison(where: str, sd: dict, problems: list[str]) -> None:
    """Type ``comparison``: string headers, cells of text or Harvey numbers."""
    n_options: Union[int, None] = None
    n_criteria: Union[int, None] = None
    for key in ("options", "criteria"):
        if key not in sd:
            continue
        entries = sd[key]
        if not isinstance(entries, list) or not entries:
            problems.append(f"{where}: '{key}' muss eine nicht-leere Liste sein")
            continue
        if key == "options":
            n_options = len(entries)
        else:
            n_criteria = len(entries)
        for j, entry in enumerate(entries):
            if not _is_str(entry):
                problems.append(f"{where}: {key}[{j}] muss eine Zeichenkette sein")
    if "cells" not in sd:
        return
    cells = sd["cells"]
    if not isinstance(cells, list) or not cells:
        problems.append(f"{where}: 'cells' muss eine nicht-leere Liste sein")
        return
    if n_criteria is not None and len(cells) != n_criteria:
        problems.append(
            f"{where}: 'cells' braucht {n_criteria} Zeilen, hat aber {len(cells)}"
        )
    for j, row in enumerate(cells):
        if not isinstance(row, list):
            problems.append(f"{where}: cells[{j}] muss eine Liste sein")
            continue
        if n_options is not None and len(row) != n_options:
            problems.append(
                f"{where}: cells[{j}] braucht {n_options} Zellen, hat aber {len(row)}"
            )
        for k, cell in enumerate(row):
            if not (_is_str(cell) or _is_number(cell)):
                problems.append(
                    f"{where}: cells[{j}][{k}] muss Zeichenkette oder Zahl sein"
                )
            elif _is_number(cell) and not 0 <= cell <= 1:
                problems.append(
                    f"{where}: cells[{j}][{k}] als Harvey-Wert muss zwischen 0 und 1 liegen"
                )


def _check_blank(where: str, sd: dict, problems: list[str]) -> None:
    """Type ``blank``: nothing beyond the generic checks."""


_TYPE_CHECKERS: dict[str, Callable[[str, dict, list], None]] = {
    "title": _check_title,
    "section": _check_section,
    "bullets": _check_bullets,
    "agenda": _check_agenda,
    "kpi": _check_kpi,
    "table": _check_table,
    "waterfall": _check_waterfall,
    "bars": _check_bars,
    "timeline": _check_timeline,
    "comparison": _check_comparison,
    "blank": _check_blank,
}


# --- building ----------------------------------------------------------------------


def build_from_spec(spec: dict, template_path: Union[str, None] = None) -> Deck:
    """Build a :class:`~deckforge.api.Deck` from a deck spec.

    The spec is validated first; any problems raise
    :class:`~deckforge.errors.SpecError` listing every issue with its slide
    index. ``template_path`` overrides ``spec["template"]``; when neither is
    given, the bootstrap default template is created with
    ``spec.get("accent", "206EFB")`` as accent color. The returned deck has
    all slides queued — call :meth:`Deck.save` to write the file.
    """
    problems = validate_spec(spec)
    if problems:
        raise SpecError(
            "Ungültige Spezifikation:\n  - " + "\n  - ".join(problems)
        )
    path = template_path or spec.get("template")
    if path:
        deck = Deck.open(path)
    else:
        deck = Deck.create(accent=spec.get("accent", _DEFAULT_ACCENT))
    deck.title = spec.get("title")
    deck.author = spec.get("author")
    for slide_spec in spec["slides"]:
        _SLIDE_BUILDERS[slide_spec["type"]](deck, slide_spec)
    return deck


# --- geometry & layout helpers -----------------------------------------------------


def _content_box(slide: SlideBuilder) -> Box:
    """Default content area below the title (margins per ARCHITECTURE 3.12)."""
    return Box(
        _MARGIN,
        _CONTENT_TOP,
        slide.width - 2 * _MARGIN,
        slide.height - _CONTENT_TOP - _MARGIN,
    )


def _callout_box(slide: SlideBuilder) -> Box:
    """Full-width callout strip at the bottom of the slide."""
    height = cm(1.8)
    return Box(
        _MARGIN,
        slide.height - _MARGIN - height,
        slide.width - 2 * _MARGIN,
        height,
    )


def _layout_for(deck: Deck, sd: dict, *candidates: str) -> LayoutSpec:
    """Pick the layout for a slide spec.

    An explicit ``"layout"`` key wins (and raises
    :class:`~deckforge.errors.ParseError` when it does not match). Otherwise
    the ``candidates`` queries are tried in order, then ``"obj"``, then the
    first layout of the template.
    """
    if "layout" in sd:
        return deck.layout(sd["layout"])
    for candidate in (*candidates, "obj"):
        try:
            return deck.layout(candidate)
        except ParseError:
            continue
    layouts = deck.layouts
    if layouts:
        return layouts[0]
    raise ParseError("Template has no slide layouts")


def _has_ph_type(layout: LayoutSpec, *types: str) -> bool:
    """True when the layout declares a placeholder of any given type."""
    return any(ph.ph_type in types for ph in layout.placeholders)


def _set_title(slide: SlideBuilder, layout: LayoutSpec, text: str) -> None:
    """Set the slide title via the layout placeholder, or a textbox fallback."""
    if _has_ph_type(layout, "title", "ctrTitle"):
        slide.title(text)
    else:
        box = Box(_MARGIN, cm(0.8), slide.width - 2 * _MARGIN, cm(1.8))
        slide.add_textbox(box).text(text, fmt=RunFormat(size_pt=24.0, bold=True))


def _new_slide(deck: Deck, sd: dict, *candidates: str) -> tuple[SlideBuilder, LayoutSpec]:
    """Queue a new slide for ``sd`` and return ``(builder, layout)``."""
    layout = _layout_for(deck, sd, *candidates)
    return deck.add_slide(layout), layout


def _cell_text(cell: Any) -> str:
    """Coerce a table cell value to display text (floats keep ``str`` form)."""
    if cell is None:
        return ""
    if isinstance(cell, float) and cell.is_integer():
        return str(int(cell))
    return str(cell)


# --- slide type handlers -----------------------------------------------------------


def _build_title(deck: Deck, sd: dict) -> None:
    """``title``: title layout with title and optional subtitle."""
    slide, layout = _new_slide(deck, sd, "title")
    _set_title(slide, layout, sd["title"])
    subtitle = sd.get("subtitle")
    if subtitle:
        if _has_ph_type(layout, "subTitle"):
            slide.placeholder("subtitle").text(subtitle)
        else:
            box = Box(
                _MARGIN,
                int(slide.height * 0.55),
                slide.width - 2 * _MARGIN,
                cm(2.0),
            )
            slide.add_textbox(box).text(
                subtitle, fmt=RunFormat(size_pt=18.0, color="tx2")
            )


def _build_section(deck: Deck, sd: dict) -> None:
    """``section``: section-header layout, optional big section number."""
    slide, layout = _new_slide(deck, sd, "secHead")
    _set_title(slide, layout, sd["title"])
    number = sd.get("number")
    if number is not None:
        box = Box(_MARGIN, cm(0.8), cm(8.0), cm(3.4))
        slide.add_textbox(box).text(
            str(number), fmt=RunFormat(size_pt=80.0, bold=True, color="accent1")
        )


def _bullet_items(raw: list) -> list:
    """Normalize spec bullet entries; unknown dict keys are dropped."""
    items: list = []
    for item in raw:
        if isinstance(item, dict):
            items.append({k: item[k] for k in _BULLET_KEYS if k in item})
        else:
            items.append(item)
    return items


def _build_bullets(deck: Deck, sd: dict) -> None:
    """``bullets``: body bullet list plus an optional bottom callout."""
    slide, layout = _new_slide(deck, sd, "obj")
    _set_title(slide, layout, sd["title"])
    items = _bullet_items(sd["bullets"])
    if _has_ph_type(layout, "body"):
        slide.placeholder("body").bullets(items)
    else:
        slide.add_textbox(_content_box(slide)).bullets(items)
    callout = sd.get("callout")
    if callout:
        from . import components  # deferred: sibling module

        components.add_callout(
            slide,
            callout["text"],
            kind=callout.get("kind", "info"),
            box=_callout_box(slide),
        )


def _build_agenda(deck: Deck, sd: dict) -> None:
    """``agenda``: numbered agenda with an optional active item."""
    from . import components  # deferred: sibling module

    slide, layout = _new_slide(deck, sd, "titleOnly")
    _set_title(slide, layout, sd.get("title", "Agenda"))
    components.add_agenda(
        slide, [str(item) for item in sd["items"]], active=sd.get("active")
    )


def _build_kpi(deck: Deck, sd: dict) -> None:
    """``kpi``: row of KPI tiles."""
    from . import components  # deferred: sibling module

    slide, layout = _new_slide(deck, sd, "titleOnly")
    _set_title(slide, layout, sd["title"])
    kpis = [
        {key: kpi[key] for key in ("value", "label", "delta", "color") if key in kpi}
        for kpi in sd["kpis"]
    ]
    components.add_kpi_row(slide, kpis)


def _build_table(deck: Deck, sd: dict) -> None:
    """``table``: formatted data table in the content area."""
    slide, layout = _new_slide(deck, sd, "titleOnly")
    _set_title(slide, layout, sd["title"])
    columns: list = []
    for col in sd["columns"]:
        if isinstance(col, dict):
            columns.append(
                {k: col[k] for k in ("label", "width", "align") if k in col}
            )
        else:
            columns.append(col)
    rows = [[_cell_text(cell) for cell in row] for row in sd["rows"]]
    slide.add_table(_content_box(slide), columns, rows)


def _build_waterfall(deck: Deck, sd: dict) -> None:
    """``waterfall``: bridge chart with a trailing total bar."""
    from . import components  # deferred: sibling module

    slide, layout = _new_slide(deck, sd, "titleOnly")
    _set_title(slide, layout, sd["title"])
    items = [
        {"label": str(item["label"]), "value": float(item["value"])}
        for item in sd["items"]
    ]
    components.add_waterfall(
        slide,
        _content_box(slide),
        items,
        total_label=str(sd.get("total_label", "Summe")),
    )


def _build_bars(deck: Deck, sd: dict) -> None:
    """``bars``: shape-based bar chart (horizontal by default)."""
    from . import components  # deferred: sibling module

    slide, layout = _new_slide(deck, sd, "titleOnly")
    _set_title(slide, layout, sd["title"])
    components.add_bar_chart(
        slide,
        _content_box(slide),
        [str(category) for category in sd["categories"]],
        [float(value) for value in sd["values"]],
        horizontal=bool(sd.get("horizontal", True)),
    )


def _build_timeline(deck: Deck, sd: dict) -> None:
    """``timeline``: chevron phase band."""
    from . import components  # deferred: sibling module

    slide, layout = _new_slide(deck, sd, "titleOnly")
    _set_title(slide, layout, sd["title"])
    phases = [
        {
            "label": str(phase["label"]),
            "sub": phase.get("sub"),
            "active": bool(phase.get("active", False)),
        }
        for phase in sd["phases"]
    ]
    components.add_timeline(slide, phases)


def _build_comparison(deck: Deck, sd: dict) -> None:
    """``comparison``: options × criteria matrix (numbers become Harveys)."""
    from . import components  # deferred: sibling module

    slide, layout = _new_slide(deck, sd, "titleOnly")
    _set_title(slide, layout, sd["title"])
    cells = [
        [cell if isinstance(cell, str) else float(cell) for cell in row]
        for row in sd["cells"]
    ]
    components.add_comparison(
        slide,
        [str(option) for option in sd["options"]],
        [str(criterion) for criterion in sd["criteria"]],
        cells,
    )


def _build_blank(deck: Deck, sd: dict) -> None:
    """``blank``: an empty slide on the chosen (or blank) layout."""
    deck.add_slide(_layout_for(deck, sd, "blank"))


_SLIDE_BUILDERS: dict[str, Callable[[Deck, dict], None]] = {
    "title": _build_title,
    "section": _build_section,
    "bullets": _build_bullets,
    "agenda": _build_agenda,
    "kpi": _build_kpi,
    "table": _build_table,
    "waterfall": _build_waterfall,
    "bars": _build_bars,
    "timeline": _build_timeline,
    "comparison": _build_comparison,
    "blank": _build_blank,
}
