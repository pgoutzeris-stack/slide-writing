"""Tests for deckforge.slide: SlideBuilder and PlaceholderShape."""

from __future__ import annotations

import os
import struct
import tempfile
import unittest

from deckforge.emu import SLIDE_H_16_9, SLIDE_W_16_9, Box, pt
from deckforge.errors import BuildError
from deckforge.model import LayoutSpec, MasterSpec, PlaceholderSpec
from deckforge.slide import PlaceholderShape, SlideBuilder
from deckforge.text import RunFormat, TextFrame
from deckforge.theme import ColorScheme, FontScheme, Theme
from deckforge.xmlcore import el, find, findall, parse_xml, qn

#: Minimal but valid PNG header: signature + IHDR chunk start with 100x50 px.
PNG_100x50 = (
    b"\x89PNG\r\n\x1a\n"
    + struct.pack(">I", 13)
    + b"IHDR"
    + struct.pack(">II", 100, 50)
)


def _theme() -> Theme:
    return Theme(
        name="Test",
        colors=ColorScheme(
            dk1="000000",
            lt1="FFFFFF",
            dk2="1A1A2E",
            lt2="EEEEEE",
            accent1="206EFB",
            accent2="FF6B35",
            accent3="2E9E4F",
            accent4="E8A33D",
            accent5="9B5DE5",
            accent6="00BBF9",
            hlink="0563C1",
            folHlink="954F72",
        ),
        fonts=FontScheme(major_latin="Calibri Light", minor_latin="Calibri"),
        element=el("a:theme"),
    )


def _ph(ph_type: str, idx: int, shape_id: int, name: str) -> PlaceholderSpec:
    return PlaceholderSpec(
        ph_type=ph_type,
        idx=idx,
        shape_id=shape_id,
        name=name,
        box=Box(0, 0, 100, 100),
        element=el("p:sp"),
    )


def _layout(placeholders: list, name: str = "Titel und Inhalt") -> LayoutSpec:
    return LayoutSpec(
        partname="/ppt/slideLayouts/slideLayout1.xml",
        name=name,
        ltype="obj",
        placeholders=placeholders,
        element=el("p:sldLayout"),
        master_partname="/ppt/slideMasters/slideMaster1.xml",
    )


def _master(layout: LayoutSpec) -> MasterSpec:
    return MasterSpec(
        partname="/ppt/slideMasters/slideMaster1.xml",
        clr_map={
            "bg1": "lt1",
            "tx1": "dk1",
            "bg2": "lt2",
            "tx2": "dk2",
            "accent1": "accent1",
            "hlink": "hlink",
            "folHlink": "folHlink",
        },
        placeholders=[],
        layouts=[layout],
        theme=_theme(),
        element=el("p:sldMaster"),
    )


def _builder(placeholders: list | None = None) -> SlideBuilder:
    if placeholders is None:
        placeholders = [
            _ph("title", 0, 2, "Titel 1"),
            _ph("body", 1, 3, "Inhaltsplatzhalter 2"),
        ]
    layout = _layout(placeholders)
    return SlideBuilder(layout, _master(layout), SLIDE_W_16_9, SLIDE_H_16_9)


def _sp_tree(builder: SlideBuilder):
    root = parse_xml(builder.to_xml())
    return root, find(root, "p:cSld/p:spTree")


