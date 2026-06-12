"""Tests for slidewriting.text: runs, paragraphs, text bodies, TextFrame."""

from __future__ import annotations

import unittest

from slidewriting.errors import BuildError
from slidewriting.text import (
    ParaFormat,
    RunFormat,
    TextFrame,
    para_el,
    run_el,
    txbody_el,
)
from slidewriting.xmlcore import find, findall, parse_xml, qn, serialize


class TestRunEl(unittest.TestCase):
    def test_plain_run_has_no_rpr(self):
        run = run_el("Hallo")
        self.assertEqual(run.tag, qn("a:r"))
        self.assertIsNone(find(run, "a:rPr"))
        t = find(run, "a:t")
        self.assertIsNotNone(t)
        self.assertEqual(t.text, "Hallo")

    def test_empty_runformat_omits_rpr(self):
        run = run_el("x", RunFormat())
        self.assertIsNone(find(run, "a:rPr"))

    def test_size_in_hundredths_pt(self):
        run = run_el("x", RunFormat(size_pt=18))
        rpr = find(run, "a:rPr")
        self.assertEqual(rpr.get("sz"), "1800")

    def test_bold_italic_flags(self):
        rpr = find(run_el("x", RunFormat(bold=True, italic=True)), "a:rPr")
        self.assertEqual(rpr.get("b"), "1")
        self.assertEqual(rpr.get("i"), "1")

    def test_explicit_false_flags(self):
        rpr = find(run_el("x", RunFormat(bold=False, italic=False)), "a:rPr")
        self.assertEqual(rpr.get("b"), "0")
        self.assertEqual(rpr.get("i"), "0")

    def test_underline(self):
        rpr = find(run_el("x", RunFormat(underline=True)), "a:rPr")
        self.assertEqual(rpr.get("u"), "sng")
        rpr = find(run_el("x", RunFormat(underline=False)), "a:rPr")
        self.assertEqual(rpr.get("u"), "none")

    def test_lang_attribute(self):
        rpr = find(run_el("x", RunFormat(bold=True)), "a:rPr")
        self.assertEqual(rpr.get("lang"), "de-DE")
        rpr = find(run_el("x", RunFormat(bold=True), lang="en-US"), "a:rPr")
        self.assertEqual(rpr.get("lang"), "en-US")

    def test_scheme_color_fill(self):
        rpr = find(run_el("x", RunFormat(color="accent1")), "a:rPr")
        clr = find(rpr, "a:solidFill/a:schemeClr")
        self.assertIsNotNone(clr)
        self.assertEqual(clr.get("val"), "accent1")

    def test_hex_color_fill(self):
        rpr = find(run_el("x", RunFormat(color="#1f2e3d")), "a:rPr")
        clr = find(rpr, "a:solidFill/a:srgbClr")
        self.assertIsNotNone(clr)
        self.assertEqual(clr.get("val"), "1F2E3D")

    def test_font_latin(self):
        rpr = find(run_el("x", RunFormat(font="+mj-lt")), "a:rPr")
        latin = find(rpr, "a:latin")
        self.assertEqual(latin.get("typeface"), "+mj-lt")

    def test_rpr_child_order_fill_then_latin(self):
        rpr = find(
            run_el("x", RunFormat(color="accent1", font="Calibri")), "a:rPr"
        )
        tags = [child.tag for child in rpr]
        self.assertEqual(tags, [qn("a:solidFill"), qn("a:latin")])

    def test_rpr_precedes_text(self):
        run = run_el("x", RunFormat(bold=True))
        tags = [child.tag for child in run]
        self.assertEqual(tags, [qn("a:rPr"), qn("a:t")])

    def test_special_characters_survive_serialization(self):
        run = run_el('Ärger & <Größe> "Übermaß"')
        blob = serialize(run)
        round_tripped = parse_xml(blob)
        self.assertEqual(
            find(round_tripped, "a:t").text, 'Ärger & <Größe> "Übermaß"'
        )


