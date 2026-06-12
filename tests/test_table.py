"""Unit tests for slidewriting.table (graphicFrame table builder).

slidewriting.table imports slidewriting.text and slidewriting.theme, which are owned
by other implementers and may not exist yet. To keep these tests runnable in
isolation, minimal contract-compliant stand-ins (per ARCHITECTURE.md sections
3.5 and 3.8) are registered in ``sys.modules`` *only* when the real modules
are not importable; once the real modules exist they are used unchanged.
"""

from __future__ import annotations

import importlib
import re
import sys
import types
import unittest

from dataclasses import dataclass

import xml.etree.ElementTree as ET

from slidewriting.emu import Box, pt
from slidewriting.errors import BuildError
from slidewriting.xmlcore import el, find, findall, qn, sub

_HEX_RE = re.compile(r"#?[0-9A-Fa-f]{6}")


def _stub_color_el(color: str) -> ET.Element:
    """Contract behavior of theme.color_el (section 3.5)."""
    if _HEX_RE.fullmatch(color):
        return el("a:srgbClr", {"val": color.lstrip("#").upper()})
    return el("a:schemeClr", {"val": color})


def _stub_fill_for(color: str, alpha_pct: "int | None" = None) -> ET.Element:
    """Contract behavior of theme.fill_for (section 3.5)."""
    fill = el("a:solidFill")
    clr = _stub_color_el(color)
    if alpha_pct is not None:
        sub(clr, "a:alpha", {"val": str(alpha_pct * 1000)})
    fill.append(clr)
    return fill


def _install_sibling_stubs() -> None:
    """Register stand-ins for slidewriting.theme / slidewriting.text if absent."""
    import slidewriting

    try:
        importlib.import_module("slidewriting.theme")
    except ImportError:
        theme = types.ModuleType("slidewriting.theme")
        theme.color_el = _stub_color_el
        theme.fill_for = _stub_fill_for
        sys.modules["slidewriting.theme"] = theme
        slidewriting.theme = theme

    try:
        importlib.import_module("slidewriting.text")
    except ImportError:
        text = types.ModuleType("slidewriting.text")

        @dataclass
        class RunFormat:  # contract: section 3.8
            size_pt: "float | None" = None
            bold: "bool | None" = None
            italic: "bool | None" = None
            underline: "bool | None" = None
            color: "str | None" = None
            font: "str | None" = None

        @dataclass
        class ParaFormat:  # contract: section 3.8
            level: int = 0
            align: "str | None" = None
            space_before_pt: "float | None" = None
            space_after_pt: "float | None" = None
            line_spacing: "float | None" = None
            bullet: "str | None" = None

        def run_el(value, fmt=None, lang="de-DE"):
            r = el("a:r")
            rpr = sub(r, "a:rPr", {"lang": lang, "dirty": "0"})
            if fmt is not None:
                if fmt.size_pt is not None:
                    rpr.set("sz", str(int(round(fmt.size_pt * 100))))
                if fmt.bold is not None:
                    rpr.set("b", "1" if fmt.bold else "0")
                if fmt.color is not None:
                    rpr.append(_stub_fill_for(fmt.color))
            sub(r, "a:t", text=value)
            return r

        def para_el(runs, pf=None, default_fmt=None):
            p = el("a:p")
            if pf is not None:
                attrs = {}
                if pf.level:
                    attrs["lvl"] = str(pf.level)
                if pf.align is not None:
                    attrs["algn"] = pf.align
                if attrs:
                    sub(p, "a:pPr", attrs)
            if isinstance(runs, str):
                runs = [run_el(runs, default_fmt)]
            for r in runs:
                p.append(r)
            return p

        def txbody_el(paragraphs, *, anchor=None, wrap=True,
                      autofit="norm", insets_emu=None):
            body = el("p:txBody")
            attrs = {}
            if anchor is not None:
                attrs["anchor"] = anchor
            if not wrap:
                attrs["wrap"] = "none"
            bodypr = sub(body, "a:bodyPr", attrs)
            if autofit == "norm":
                sub(bodypr, "a:normAutofit")
            sub(body, "a:lstStyle")
            for para in paragraphs:
                body.append(para)
            return body

        text.RunFormat = RunFormat
        text.ParaFormat = ParaFormat
        text.run_el = run_el
        text.para_el = para_el
        text.txbody_el = txbody_el
        sys.modules["slidewriting.text"] = text
        slidewriting.text = text