class TestSkeleton(unittest.TestCase):
    def test_root_structure(self):
        root, sp_tree = _sp_tree(_builder())
        self.assertEqual(root.tag, qn("p:sld"))
        self.assertEqual([c.tag for c in root], [qn("p:cSld"), qn("p:clrMapOvr")])
        self.assertIsNotNone(sp_tree)

    def test_clr_map_ovr_uses_master_mapping(self):
        root, _ = _sp_tree(_builder())
        self.assertIsNotNone(find(root, "p:clrMapOvr/a:masterClrMapping"))

    def test_sp_tree_skeleton(self):
        _, sp_tree = _sp_tree(_builder())
        self.assertEqual(
            [c.tag for c in sp_tree], [qn("p:nvGrpSpPr"), qn("p:grpSpPr")]
        )
        cnvpr = find(sp_tree, "p:nvGrpSpPr/p:cNvPr")
        self.assertEqual(cnvpr.get("id"), "1")
        self.assertEqual(cnvpr.get("name"), "")
        self.assertIsNotNone(find(sp_tree, "p:nvGrpSpPr/p:cNvGrpSpPr"))
        self.assertIsNotNone(find(sp_tree, "p:nvGrpSpPr/p:nvPr"))
        xfrm = find(sp_tree, "p:grpSpPr/a:xfrm")
        for tag, attrs in (
            ("a:off", ("x", "y")),
            ("a:ext", ("cx", "cy")),
            ("a:chOff", ("x", "y")),
            ("a:chExt", ("cx", "cy")),
        ):
            child = find(xfrm, tag)
            self.assertIsNotNone(child, tag)
            for attr in attrs:
                self.assertEqual(child.get(attr), "0", f"{tag}@{attr}")

    def test_dimensions_and_resolver(self):
        builder = _builder()
        self.assertEqual(builder.width, SLIDE_W_16_9)
        self.assertEqual(builder.height, SLIDE_H_16_9)
        self.assertEqual(builder.resolver.rgb("accent1"), "206EFB")
        self.assertEqual(builder.resolver.rgb("tx1"), "000000")  # via clr_map

    def test_next_id_starts_at_2(self):
        builder = _builder()
        self.assertEqual(builder.next_id(), 2)
        self.assertEqual(builder.next_id(), 3)
        self.assertEqual(builder.next_id(), 4)

    def test_to_xml_round_trips(self):
        blob = _builder().to_xml()
        self.assertTrue(
            blob.startswith(
                b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
            )
        )
        self.assertEqual(parse_xml(blob).tag, qn("p:sld"))