class TestParaEl(unittest.TestCase):
    def test_no_ppr_for_default_format(self):
        self.assertIsNone(find(para_el([run_el("x")]), "a:pPr"))
        self.assertIsNone(find(para_el([run_el("x")], ParaFormat()), "a:pPr"))

    def test_level_emitted_when_positive(self):
        ppr = find(para_el("x", ParaFormat(level=2)), "a:pPr")
        self.assertEqual(ppr.get("lvl"), "2")

    def test_level_zero_omitted(self):
        ppr = find(para_el("x", ParaFormat(level=0, align="ctr")), "a:pPr")
        self.assertIsNotNone(ppr)
        self.assertIsNone(ppr.get("lvl"))

    def test_level_out_of_range(self):
        with self.assertRaises(BuildError):
            para_el("x", ParaFormat(level=9))
        with self.assertRaises(BuildError):
            para_el("x", ParaFormat(level=-1))

    def test_align(self):
        ppr = find(para_el("x", ParaFormat(align="just")), "a:pPr")
        self.assertEqual(ppr.get("algn"), "just")

    def test_space_before_after_in_hundredths(self):
        ppr = find(
            para_el("x", ParaFormat(space_before_pt=6, space_after_pt=12.5)),
            "a:pPr",
        )
        self.assertEqual(find(ppr, "a:spcBef/a:spcPts").get("val"), "600")
        self.assertEqual(find(ppr, "a:spcAft/a:spcPts").get("val"), "1250")

    def test_line_spacing_percent(self):
        ppr = find(para_el("x", ParaFormat(line_spacing=1.2)), "a:pPr")
        self.assertEqual(find(ppr, "a:lnSpc/a:spcPct").get("val"), "120000")

    def test_bullet_none(self):
        ppr = find(para_el("x", ParaFormat(bullet="none")), "a:pPr")
        self.assertIsNotNone(find(ppr, "a:buNone"))
        self.assertIsNone(find(ppr, "a:buChar"))

    def test_bullet_char(self):
        ppr = find(para_el("x", ParaFormat(bullet="•")), "a:pPr")
        self.assertEqual(find(ppr, "a:buChar").get("char"), "•")

    def test_ppr_child_order(self):
        ppr = find(
            para_el(
                "x",
                ParaFormat(
                    line_spacing=1.0,
                    space_before_pt=4,
                    space_after_pt=4,
                    bullet="-",
                ),
            ),
            "a:pPr",
        )
        tags = [child.tag for child in ppr]
        self.assertEqual(
            tags,
            [qn("a:lnSpc"), qn("a:spcBef"), qn("a:spcAft"), qn("a:buChar")],
        )

    def test_ppr_is_first_child(self):
        para = para_el([run_el("x")], ParaFormat(align="r"))
        self.assertEqual(para[0].tag, qn("a:pPr"))
        self.assertEqual(para[1].tag, qn("a:r"))

    def test_string_input_uses_default_fmt(self):
        para = para_el("Hallo", default_fmt=RunFormat(bold=True))
        run = find(para, "a:r")
        self.assertEqual(find(run, "a:rPr").get("b"), "1")
        self.assertEqual(find(run, "a:t").text, "Hallo")

    def test_string_newlines_become_soft_breaks(self):
        para = para_el("a\nb")
        tags = [child.tag for child in para]
        self.assertEqual(tags, [qn("a:r"), qn("a:br"), qn("a:r")])

    def test_prebuilt_runs_kept_in_order(self):
        para = para_el([run_el("a"), run_el("b")])
        texts = [t.text for t in findall(para, "a:r/a:t")]
        self.assertEqual(texts, ["a", "b"])


class TestTxbodyEl(unittest.TestCase):
    def test_structure_and_order(self):
        body = txbody_el([para_el("x"), para_el("y")])
        self.assertEqual(body.tag, qn("p:txBody"))
        tags = [child.tag for child in body]
        self.assertEqual(
            tags, [qn("a:bodyPr"), qn("a:lstStyle"), qn("a:p"), qn("a:p")]
        )

    def test_empty_paragraph_list_gets_one_empty_p(self):
        body = txbody_el([])
        paras = findall(body, "a:p")
        self.assertEqual(len(paras), 1)
        self.assertEqual(len(paras[0]), 0)

    def test_anchor_and_wrap(self):
        bodypr = find(txbody_el([], anchor="ctr", wrap=False), "a:bodyPr")
        self.assertEqual(bodypr.get("anchor"), "ctr")
        self.assertEqual(bodypr.get("wrap"), "none")

    def test_wrap_true_has_no_attribute(self):
        bodypr = find(txbody_el([]), "a:bodyPr")
        self.assertIsNone(bodypr.get("wrap"))
        self.assertIsNone(bodypr.get("anchor"))

    def test_autofit_norm_default(self):
        bodypr = find(txbody_el([]), "a:bodyPr")
        self.assertIsNotNone(find(bodypr, "a:normAutofit"))

    def test_autofit_none(self):
        bodypr = find(txbody_el([], autofit=None), "a:bodyPr")
        self.assertEqual(len(bodypr), 0)

    def test_autofit_shrink(self):
        bodypr = find(txbody_el([], autofit="shrink"), "a:bodyPr")
        autofit = find(bodypr, "a:normAutofit")
        self.assertIsNotNone(autofit)
        self.assertIsNotNone(autofit.get("fontScale"))

    def test_autofit_spauto(self):
        bodypr = find(txbody_el([], autofit="spAuto"), "a:bodyPr")
        self.assertIsNotNone(find(bodypr, "a:spAutoFit"))

    def test_autofit_invalid(self):
        with self.assertRaises(BuildError):
            txbody_el([], autofit="bogus")

    def test_insets(self):
        bodypr = find(txbody_el([], insets_emu=(1, 2, 3, 4)), "a:bodyPr")
        self.assertEqual(bodypr.get("lIns"), "1")
        self.assertEqual(bodypr.get("tIns"), "2")
        self.assertEqual(bodypr.get("rIns"), "3")
        self.assertEqual(bodypr.get("bIns"), "4")