_install_sibling_stubs()

from slidewriting.table import TableStyle, table_el  # noqa: E402

BOX = Box(914400, 914400, 9144000, 3429000)


def _tbl(frame: ET.Element) -> ET.Element:
    return find(frame, "a:graphic/a:graphicData/a:tbl")


def _grid_widths(frame: ET.Element) -> "list[int]":
    return [int(c.get("w"))
            for c in findall(_tbl(frame), "a:tblGrid/a:gridCol")]


def _rows(frame: ET.Element) -> "list[ET.Element]":
    return findall(_tbl(frame), "a:tr")


def _cells(tr: ET.Element) -> "list[ET.Element]":
    return findall(tr, "a:tc")


def _cell_algn(tc: ET.Element) -> "str | None":
    ppr = find(tc, "a:txBody/a:p/a:pPr")
    return None if ppr is None else ppr.get("algn")


class FrameStructureTests(unittest.TestCase):
    def test_graphic_frame_skeleton(self) -> None:
        frame = table_el(9, BOX, ["A", "B"], [["1", "2"]])
        self.assertEqual(frame.tag, qn("p:graphicFrame"))
        cnv = find(frame, "p:nvGraphicFramePr/p:cNvPr")
        self.assertEqual(cnv.get("id"), "9")
        self.assertEqual(cnv.get("name"), "Table 9")
        self.assertIsNotNone(find(frame, "p:nvGraphicFramePr/p:cNvGraphicFramePr"))
        self.assertIsNotNone(find(frame, "p:nvGraphicFramePr/p:nvPr"))
        off = find(frame, "p:xfrm/a:off")
        ext = find(frame, "p:xfrm/a:ext")
        self.assertEqual((off.get("x"), off.get("y")), ("914400", "914400"))
        self.assertEqual((ext.get("cx"), ext.get("cy")), ("9144000", "3429000"))
        gd = find(frame, "a:graphic/a:graphicData")
        self.assertEqual(
            gd.get("uri"),
            "http://schemas.openxmlformats.org/drawingml/2006/table",
        )
        tbl_pr = find(_tbl(frame), "a:tblPr")
        self.assertEqual(tbl_pr.get("firstRow"), "1")
        self.assertEqual(tbl_pr.get("bandRow"), "1")

    def test_cell_order_and_namespaces(self) -> None:
        frame = table_el(2, BOX, ["A"], [["x"]])
        tc = _cells(_rows(frame)[0])[0]
        children = list(tc)
        self.assertEqual(children[0].tag, qn("a:txBody"))
        self.assertEqual(children[1].tag, qn("a:tcPr"))
        self.assertIsNotNone(find(tc, "a:txBody/a:bodyPr"))

    def test_row_heights_and_count(self) -> None:
        frame = table_el(2, BOX, ["A"], [["1"], ["2"], ["3"]])
        rows = _rows(frame)
        self.assertEqual(len(rows), 4)  # header + 3 body rows
        for tr in rows:
            self.assertEqual(tr.get("h"), str(pt(22.0)))

    def test_empty_rows_yield_header_only(self) -> None:
        frame = table_el(2, BOX, ["A", "B"], [])
        self.assertEqual(len(_rows(frame)), 1)
        self.assertEqual(len(_cells(_rows(frame)[0])), 2)