class TestPlaceholder(unittest.TestCase):
    def test_title_copies_type_and_omits_idx_zero(self):
        builder = _builder()
        shape = builder.placeholder("title")
        self.assertIsInstance(shape, PlaceholderShape)
        ph = find(shape.element, "p:nvSpPr/p:nvPr/p:ph")
        self.assertEqual(ph.get("type"), "title")
        self.assertIsNone(ph.get("idx"))

    def test_title_matches_ctr_title(self):
        builder = _builder([_ph("ctrTitle", 0, 2, "Titel 1")])
        ph = find(builder.placeholder("title").element, "p:nvSpPr/p:nvPr/p:ph")
        self.assertEqual(ph.get("type"), "ctrTitle")

    def test_subtitle_matches_subtitle_type(self):
        builder = _builder(
            [_ph("ctrTitle", 0, 2, "Titel 1"), _ph("subTitle", 1, 3, "Untertitel 2")]
        )
        ph = find(
            builder.placeholder("subtitle").element, "p:nvSpPr/p:nvPr/p:ph"
        )
        self.assertEqual(ph.get("type"), "subTitle")
        self.assertEqual(ph.get("idx"), "1")

    def test_body_matches_first_body(self):
        builder = _builder(
            [
                _ph("title", 0, 2, "Titel 1"),
                _ph("body", 1, 3, "Inhalt links"),
                _ph("body", 2, 4, "Inhalt rechts"),
            ]
        )
        ph = find(builder.placeholder("body").element, "p:nvSpPr/p:nvPr/p:ph")
        self.assertEqual(ph.get("type"), "body")
        self.assertEqual(ph.get("idx"), "1")

    def test_int_ref_matches_idx(self):
        builder = _builder()
        ph = find(builder.placeholder(1).element, "p:nvSpPr/p:nvPr/p:ph")
        self.assertEqual(ph.get("type"), "body")
        self.assertEqual(ph.get("idx"), "1")

    def test_name_ref_case_insensitive(self):
        builder = _builder()
        ph = find(
            builder.placeholder("inhaltsplatzhalter 2").element,
            "p:nvSpPr/p:nvPr/p:ph",
        )
        self.assertEqual(ph.get("idx"), "1")

    def test_missing_placeholder_lists_available(self):
        builder = _builder()
        with self.assertRaises(BuildError) as ctx:
            builder.placeholder("subtitle")
        message = str(ctx.exception)
        self.assertIn("subtitle", message)
        self.assertIn("title", message)
        self.assertIn("body", message)
        self.assertIn("Inhaltsplatzhalter 2", message)

    def test_missing_placeholder_on_empty_layout(self):
        builder = _builder([])
        with self.assertRaises(BuildError) as ctx:
            builder.placeholder(0)
        self.assertIn("none", str(ctx.exception))

    def test_shape_structure(self):
        builder = _builder()
        sp = builder.placeholder("title").element
        self.assertEqual(sp.tag, qn("p:sp"))
        cnvpr = find(sp, "p:nvSpPr/p:cNvPr")
        self.assertEqual(cnvpr.get("id"), "2")
        self.assertEqual(cnvpr.get("name"), "Titel 1")
        locks = find(sp, "p:nvSpPr/p:cNvSpPr/a:spLocks")
        self.assertEqual(locks.get("noGrp"), "1")
        sppr = find(sp, "p:spPr")
        self.assertEqual(len(sppr), 0, "spPr must stay empty for inheritance")
        self.assertEqual(sppr.attrib, {})
        txbody = find(sp, "p:txBody")
        self.assertEqual(
            [c.tag for c in txbody],
            [qn("a:bodyPr"), qn("a:lstStyle"), qn("a:p")],
        )

    def test_shape_appended_to_sp_tree(self):
        builder = _builder()
        builder.placeholder("title")
        _, sp_tree = _sp_tree(builder)
        self.assertEqual(sp_tree[-1].tag, qn("p:sp"))
        self.assertIsNotNone(find(sp_tree[-1], "p:nvSpPr/p:nvPr/p:ph"))

    def test_text_and_bullets_chain(self):
        builder = _builder()
        shape = builder.placeholder("body")
        self.assertIs(shape.text("Hallo", bold=True), shape)
        run = find(shape.element, "p:txBody/a:p/a:r")
        self.assertEqual(find(run, "a:rPr").get("b"), "1")
        self.assertIs(shape.bullets(["a", ("b", 1)], size_pt=14), shape)
        paras = findall(shape.element, "p:txBody/a:p")
        self.assertEqual(len(paras), 2)
        self.assertEqual(find(paras[1], "a:pPr").get("lvl"), "1")
        self.assertEqual(find(paras[0], "a:r/a:rPr").get("sz"), "1400")

    def test_text_rejects_unknown_format_kwargs(self):
        with self.assertRaises(BuildError):
            _builder().placeholder("title").text("x", weight="bold")

    def test_frame_is_textframe_on_own_txbody(self):
        shape = _builder().placeholder("title")
        self.assertIsInstance(shape.frame, TextFrame)
        self.assertIs(shape.frame.element, find(shape.element, "p:txBody"))

    def test_title_convenience(self):
        builder = _builder()
        shape = builder.title("Überschrift")
        self.assertEqual(
            find(shape.element, "p:txBody/a:p/a:r/a:t").text, "Überschrift"
        )
        ph = find(shape.element, "p:nvSpPr/p:nvPr/p:ph")
        self.assertEqual(ph.get("type"), "title")


class TestAddTextbox(unittest.TestCase):
    def test_structure(self):
        builder = _builder()
        frame = builder.add_textbox(Box(10, 20, 300, 400), anchor="ctr")
        self.assertIsInstance(frame, TextFrame)
        _, sp_tree = _sp_tree(builder)
        sp = sp_tree[-1]
        self.assertEqual(sp.tag, qn("p:sp"))
        self.assertEqual(find(sp, "p:nvSpPr/p:cNvSpPr").get("txBox"), "1")
        off = find(sp, "p:spPr/a:xfrm/a:off")
        ext = find(sp, "p:spPr/a:xfrm/a:ext")
        self.assertEqual((off.get("x"), off.get("y")), ("10", "20"))
        self.assertEqual((ext.get("cx"), ext.get("cy")), ("300", "400"))
        self.assertEqual(find(sp, "p:spPr/a:prstGeom").get("prst"), "rect")
        self.assertIsNotNone(find(sp, "p:spPr/a:noFill"))
        self.assertEqual(find(sp, "p:txBody/a:bodyPr").get("anchor"), "ctr")

    def test_frame_writes_into_slide(self):
        builder = _builder()
        builder.add_textbox(Box(0, 0, 100, 100)).text("Notiz")
        root, _ = _sp_tree(builder)
        texts = [t.text for t in findall(root, ".//" + qn("a:t"))]
        self.assertIn("Notiz", texts)


