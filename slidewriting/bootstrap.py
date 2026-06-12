"""Bootstrap a complete, valid 16:9 presentation template from scratch.

:func:`create_default_template` assembles every part a minimal-but-complete
``.pptx`` needs — content types, package rels, docProps (core + app),
``presentation.xml`` (+ rels), presProps, viewProps, tableStyles, a full
theme (color/font/format scheme), one slide master (color map, placeholders,
text styles), and the six standard layouts from :data:`DEFAULT_LAYOUTS` —
with **no slides**. The resulting :class:`~slidewriting.opc.Package` opens
cleanly in PowerPoint and serves as the default design for decks created
without an external template.

Design: clean consulting look — title top-left with a thin accent rule
underneath, generous content area, small date/footer/slide-number
placeholders along the bottom edge.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .emu import Box, SLIDE_H_16_9, SLIDE_W_16_9, cm, pt
from .errors import BuildError
from .opc import (
    CT_CORE_PROPS,
    CT_EXT_PROPS,
    CT_PRESENTATION,
    CT_PRES_PROPS,
    CT_SLIDE_LAYOUT,
    CT_SLIDE_MASTER,
    CT_TABLE_STYLES,
    CT_THEME,
    CT_VIEW_PROPS,
    Package,
    RT_CORE_PROPS,
    RT_EXTENDED_PROPS,
    RT_OFFICE_DOCUMENT,
    RT_PRES_PROPS,
    RT_SLIDE_LAYOUT,
    RT_SLIDE_MASTER,
    RT_TABLE_STYLES,
    RT_THEME,
    RT_VIEW_PROPS,
)
from .xmlcore import el, serialize, sub

#: The six default layouts as ``(p:cSld@name, p:sldLayout@type)`` pairs,
#: in slideLayout1..slideLayout6 order.
DEFAULT_LAYOUTS: list[tuple[str, str]] = [
    ("Titelfolie", "title"),
    ("Titel und Inhalt", "obj"),
    ("Abschnittsüberschrift", "secHead"),
    ("Zwei Inhalte", "twoObj"),
    ("Nur Titel", "titleOnly"),
    ("Leer", "blank"),
]

#: Master/layout ids in presentation.xml and the master must be >= 2^31.
_MASTER_ID = 2147483648

#: Fixed timestamp for deterministic docProps output.
_FIXED_TIMESTAMP = "2026-01-01T00:00:00Z"

#: Default table style GUID for ``a:tblStyleLst@def``.
_TABLE_STYLES_GUID = "{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"

#: Derived consulting palette for accent2..accent6 plus folHlink.
_ACCENT2 = "12B5A5"
_ACCENT3 = "7C5CFC"
_ACCENT4 = "E8A33D"
_ACCENT5 = "2E9E4F"
_ACCENT6 = "5B6B7C"
_FOLHLINK = "7C5CFC"
_DK2 = "1A2B40"
_LT2 = "F2F4F7"

_HEX_RE = re.compile(r"#?([0-9A-Fa-f]{6})\Z")

# --- Master geometry (all EMU) --------------------------------------------------------

_TITLE_BOX = Box(cm(1.2), cm(0.9), SLIDE_W_16_9 - cm(2.4), cm(1.6))
_RULE_BOX = Box(cm(1.2), cm(2.62), SLIDE_W_16_9 - cm(2.4), pt(2))
_BODY_BOX = Box(cm(1.2), cm(3.2), SLIDE_W_16_9 - cm(2.4), cm(14.2))
_DT_BOX = Box(cm(1.2), cm(17.8), cm(6.0), cm(0.6))
_FTR_BOX = Box((SLIDE_W_16_9 - cm(8.0)) // 2, cm(17.8), cm(8.0), cm(0.6))
_SLDNUM_BOX = Box(SLIDE_W_16_9 - cm(1.2) - cm(3.0), cm(17.8), cm(3.0), cm(0.6))

# --- Layout geometry -------------------------------------------------------------------

_CTR_TITLE_BOX = Box(cm(2.4), cm(6.0), SLIDE_W_16_9 - cm(4.8), cm(3.0))
_SUBTITLE_BOX = Box(cm(2.4), cm(9.6), SLIDE_W_16_9 - cm(4.8), cm(2.4))
_SEC_TITLE_BOX = Box(cm(1.2), cm(7.0), SLIDE_W_16_9 - cm(2.4), cm(3.2))
_SEC_BODY_BOX = Box(cm(1.2), cm(10.6), SLIDE_W_16_9 - cm(2.4), cm(2.0))
_TWO_GAP = cm(0.6)
_TWO_W = (_BODY_BOX.w - _TWO_GAP) // 2
_TWO_LEFT_BOX = Box(_BODY_BOX.x, _BODY_BOX.y, _TWO_W, _BODY_BOX.h)
_TWO_RIGHT_BOX = Box(_BODY_BOX.x + _TWO_W + _TWO_GAP, _BODY_BOX.y, _TWO_W, _BODY_BOX.h)

#: Master body style: (marL, bullet char, size in hundredths pt) for lvl1-5.
_BODY_LEVELS: tuple[tuple[int, str, int], ...] = (
    (0, "•", 1800),
    (342900, "–", 1600),
    (685800, "•", 1400),
    (1028700, "–", 1200),
    (1371600, "•", 1200),
)


def create_default_template(
    accent: str = "206EFB",
    *,
    name: str = "Slide Writing",
    major_font: str = "Calibri Light",
    minor_font: str = "Calibri",
) -> Package:
    """Build the complete default template package (16:9, no slides).

    Args:
        accent: Primary accent color as ``"RRGGBB"`` or ``"#RRGGBB"``;
            becomes theme slot ``accent1`` (and the hyperlink color).
        name: Template/theme name; also written as ``dc:title``.
        major_font: Theme major latin typeface (headings).
        minor_font: Theme minor latin typeface (body text).

    Returns:
        A fully wired :class:`~slidewriting.opc.Package` ready to save or to
        extend with slides.

    Raises:
        BuildError: If ``accent`` is not a six-digit hex color.
    """
    accent_rgb = _normalize_accent(accent)
    pkg = Package.create()

    # docProps ---------------------------------------------------------------------
    pkg.add_part("/docProps/core.xml", CT_CORE_PROPS, _core_xml(name))
    pkg.add_part("/docProps/app.xml", CT_EXT_PROPS, _app_xml(name))

    # ppt main parts ---------------------------------------------------------------
    pres_rels = pkg.rels("/ppt/presentation.xml")
    master_rid = pres_rels.add(RT_SLIDE_MASTER, "slideMasters/slideMaster1.xml")
    pres_rels.add(RT_THEME, "theme/theme1.xml")
    pres_rels.add(RT_PRES_PROPS, "presProps.xml")
    pres_rels.add(RT_VIEW_PROPS, "viewProps.xml")
    pres_rels.add(RT_TABLE_STYLES, "tableStyles.xml")
    pkg.add_part("/ppt/presentation.xml", CT_PRESENTATION, _presentation_xml(master_rid))
    pkg.add_part("/ppt/presProps.xml", CT_PRES_PROPS, serialize(el("p:presentationPr")))
    pkg.add_part("/ppt/viewProps.xml", CT_VIEW_PROPS, serialize(el("p:viewPr")))
    pkg.add_part(
        "/ppt/tableStyles.xml",
        CT_TABLE_STYLES,
        serialize(el("a:tblStyleLst", {"def": _TABLE_STYLES_GUID})),
    )
    pkg.add_part(
        "/ppt/theme/theme1.xml",
        CT_THEME,
        _theme_xml(name, accent_rgb, major_font, minor_font),
    )

    # Slide master + its rels (layouts first so rIds match p:sldLayoutIdLst) -------
    master_rels = pkg.rels("/ppt/slideMasters/slideMaster1.xml")
    layout_rids: list[str] = []
    for index in range(len(DEFAULT_LAYOUTS)):
        layout_rids.append(
            master_rels.add(
                RT_SLIDE_LAYOUT, f"../slideLayouts/slideLayout{index + 1}.xml"
            )
        )
    master_rels.add(RT_THEME, "../theme/theme1.xml")
    pkg.add_part(
        "/ppt/slideMasters/slideMaster1.xml", CT_SLIDE_MASTER, _master_xml(layout_rids)
    )

    # Layouts -----------------------------------------------------------------------
    for index, (layout_name, ltype) in enumerate(DEFAULT_LAYOUTS):
        partname = f"/ppt/slideLayouts/slideLayout{index + 1}.xml"
        pkg.rels(partname).add(RT_SLIDE_MASTER, "../slideMasters/slideMaster1.xml")
        pkg.add_part(partname, CT_SLIDE_LAYOUT, _layout_xml(layout_name, ltype))

    # Package-level rels -------------------------------------------------------------
    pkg_rels = pkg.rels(None)
    pkg_rels.add(RT_OFFICE_DOCUMENT, "ppt/presentation.xml")
    pkg_rels.add(RT_CORE_PROPS, "docProps/core.xml")
    pkg_rels.add(RT_EXTENDED_PROPS, "docProps/app.xml")
    return pkg


# --- helpers: validation ---------------------------------------------------------------


def _normalize_accent(value: str) -> str:
    """Normalize an accent color to uppercase ``RRGGBB``; raise on bad input."""
    match = _HEX_RE.match(value)
    if match is None:
        raise BuildError(
            f"Invalid accent color {value!r}; expected 'RRGGBB' or '#RRGGBB'"
        )
    return match.group(1).upper()


# --- helpers: docProps -----------------------------------------------------------------


def _core_xml(name: str) -> bytes:
    """Build ``docProps/core.xml`` with fixed, deterministic timestamps."""
    root = el("cp:coreProperties")
    sub(root, "dcterms:created", {"xsi:type": "dcterms:W3CDTF"}, text=_FIXED_TIMESTAMP)
    sub(root, "dc:creator", text="Slide Writing")
    sub(root, "cp:lastModifiedBy", text="Slide Writing")
    sub(root, "dcterms:modified", {"xsi:type": "dcterms:W3CDTF"}, text=_FIXED_TIMESTAMP)
    sub(root, "dc:title", text=name)
    return serialize(root)


def _app_xml(name: str) -> bytes:
    """Build a minimal ``docProps/app.xml`` (extended properties)."""
    root = el("ep:Properties")
    sub(root, "ep:Application", text="Slide Writing")
    sub(root, "ep:PresentationFormat", text="Breitbild")
    sub(root, "ep:Slides", text="0")
    pairs = sub(root, "ep:HeadingPairs")
    vector = sub(pairs, "vt:vector", {"size": "2", "baseType": "variant"})
    variant = sub(vector, "vt:variant")
    sub(variant, "vt:lpstr", text="Designs")
    variant = sub(vector, "vt:variant")
    sub(variant, "vt:i4", text="1")
    titles = sub(root, "ep:TitlesOfParts")
    vector = sub(titles, "vt:vector", {"size": "1", "baseType": "lpstr"})
    sub(vector, "vt:lpstr", text=name)
    return serialize(root)


# --- helpers: presentation.xml ---------------------------------------------------------


def _presentation_xml(master_rid: str) -> bytes:
    """Build ``ppt/presentation.xml`` with an empty ``p:sldIdLst``."""
    pres = el("p:presentation")
    master_lst = sub(pres, "p:sldMasterIdLst")
    sub(master_lst, "p:sldMasterId", {"id": str(_MASTER_ID), "r:id": master_rid})
    sub(pres, "p:sldIdLst")
    sub(pres, "p:sldSz", {"cx": str(SLIDE_W_16_9), "cy": str(SLIDE_H_16_9)})
    sub(pres, "p:notesSz", {"cx": "6858000", "cy": "9144000"})
    style = sub(pres, "p:defaultTextStyle")
    def_ppr = sub(style, "a:defPPr")
    sub(def_ppr, "a:defRPr", {"lang": "de-DE"})
    lvl1 = sub(style, "a:lvl1pPr", {"marL": "0", "algn": "l"})
    rpr = sub(lvl1, "a:defRPr", {"sz": "1800", "kern": "1200"})
    fill = sub(rpr, "a:solidFill")
    sub(fill, "a:schemeClr", {"val": "tx1"})
    sub(rpr, "a:latin", {"typeface": "+mn-lt"})
    return serialize(pres)


# --- helpers: theme --------------------------------------------------------------------


def _grad_fill(stops: list[tuple[int, list[tuple[str, int]]]]) -> ET.Element:
    """Build an ``a:gradFill`` over ``phClr`` with the given (pos, mods) stops."""
    grad = el("a:gradFill", {"rotWithShape": "1"})
    gs_lst = sub(grad, "a:gsLst")
    for pos, mods in stops:
        gs = sub(gs_lst, "a:gs", {"pos": str(pos)})
        clr = sub(gs, "a:schemeClr", {"val": "phClr"})
        for mod_tag, mod_val in mods:
            sub(clr, f"a:{mod_tag}", {"val": str(mod_val)})
    sub(grad, "a:lin", {"ang": "5400000", "scaled": "0"})
    return grad


def _ph_solid_fill(mods: list[tuple[str, int]] | None = None) -> ET.Element:
    """Build ``<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>``."""
    fill = el("a:solidFill")
    clr = sub(fill, "a:schemeClr", {"val": "phClr"})
    for mod_tag, mod_val in mods or []:
        sub(clr, f"a:{mod_tag}", {"val": str(mod_val)})
    return fill


def _theme_xml(name: str, accent: str, major_font: str, minor_font: str) -> bytes:
    """Build ``ppt/theme/theme1.xml`` with a complete format scheme."""
    theme = el("a:theme", {"name": name})
    elements = sub(theme, "a:themeElements")

    # Color scheme ------------------------------------------------------------------
    clr_scheme = sub(elements, "a:clrScheme", {"name": name})
    dk1 = sub(clr_scheme, "a:dk1")
    sub(dk1, "a:sysClr", {"val": "windowText", "lastClr": "000000"})
    lt1 = sub(clr_scheme, "a:lt1")
    sub(lt1, "a:sysClr", {"val": "window", "lastClr": "FFFFFF"})
    for slot, rgb in (
        ("dk2", _DK2),
        ("lt2", _LT2),
        ("accent1", accent),
        ("accent2", _ACCENT2),
        ("accent3", _ACCENT3),
        ("accent4", _ACCENT4),
        ("accent5", _ACCENT5),
        ("accent6", _ACCENT6),
        ("hlink", accent),
        ("folHlink", _FOLHLINK),
    ):
        slot_el = sub(clr_scheme, f"a:{slot}")
        sub(slot_el, "a:srgbClr", {"val": rgb})

    # Font scheme -------------------------------------------------------------------
    font_scheme = sub(elements, "a:fontScheme", {"name": name})
    for tag, typeface in (("a:majorFont", major_font), ("a:minorFont", minor_font)):
        font = sub(font_scheme, tag)
        sub(font, "a:latin", {"typeface": typeface})
        sub(font, "a:ea", {"typeface": ""})
        sub(font, "a:cs", {"typeface": ""})

    # Format scheme (mirrors the standard Office structure) --------------------------
    fmt = sub(elements, "a:fmtScheme", {"name": "Office"})
    fill_lst = sub(fmt, "a:fillStyleLst")
    fill_lst.append(_ph_solid_fill())
    fill_lst.append(
        _grad_fill(
            [
                (0, [("lumMod", 110000), ("satMod", 105000), ("tint", 67000)]),
                (50000, [("lumMod", 105000), ("satMod", 103000), ("tint", 73000)]),
                (100000, [("lumMod", 105000), ("satMod", 109000), ("tint", 81000)]),
            ]
        )
    )
    fill_lst.append(
        _grad_fill(
            [
                (0, [("satMod", 103000), ("lumMod", 102000), ("tint", 94000)]),
                (50000, [("satMod", 110000), ("lumMod", 100000), ("shade", 100000)]),
                (100000, [("lumMod", 99000), ("satMod", 120000), ("shade", 78000)]),
            ]
        )
    )
    ln_lst = sub(fmt, "a:lnStyleLst")
    for width in (6350, 12700, 19050):
        ln = sub(
            ln_lst,
            "a:ln",
            {"w": str(width), "cap": "flat", "cmpd": "sng", "algn": "ctr"},
        )
        ln.append(_ph_solid_fill())
        sub(ln, "a:prstDash", {"val": "solid"})
        sub(ln, "a:miter", {"lim": "800000"})
    effect_lst = sub(fmt, "a:effectStyleLst")
    for _ in range(2):
        style = sub(effect_lst, "a:effectStyle")
        sub(style, "a:effectLst")
    style = sub(effect_lst, "a:effectStyle")
    inner = sub(style, "a:effectLst")
    shadow = sub(
        inner,
        "a:outerShdw",
        {
            "blurRad": "57150",
            "dist": "19050",
            "dir": "5400000",
            "algn": "ctr",
            "rotWithShape": "0",
        },
    )
    shadow_clr = sub(shadow, "a:srgbClr", {"val": "000000"})
    sub(shadow_clr, "a:alpha", {"val": "63000"})
    bg_lst = sub(fmt, "a:bgFillStyleLst")
    bg_lst.append(_ph_solid_fill())
    bg_lst.append(_ph_solid_fill([("tint", 95000), ("satMod", 170000)]))
    bg_lst.append(
        _grad_fill(
            [
                (
                    0,
                    [
                        ("tint", 93000),
                        ("satMod", 150000),
                        ("shade", 98000),
                        ("lumMod", 102000),
                    ],
                ),
                (
                    50000,
                    [
                        ("tint", 98000),
                        ("satMod", 130000),
                        ("shade", 90000),
                        ("lumMod", 103000),
                    ],
                ),
                (100000, [("shade", 63000), ("satMod", 120000)]),
            ]
        )
    )
    return serialize(theme)


# --- helpers: shape trees ---------------------------------------------------------------


def _sp_tree(c_sld: ET.Element) -> ET.Element:
    """Append the canonical empty ``p:spTree`` skeleton to ``p:cSld``."""
    tree = sub(c_sld, "p:spTree")
    nv = sub(tree, "p:nvGrpSpPr")
    sub(nv, "p:cNvPr", {"id": "1", "name": ""})
    sub(nv, "p:cNvGrpSpPr")
    sub(nv, "p:nvPr")
    grp = sub(tree, "p:grpSpPr")
    xfrm = sub(grp, "a:xfrm")
    sub(xfrm, "a:off", {"x": "0", "y": "0"})
    sub(xfrm, "a:ext", {"cx": "0", "cy": "0"})
    sub(xfrm, "a:chOff", {"x": "0", "y": "0"})
    sub(xfrm, "a:chExt", {"cx": "0", "cy": "0"})
    return tree


def _lvl1_ppr(
    *,
    mar_l: int | None = None,
    indent: int | None = None,
    algn: str | None = None,
    bu_none: bool = False,
    size: int | None = None,
    color: str | None = None,
) -> ET.Element:
    """Build an ``a:lvl1pPr`` override for a placeholder ``a:lstStyle``."""
    attrs: dict[str, str] = {}
    if mar_l is not None:
        attrs["marL"] = str(mar_l)
    if indent is not None:
        attrs["indent"] = str(indent)
    if algn is not None:
        attrs["algn"] = algn
    ppr = el("a:lvl1pPr", attrs)
    if bu_none:
        sub(ppr, "a:buNone")
    if size is not None or color is not None:
        rpr = sub(ppr, "a:defRPr", {"sz": str(size)} if size is not None else None)
        if color is not None:
            fill = sub(rpr, "a:solidFill")
            sub(fill, "a:schemeClr", {"val": color})
    return ppr


def _ph_sp(
    shape_id: int,
    name: str,
    ph_type: str,
    idx: int | None,
    box: Box | None,
    *,
    anchor: str | None = None,
    lvl1: ET.Element | None = None,
) -> ET.Element:
    """Build a placeholder ``<p:sp>`` for a master or layout shape tree.

    Args:
        shape_id: Numeric id for ``p:cNvPr``.
        name: Shape name for ``p:cNvPr``.
        ph_type: ``p:ph@type`` value.
        idx: ``p:ph@idx`` value, or ``None`` to omit the attribute.
        box: Explicit geometry, or ``None`` to inherit.
        anchor: Optional vertical anchor for ``a:bodyPr``.
        lvl1: Optional ``a:lvl1pPr`` override placed in ``a:lstStyle``.
    """
    sp = el("p:sp")
    nv = sub(sp, "p:nvSpPr")
    sub(nv, "p:cNvPr", {"id": str(shape_id), "name": name})
    cnv = sub(nv, "p:cNvSpPr")
    sub(cnv, "a:spLocks", {"noGrp": "1"})
    nvpr = sub(nv, "p:nvPr")
    ph_attrs = {"type": ph_type}
    if idx is not None:
        ph_attrs["idx"] = str(idx)
    sub(nvpr, "p:ph", ph_attrs)
    sp_pr = sub(sp, "p:spPr")
    if box is not None:
        xfrm = sub(sp_pr, "a:xfrm")
        sub(xfrm, "a:off", {"x": str(box.x), "y": str(box.y)})
        sub(xfrm, "a:ext", {"cx": str(box.w), "cy": str(box.h)})
        geom = sub(sp_pr, "a:prstGeom", {"prst": "rect"})
        sub(geom, "a:avLst")
    tx = sub(sp, "p:txBody")
    sub(tx, "a:bodyPr", {"anchor": anchor} if anchor else None)
    lst = sub(tx, "a:lstStyle")
    if lvl1 is not None:
        lst.append(lvl1)
    para = sub(tx, "a:p")
    sub(para, "a:endParaRPr", {"lang": "de-DE"})
    return sp


def _accent_rule_sp(shape_id: int) -> ET.Element:
    """Build the thin accent1 rule under the master title area."""
    sp = el("p:sp")
    nv = sub(sp, "p:nvSpPr")
    sub(nv, "p:cNvPr", {"id": str(shape_id), "name": "Titellinie"})
    sub(nv, "p:cNvSpPr")
    sub(nv, "p:nvPr")
    sp_pr = sub(sp, "p:spPr")
    xfrm = sub(sp_pr, "a:xfrm")
    sub(xfrm, "a:off", {"x": str(_RULE_BOX.x), "y": str(_RULE_BOX.y)})
    sub(xfrm, "a:ext", {"cx": str(_RULE_BOX.w), "cy": str(_RULE_BOX.h)})
    geom = sub(sp_pr, "a:prstGeom", {"prst": "rect"})
    sub(geom, "a:avLst")
    fill = sub(sp_pr, "a:solidFill")
    sub(fill, "a:schemeClr", {"val": "accent1"})
    ln = sub(sp_pr, "a:ln")
    sub(ln, "a:noFill")
    tx = sub(sp, "p:txBody")
    sub(tx, "a:bodyPr")
    sub(tx, "a:lstStyle")
    para = sub(tx, "a:p")
    sub(para, "a:endParaRPr", {"lang": "de-DE"})
    return sp


# --- helpers: slide master --------------------------------------------------------------


def _footer_lvl1(algn: str) -> ET.Element:
    """Level-1 style for the small dt/ftr/sldNum placeholders."""
    return _lvl1_ppr(mar_l=0, indent=0, algn=algn, bu_none=True, size=1000, color="tx2")


def _master_xml(layout_rids: list[str]) -> bytes:
    """Build ``ppt/slideMasters/slideMaster1.xml``."""
    master = el("p:sldMaster")
    c_sld = sub(master, "p:cSld")
    bg = sub(c_sld, "p:bg")
    bg_pr = sub(bg, "p:bgPr")
    fill = sub(bg_pr, "a:solidFill")
    sub(fill, "a:schemeClr", {"val": "lt1"})
    sub(bg_pr, "a:effectLst")
    tree = _sp_tree(c_sld)
    tree.append(
        _ph_sp(2, "Titel 1", "title", None, _TITLE_BOX, anchor="ctr")
    )
    tree.append(_ph_sp(3, "Inhalt 2", "body", 1, _BODY_BOX, anchor="t"))
    tree.append(
        _ph_sp(4, "Datum 3", "dt", 2, _DT_BOX, anchor="ctr", lvl1=_footer_lvl1("l"))
    )
    tree.append(
        _ph_sp(
            5, "Fußzeile 4", "ftr", 3, _FTR_BOX, anchor="ctr", lvl1=_footer_lvl1("ctr")
        )
    )
    tree.append(
        _ph_sp(
            6,
            "Foliennummer 5",
            "sldNum",
            4,
            _SLDNUM_BOX,
            anchor="ctr",
            lvl1=_footer_lvl1("r"),
        )
    )
    tree.append(_accent_rule_sp(7))
    sub(
        master,
        "p:clrMap",
        {
            "bg1": "lt1",
            "tx1": "dk1",
            "bg2": "lt2",
            "tx2": "dk2",
            "accent1": "accent1",
            "accent2": "accent2",
            "accent3": "accent3",
            "accent4": "accent4",
            "accent5": "accent5",
            "accent6": "accent6",
            "hlink": "hlink",
            "folHlink": "folHlink",
        },
    )
    layout_lst = sub(master, "p:sldLayoutIdLst")
    for index, rid in enumerate(layout_rids):
        sub(
            layout_lst,
            "p:sldLayoutId",
            {"id": str(_MASTER_ID + 1 + index), "r:id": rid},
        )
    master.append(_tx_styles())
    return serialize(master)


def _tx_styles() -> ET.Element:
    """Build the master ``p:txStyles`` (title/body/other hierarchies)."""
    styles = el("p:txStyles")
    title = sub(styles, "p:titleStyle")
    lvl = sub(title, "a:lvl1pPr", {"algn": "l"})
    spc = sub(lvl, "a:spcBef")
    sub(spc, "a:spcPct", {"val": "0"})
    sub(lvl, "a:buNone")
    rpr = sub(lvl, "a:defRPr", {"sz": "3600", "b": "0", "kern": "1200"})
    fill = sub(rpr, "a:solidFill")
    sub(fill, "a:schemeClr", {"val": "dk2"})
    sub(rpr, "a:latin", {"typeface": "+mj-lt"})
    body = sub(styles, "p:bodyStyle")
    for level, (mar_l, bullet, size) in enumerate(_BODY_LEVELS, start=1):
        lvl = sub(
            body,
            f"a:lvl{level}pPr",
            {"marL": str(mar_l), "indent": "-228600", "algn": "l"},
        )
        spc = sub(lvl, "a:spcBef")
        sub(spc, "a:spcPts", {"val": "600"})
        sub(lvl, "a:buFont", {"typeface": "Arial"})
        sub(lvl, "a:buChar", {"char": bullet})
        rpr = sub(lvl, "a:defRPr", {"sz": str(size), "kern": "1200"})
        fill = sub(rpr, "a:solidFill")
        sub(fill, "a:schemeClr", {"val": "tx1"})
        sub(rpr, "a:latin", {"typeface": "+mn-lt"})
    other = sub(styles, "p:otherStyle")
    def_ppr = sub(other, "a:defPPr")
    sub(def_ppr, "a:defRPr", {"lang": "de-DE"})
    lvl = sub(other, "a:lvl1pPr")
    sub(lvl, "a:defRPr", {"sz": "1800"})
    return styles


# --- helpers: layouts --------------------------------------------------------------------


def _layout_xml(layout_name: str, ltype: str) -> bytes:
    """Build one ``ppt/slideLayouts/slideLayoutN.xml`` part."""
    layout = el("p:sldLayout", {"type": ltype})
    c_sld = sub(layout, "p:cSld", {"name": layout_name})
    tree = _sp_tree(c_sld)
    for sp in _layout_placeholders(ltype):
        tree.append(sp)
    ovr = sub(layout, "p:clrMapOvr")
    sub(ovr, "a:masterClrMapping")
    return serialize(layout)


def _layout_placeholders(ltype: str) -> list[ET.Element]:
    """Placeholder shapes for one layout type, with explicit boxes."""
    if ltype == "title":
        return [
            _ph_sp(
                2,
                "Titel 1",
                "ctrTitle",
                None,
                _CTR_TITLE_BOX,
                anchor="ctr",
                lvl1=_lvl1_ppr(algn="ctr", size=4000),
            ),
            _ph_sp(
                3,
                "Untertitel 2",
                "subTitle",
                1,
                _SUBTITLE_BOX,
                anchor="t",
                lvl1=_lvl1_ppr(
                    mar_l=0, indent=0, algn="ctr", bu_none=True, size=1800, color="tx2"
                ),
            ),
        ]
    if ltype == "obj":
        return [
            _ph_sp(2, "Titel 1", "title", None, _TITLE_BOX, anchor="ctr"),
            _ph_sp(3, "Inhaltsplatzhalter 2", "body", 1, _BODY_BOX, anchor="t"),
        ]
    if ltype == "secHead":
        return [
            _ph_sp(
                2,
                "Titel 1",
                "title",
                None,
                _SEC_TITLE_BOX,
                anchor="ctr",
                lvl1=_lvl1_ppr(algn="l", size=4000),
            ),
            _ph_sp(
                3,
                "Text 2",
                "body",
                1,
                _SEC_BODY_BOX,
                anchor="t",
                lvl1=_lvl1_ppr(
                    mar_l=0, indent=0, algn="l", bu_none=True, size=1400, color="tx2"
                ),
            ),
        ]
    if ltype == "twoObj":
        return [
            _ph_sp(2, "Titel 1", "title", None, _TITLE_BOX, anchor="ctr"),
            _ph_sp(3, "Inhaltsplatzhalter 2", "body", 1, _TWO_LEFT_BOX, anchor="t"),
            _ph_sp(4, "Inhaltsplatzhalter 3", "body", 2, _TWO_RIGHT_BOX, anchor="t"),
        ]
    if ltype == "titleOnly":
        return [_ph_sp(2, "Titel 1", "title", None, _TITLE_BOX, anchor="ctr")]
    if ltype == "blank":
        return []
    raise BuildError(f"Unknown default layout type {ltype!r}")