class WidthDistributionTests(unittest.TestCase):
    def test_equal_widths_sum_exactly(self) -> None:
        box = Box(0, 0, 1000003, 100)
        frame = table_el(2, box, ["A", "B", "C"], [])
        widths = _grid_widths(frame)
        self.assertEqual(len(widths), 3)
        self.assertEqual(sum(widths), 1000003)

    def test_explicit_col_widths_proportions(self) -> None:
        box = Box(0, 0, 400, 100)
        frame = table_el(2, box, ["A", "B", "C"], [],
                         col_widths=[1.0, 2.0, 1.0])
        self.assertEqual(_grid_widths(frame), [100, 200, 100])

    def test_dict_widths(self) -> None:
        box = Box(0, 0, 400, 100)
        frame = table_el(2, box, [{"label": "A", "width": 3.0},
                                  {"label": "B", "width": 1.0}], [])
        self.assertEqual(_grid_widths(frame), [300, 100])

    def test_col_widths_param_overrides_dict_widths(self) -> None:
        box = Box(0, 0, 400, 100)
        frame = table_el(2, box, [{"label": "A", "width": 9.0},
                                  {"label": "B", "width": 1.0}], [],
                         col_widths=[1.0, 1.0])
        self.assertEqual(_grid_widths(frame), [200, 200])

    def test_mixed_dict_and_plain_columns_default_weight(self) -> None:
        # Columns without a "width" key default to weight 1.0.
        box = Box(0, 0, 400, 100)
        frame = table_el(2, box, [{"label": "A", "width": 2.0}, "B", "C"], [])
        self.assertEqual(_grid_widths(frame), [200, 100, 100])

    def test_last_column_absorbs_rounding(self) -> None:
        box = Box(0, 0, 1000000, 100)
        frame = table_el(2, box, ["A", "B", "C"], [],
                         col_widths=[1.0, 1.0, 1.0])
        widths = _grid_widths(frame)
        self.assertEqual(sum(widths), 1000000)
        self.assertEqual(widths[0], 333333)
        self.assertEqual(widths[1], 333333)
        self.assertEqual(widths[2], 333334)

    def test_invalid_widths_raise(self) -> None:
        with self.assertRaises(BuildError):
            table_el(2, BOX, ["A", "B"], [], col_widths=[1.0])
        with self.assertRaises(BuildError):
            table_el(2, BOX, ["A", "B"], [], col_widths=[1.0, -1.0])

    def test_empty_columns_raise(self) -> None:
        with self.assertRaises(BuildError):
            table_el(2, BOX, [], [])

    def test_ragged_rows_raise(self) -> None:
        with self.assertRaises(BuildError) as ctx:
            table_el(2, BOX, ["A", "B"], [["1", "2"], ["only one"]])
        self.assertIn("Row 1", str(ctx.exception))


class HeaderAndZebraTests(unittest.TestCase):
    def test_header_fill_and_run_format(self) -> None:
        frame = table_el(2, BOX, ["KPI", "Wert"], [["a", "b"]])
        header = _rows(frame)[0]
        for tc in _cells(header):
            scheme = find(tc, "a:tcPr/a:solidFill/a:schemeClr")
            self.assertIsNotNone(scheme)
            self.assertEqual(scheme.get("val"), "accent1")
            rpr = find(tc, "a:txBody/a:p/a:r/a:rPr")
            self.assertEqual(rpr.get("b"), "1")
            self.assertEqual(rpr.get("sz"), "1100")
            run_clr = find(rpr, "a:solidFill/a:srgbClr")
            self.assertEqual(run_clr.get("val"), "FFFFFF")

    def test_custom_header_fill_literal(self) -> None:
        style = TableStyle(header_fill="1A1A2E", header_color="tx1")
        frame = table_el(2, BOX, ["A"], [], style=style)
        tc = _cells(_rows(frame)[0])[0]
        srgb = find(tc, "a:tcPr/a:solidFill/a:srgbClr")
        self.assertEqual(srgb.get("val"), "1A1A2E")

    def test_zebra_banding_on_odd_body_rows(self) -> None:
        style = TableStyle(band_fill="F2F2F2")
        frame = table_el(2, BOX, ["A"], [["r0"], ["r1"], ["r2"], ["r3"]],
                         style=style)
        body = _rows(frame)[1:]
        for i, tr in enumerate(body):
            fill = find(_cells(tr)[0], "a:tcPr/a:solidFill/a:srgbClr")
            if i % 2 == 1:
                self.assertIsNotNone(fill, f"body row {i} should be banded")
                self.assertEqual(fill.get("val"), "F2F2F2")
            else:
                self.assertIsNone(fill, f"body row {i} should not be banded")

    def test_no_banding_without_band_fill(self) -> None:
        frame = table_el(2, BOX, ["A"], [["r0"], ["r1"]])
        for tr in _rows(frame)[1:]:
            self.assertIsNone(find(_cells(tr)[0], "a:tcPr/a:solidFill"))