class TestAddShape(unittest.TestCase):
    def test_fill_line_text(self):
        builder = _builder()
        shape = builder.add_shape(
            "roundRect",
            Box(1, 2, 3, 4),
            fill="accent1",
            line="FFFFFF",
            line_w_pt=2.0,
            text="Box",
        )
        _, sp_tree = _sp_tree(builder)
        self.assertEqual(sp_tree[-1].tag, qn("p:sp"))
        self.assertEqual(
            find(shape, "p:spPr/a:prstGeom").get("prst"), "roundRect"
        )
        fill_clr = find(shape, "p:spPr/a:solidFill/a:schemeClr")
        self.assertEqual(fill_clr.get("val"), "accent1")
        ln = find(shape, "p:spPr/a:ln")
        self.assertEqual(ln.get("w"), str(pt(2.0)))
        self.assertEqual(
            find(ln, "a:solidFill/a:srgbClr").get("val"), "FFFFFF"
        )
        self.assertEqual(find(shape, "p:txBody/a:bodyPr").get("anchor"), "ctr")
        para = find(shape, "p:txBody/a:p")
        self.assertEqual(find(para, "a:pPr").get("algn"), "ctr")
        self.assertEqual(find(para, "a:r/a:t").text, "Box")

    def test_minimal_shape_has_no_fill_or_line(self):
        shape = _builder().add_shape("ellipse", Box(0, 0, 10, 10))
        self.assertIsNone(find(shape, "p:spPr/a:solidFill"))
        self.assertIsNone(find(shape, "p:spPr/a:ln"))
        self.assertIsNone(find(shape, "p:txBody"))

    def test_adjust_values_and_rotation(self):
        shape = _builder().add_shape(
            "pie", Box(0, 0, 10, 10), adj={"adj1": 0, "adj2": 16200000}, rot=60000
        )
        gds = findall(shape, "p:spPr/a:prstGeom/a:avLst/a:gd")
        self.assertEqual(
            [(g.get("name"), g.get("fmla")) for g in gds],
            [("adj1", "val 0"), ("adj2", "val 16200000")],
        )
        self.assertEqual(find(shape, "p:spPr/a:xfrm").get("rot"), "60000")


class TestAddLine(unittest.TestCase):
    def test_connector(self):
        builder = _builder()
        cxn = builder.add_line(100, 200, 400, 600, color="accent1", w_pt=1.0)
        _, sp_tree = _sp_tree(builder)
        self.assertEqual(sp_tree[-1].tag, qn("p:cxnSp"))
        self.assertEqual(cxn.tag, qn("p:cxnSp"))
        off = find(cxn, "p:spPr/a:xfrm/a:off")
        ext = find(cxn, "p:spPr/a:xfrm/a:ext")
        self.assertEqual((off.get("x"), off.get("y")), ("100", "200"))
        self.assertEqual((ext.get("cx"), ext.get("cy")), ("300", "400"))
        self.assertEqual(find(cxn, "p:spPr/a:prstGeom").get("prst"), "line")
        self.assertEqual(
            find(cxn, "p:spPr/a:ln/a:solidFill/a:schemeClr").get("val"),
            "accent1",
        )

    def test_dash(self):
        cxn = _builder().add_line(0, 0, 10, 10, dash="dash")
        self.assertEqual(
            find(cxn, "p:spPr/a:ln/a:prstDash").get("val"), "dash"
        )