class TestTextFrame(unittest.TestCase):
    def _frame(self) -> TextFrame:
        return TextFrame(txbody_el([]))

    def test_clear_keeps_bodypr_and_lststyle(self):
        frame = self._frame()
        frame.text("a\nb\nc")
        frame.clear()
        tags = [child.tag for child in frame.element]
        self.assertEqual(tags, [qn("a:bodyPr"), qn("a:lstStyle")])

    def test_text_multiline_becomes_paragraphs(self):
        frame = self._frame().text("a\nb")
        paras = findall(frame.element, "a:p")
        self.assertEqual(len(paras), 2)
        self.assertEqual(find(paras[0], "a:r/a:t").text, "a")
        self.assertEqual(find(paras[1], "a:r/a:t").text, "b")

    def test_text_empty_line_becomes_empty_paragraph(self):
        frame = self._frame().text("a\n\nb")
        paras = findall(frame.element, "a:p")
        self.assertEqual(len(paras), 3)
        self.assertEqual(len(paras[1]), 0)

    def test_text_replaces_previous_content(self):
        frame = self._frame().text("alt")
        frame.text("neu")
        texts = [t.text for t in findall(frame.element, "a:p/a:r/a:t")]
        self.assertEqual(texts, ["neu"])

    def test_text_applies_formats(self):
        frame = self._frame().text(
            "x", fmt=RunFormat(size_pt=24), pf=ParaFormat(align="ctr")
        )
        para = find(frame.element, "a:p")
        self.assertEqual(find(para, "a:pPr").get("algn"), "ctr")
        self.assertEqual(find(para, "a:r/a:rPr").get("sz"), "2400")

    def test_methods_chain(self):
        frame = self._frame()
        self.assertIs(frame.text("a"), frame)
        self.assertIs(frame.paragraph("b"), frame)
        self.assertIs(frame.bullets(["c"]), frame)

    def test_paragraph_drops_lone_empty_placeholder(self):
        frame = self._frame()  # txbody_el([]) holds one empty <a:p>
        frame.paragraph("erste")
        paras = findall(frame.element, "a:p")
        self.assertEqual(len(paras), 1)
        frame.paragraph("zweite")
        self.assertEqual(len(findall(frame.element, "a:p")), 2)

    def test_paragraph_with_run_tuples(self):
        frame = self._frame().paragraph(
            [("fett", RunFormat(bold=True)), (" normal", None)]
        )
        runs = findall(frame.element, "a:p/a:r")
        self.assertEqual(len(runs), 2)
        self.assertEqual(find(runs[0], "a:rPr").get("b"), "1")
        self.assertIsNone(find(runs[1], "a:rPr"))

    def test_bullets_levels_and_overrides(self):
        frame = self._frame().bullets(
            [
                "oben",
                ("eingerückt", 1),
                {"text": "rot", "level": 2, "color": "FF0000"},
            ],
            base_fmt=RunFormat(size_pt=14),
        )
        paras = findall(frame.element, "a:p")
        self.assertEqual(len(paras), 3)
        self.assertIsNone(find(paras[0], "a:pPr"))  # level 0 -> no pPr needed
        self.assertEqual(find(paras[1], "a:pPr").get("lvl"), "1")
        self.assertEqual(find(paras[2], "a:pPr").get("lvl"), "2")
        rpr = find(paras[2], "a:r/a:rPr")
        self.assertEqual(rpr.get("sz"), "1400")  # base_fmt preserved
        self.assertEqual(
            find(rpr, "a:solidFill/a:srgbClr").get("val"), "FF0000"
        )

    def test_bullets_replace_content(self):
        frame = self._frame().text("alt")
        frame.bullets(["neu"])
        texts = [t.text for t in findall(frame.element, "a:p/a:r/a:t")]
        self.assertEqual(texts, ["neu"])

    def test_bullet_dict_requires_text(self):
        with self.assertRaises(BuildError):
            self._frame().bullets([{"level": 1}])

    def test_bullet_dict_unknown_key(self):
        with self.assertRaises(BuildError):
            self._frame().bullets([{"text": "x", "weight": "bold"}])

    def test_bullet_bad_tuple(self):
        with self.assertRaises(BuildError):
            self._frame().bullets([("a", 1, "extra")])

    def test_bullet_bad_type(self):
        with self.assertRaises(BuildError):
            self._frame().bullets([42])

    def test_umlauts_and_markup_survive_round_trip(self):
        frame = self._frame().text('Müller & Söhne <GmbH> "Ärzte"')
        root = parse_xml(serialize(frame.element))
        self.assertEqual(
            find(root, "a:p/a:r/a:t").text, 'Müller & Söhne <GmbH> "Ärzte"'
        )


if __name__ == "__main__":
    unittest.main()