class BordersAndMarginsTests(unittest.TestCase):
    def test_margins_in_emu(self) -> None:
        frame = table_el(2, BOX, ["A"], [["x"]])
        tc_pr = find(_cells(_rows(frame)[1])[0], "a:tcPr")
        for attr in ("marL", "marR", "marT", "marB"):
            self.assertEqual(tc_pr.get(attr), str(pt(4.0)))

    def test_four_borders_with_color_and_width(self) -> None:
        frame = table_el(2, BOX, ["A"], [["x"]])
        tc_pr = find(_cells(_rows(frame)[1])[0], "a:tcPr")
        for side in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
            ln = find(tc_pr, side)
            self.assertIsNotNone(ln, f"missing border {side}")
            self.assertEqual(ln.get("w"), str(pt(0.75)))
            clr = find(ln, "a:solidFill/a:srgbClr")
            self.assertEqual(clr.get("val"), "D9D9D9")

    def test_border_order_before_fill(self) -> None:
        style = TableStyle(band_fill="F2F2F2")
        frame = table_el(2, BOX, ["A"], [["r0"], ["r1"]], style=style)
        tc_pr = find(_cells(_rows(frame)[2])[0], "a:tcPr")
        tags = [child.tag for child in tc_pr]
        self.assertEqual(
            tags,
            [qn("a:lnL"), qn("a:lnR"), qn("a:lnT"), qn("a:lnB"),
             qn("a:solidFill")],
        )


class NumericAlignmentTests(unittest.TestCase):
    def test_numeric_cells_right_aligned(self) -> None:
        frame = table_el(2, BOX, ["Posten", "Betrag"],
                         [["Umsatz", "1.234,56 €"],
                          ["Anteil", "42 %"],
                          ["Delta", "-17.5"],
                          ["Budget", "$1,000"]])
        for tr in _rows(frame)[1:]:
            label, value = _cells(tr)
            self.assertNotEqual(_cell_algn(label), "r")
            self.assertEqual(_cell_algn(value), "r")

    def test_text_with_digits_not_right_aligned(self) -> None:
        frame = table_el(2, BOX, ["A"], [["+3 pp"], ["Q4 2026"], ["—"]])
        for tr in _rows(frame)[1:]:
            self.assertNotEqual(_cell_algn(_cells(tr)[0]), "r")

    def test_alignment_can_be_disabled(self) -> None:
        style = TableStyle(align_numbers_right=False)
        frame = table_el(2, BOX, ["A"], [["42 %"]], style=style)
        self.assertNotEqual(_cell_algn(_cells(_rows(frame)[1])[0]), "r")

    def test_explicit_column_align_wins(self) -> None:
        frame = table_el(2, BOX,
                         [{"label": "A", "align": "ctr"}], [["42 %"]])
        self.assertEqual(_cell_algn(_cells(_rows(frame)[1])[0]), "ctr")
        self.assertEqual(_cell_algn(_cells(_rows(frame)[0])[0]), "ctr")

    def test_invalid_column_align_raises(self) -> None:
        with self.assertRaises(BuildError):
            table_el(2, BOX, [{"label": "A", "align": "center"}], [])


class CellContentTests(unittest.TestCase):
    def test_cell_text_and_body_format(self) -> None:
        frame = table_el(2, BOX, ["A"], [["Härte & Größe"]])
        tc = _cells(_rows(frame)[1])[0]
        t = find(tc, "a:txBody/a:p/a:r/a:t")
        self.assertEqual(t.text, "Härte & Größe")
        rpr = find(tc, "a:txBody/a:p/a:r/a:rPr")
        self.assertEqual(rpr.get("sz"), "1100")
        clr = find(rpr, "a:solidFill/a:schemeClr")
        self.assertEqual(clr.get("val"), "tx1")

    def test_non_string_cells_are_coerced(self) -> None:
        frame = table_el(2, BOX, ["A", "B"], [[42, 3.5]])
        cells = _cells(_rows(frame)[1])
        self.assertEqual(find(cells[0], "a:txBody/a:p/a:r/a:t").text, "42")
        self.assertEqual(find(cells[1], "a:txBody/a:p/a:r/a:t").text, "3.5")

    def test_column_without_label_raises(self) -> None:
        with self.assertRaises(BuildError):
            table_el(2, BOX, [{"width": 1.0}], [])


if __name__ == "__main__":
    unittest.main()