class TestAddPicture(unittest.TestCase):
    def test_pending_images_and_temp_rid(self):
        builder = _builder()
        pic = builder.add_picture(PNG_100x50, Box(0, 0, 1000, 1000))
        self.assertEqual(builder.pending_images, [("img:1", PNG_100x50)])
        blip = find(pic, "p:blipFill/a:blip")
        self.assertEqual(blip.get(qn("r:embed")), "img:1")
        self.assertIn(b'r:embed="img:1"', builder.to_xml())

    def test_temp_rids_count_up(self):
        builder = _builder()
        builder.add_picture(PNG_100x50, Box(0, 0, 100, 100))
        builder.add_picture(PNG_100x50, Box(0, 0, 100, 100))
        self.assertEqual(
            [rid for rid, _ in builder.pending_images], ["img:1", "img:2"]
        )

    def test_aspect_ratio_fit_centered(self):
        pic = _builder().add_picture(PNG_100x50, Box(0, 0, 1000, 1000))
        off = find(pic, "p:spPr/a:xfrm/a:off")
        ext = find(pic, "p:spPr/a:xfrm/a:ext")
        self.assertEqual((ext.get("cx"), ext.get("cy")), ("1000", "500"))
        self.assertEqual((off.get("x"), off.get("y")), ("0", "250"))

    def test_appended_to_sp_tree(self):
        builder = _builder()
        builder.add_picture(PNG_100x50, Box(0, 0, 100, 100))
        _, sp_tree = _sp_tree(builder)
        self.assertEqual(sp_tree[-1].tag, qn("p:pic"))

    def test_file_path_input(self):
        builder = _builder()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bild.png")
            with open(path, "wb") as fh:
                fh.write(PNG_100x50)
            builder.add_picture(path, Box(0, 0, 100, 100))
        self.assertEqual(builder.pending_images[0], ("img:1", PNG_100x50))

    def test_missing_file_raises_builderror(self):
        with self.assertRaises(BuildError):
            _builder().add_picture("/nonexistent/bild.png", Box(0, 0, 10, 10))

    def test_invalid_type_raises_builderror(self):
        with self.assertRaises(BuildError):
            _builder().add_picture(42, Box(0, 0, 10, 10))


class TestAddTable(unittest.TestCase):
    def test_table_appended(self):
        builder = _builder()
        frame = builder.add_table(
            Box(0, 0, 6000000, 2000000),
            ["Spalte A", "Spalte B"],
            [["1", "2"], ["3", "4"]],
        )
        _, sp_tree = _sp_tree(builder)
        self.assertEqual(sp_tree[-1].tag, qn("p:graphicFrame"))
        self.assertEqual(frame.tag, qn("p:graphicFrame"))
        self.assertEqual(find(frame, "p:nvGraphicFramePr/p:cNvPr").get("id"), "2")
        tbl = find(frame, "a:graphic/a:graphicData/a:tbl")
        self.assertIsNotNone(tbl)
        self.assertEqual(len(findall(tbl, "a:tr")), 3)  # header + 2 rows


class TestToXml(unittest.TestCase):
    def test_full_slide_round_trip_with_special_chars(self):
        builder = _builder()
        builder.title("Größenordnung & <Maßstab>")
        builder.placeholder("body").bullets(["Ärger", "Übermut"])
        builder.add_textbox(Box(0, 0, 100, 100)).text('Q&A: "x < y > z"')
        root = parse_xml(builder.to_xml())
        texts = [t.text for t in root.iter(qn("a:t"))]
        self.assertIn("Größenordnung & <Maßstab>", texts)
        self.assertIn("Ärger", texts)
        self.assertIn("Übermut", texts)
        self.assertIn('Q&A: "x < y > z"', texts)

    def test_shape_ids_are_unique_and_sequential(self):
        builder = _builder()
        builder.placeholder("title")
        builder.add_textbox(Box(0, 0, 1, 1))
        builder.add_shape("rect", Box(0, 0, 1, 1))
        builder.add_line(0, 0, 1, 1)
        builder.add_picture(PNG_100x50, Box(0, 0, 10, 10))
        root = parse_xml(builder.to_xml())
        ids = sorted(
            int(c.get("id"))
            for c in root.iter(qn("p:cNvPr"))
        )
        self.assertEqual(ids, [1, 2, 3, 4, 5, 6])


if __name__ == "__main__":
    unittest.main()
