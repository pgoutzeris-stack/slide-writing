"""Unit tests for slidewriting.shapes (free shapes, connectors, pictures, image sniffing)."""

from __future__ import annotations

import struct
import unittest

from slidewriting.emu import Box
from slidewriting.errors import BuildError
from slidewriting.shapes import (
    connector_el,
    detect_image,
    line_props,
    no_fill,
    picture_el,
    shape_el,
)
from slidewriting.xmlcore import el, find, findall, get, qn


def _png_bytes(width: int, height: int) -> bytes:
    """Build a minimal PNG prefix: signature + IHDR length/type + dimensions."""
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
    )


def _jpeg_bytes(width: int, height: int, sof_marker: int = 0xC0) -> bytes:
    """Build a minimal JPEG: SOI, APP0, DHT (skipped), RST (standalone), SOFn."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    dht = b"\xff\xc4" + struct.pack(">H", 4) + b"\x00\x00"
    rst = b"\xff\xd0"  # standalone marker, no length field
    sof = (
        bytes([0xFF, sof_marker])
        + struct.pack(">H", 11)
        + b"\x08"
        + struct.pack(">H", height)
        + struct.pack(">H", width)
        + b"\x03\x01\x11\x00"
    )
    return b"\xff\xd8" + app0 + dht + rst + sof


class DetectImageTests(unittest.TestCase):
    def test_png_dimensions(self) -> None:
        ext, ct, w, h = detect_image(_png_bytes(640, 480))
        self.assertEqual((ext, ct, w, h), ("png", "image/png", 640, 480))

    def test_png_truncated_raises(self) -> None:
        with self.assertRaises(BuildError):
            detect_image(b"\x89PNG\r\n\x1a\n\x00\x00")

    def test_jpeg_baseline_sof0(self) -> None:
        ext, ct, w, h = detect_image(_jpeg_bytes(1024, 768, sof_marker=0xC0))
        self.assertEqual((ext, ct, w, h), ("jpeg", "image/jpeg", 1024, 768))

    def test_jpeg_progressive_sof2(self) -> None:
        ext, ct, w, h = detect_image(_jpeg_bytes(300, 150, sof_marker=0xC2))
        self.assertEqual((ext, ct, w, h), ("jpeg", "image/jpeg", 300, 150))

    def test_jpeg_skips_dht_c4(self) -> None:
        # _jpeg_bytes embeds a C4 (DHT) segment before SOF; C4 must not be
        # mistaken for a frame header.
        ext, _, w, h = detect_image(_jpeg_bytes(20, 10))
        self.assertEqual((ext, w, h), ("jpeg", 20, 10))

    def test_jpeg_with_fill_bytes_before_marker(self) -> None:
        # 0xFF padding (fill bytes) before a marker byte must be skipped.
        app0 = b"\xff\xe0" + struct.pack(">H", 4) + b"\x00\x00"
        sof = (
            b"\xff\xff\xff\xc0"
            + struct.pack(">H", 11)
            + b"\x08"
            + struct.pack(">HH", 99, 77)
            + b"\x03\x01\x11\x00"
        )
        ext, _, w, h = detect_image(b"\xff\xd8" + app0 + sof)
        self.assertEqual((ext, w, h), ("jpeg", 77, 99))

    def test_jpeg_without_sof_raises(self) -> None:
        blob = b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 4) + b"\x00\x00"
        with self.assertRaises(BuildError):
            detect_image(blob)

    def test_unsupported_format_raises(self) -> None:
        with self.assertRaises(BuildError):
            detect_image(b"GIF89a\x00\x00\x00\x00")
        with self.assertRaises(BuildError):
            detect_image(b"")


class ShapeElTests(unittest.TestCase):
    def test_basic_structure(self) -> None:
        box = Box(100, 200, 300, 400)
        sp = shape_el(3, "Box 2", "roundRect", box)
        self.assertEqual(sp.tag, qn("p:sp"))
        cnv = find(sp, "p:nvSpPr/p:cNvPr")
        self.assertEqual(cnv.get("id"), "3")
        self.assertEqual(cnv.get("name"), "Box 2")
        self.assertIsNotNone(find(sp, "p:nvSpPr/p:cNvSpPr"))
        self.assertIsNotNone(find(sp, "p:nvSpPr/p:nvPr"))
        off = find(sp, "p:spPr/a:xfrm/a:off")
        ext = find(sp, "p:spPr/a:xfrm/a:ext")
        self.assertEqual((off.get("x"), off.get("y")), ("100", "200"))
        self.assertEqual((ext.get("cx"), ext.get("cy")), ("300", "400"))
        geom = find(sp, "p:spPr/a:prstGeom")
        self.assertEqual(geom.get("prst"), "roundRect")
        self.assertIsNotNone(find(geom, "a:avLst"))

    def test_rot_and_flips(self) -> None:
        sp = shape_el(2, "S", "rect", Box(0, 0, 10, 10), rot=2700000,
                      flip_h=True, flip_v=True)
        xfrm = find(sp, "p:spPr/a:xfrm")
        self.assertEqual(xfrm.get("rot"), "2700000")
        self.assertEqual(xfrm.get("flipH"), "1")
        self.assertEqual(xfrm.get("flipV"), "1")
        plain = find(shape_el(2, "S", "rect", Box(0, 0, 1, 1)), "p:spPr/a:xfrm")
        self.assertIsNone(plain.get("rot"))
        self.assertIsNone(plain.get("flipH"))
        self.assertIsNone(plain.get("flipV"))

    def test_adjust_values(self) -> None:
        sp = shape_el(2, "Pie", "pie", Box(0, 0, 1, 1),
                      adj={"adj1": 0, "adj2": 16200000})
        gds = findall(sp, "p:spPr/a:prstGeom/a:avLst/a:gd")
        self.assertEqual(len(gds), 2)
        self.assertEqual(gds[0].get("name"), "adj1")
        self.assertEqual(gds[0].get("fmla"), "val 0")
        self.assertEqual(gds[1].get("name"), "adj2")
        self.assertEqual(gds[1].get("fmla"), "val 16200000")

    def test_fill_line_txbody_order(self) -> None:
        fill = el("a:solidFill")
        line = el("a:ln")
        txbody = el("p:txBody")
        sp = shape_el(4, "S", "rect", Box(0, 0, 1, 1),
                      fill=fill, line=line, txbody=txbody)
        sp_pr = find(sp, "p:spPr")
        tags = [child.tag for child in sp_pr]
        self.assertEqual(
            tags,
            [qn("a:xfrm"), qn("a:prstGeom"), qn("a:solidFill"), qn("a:ln")],
        )
        # txBody is the last child of p:sp, after spPr.
        self.assertEqual(list(sp)[-1].tag, qn("p:txBody"))

    def test_no_fill_element(self) -> None:
        nf = no_fill()
        self.assertEqual(nf.tag, qn("a:noFill"))
        self.assertEqual(len(list(nf)), 0)
        sp = shape_el(2, "S", "rect", Box(0, 0, 1, 1), fill=no_fill())
        self.assertIsNotNone(find(sp, "p:spPr/a:noFill"))


class LinePropsTests(unittest.TestCase):
    def test_width_fill_and_cap(self) -> None:
        color = el("a:srgbClr", {"val": "FF0000"})
        ln = line_props(color, 12700)
        self.assertEqual(ln.tag, qn("a:ln"))
        self.assertEqual(ln.get("w"), "12700")
        self.assertEqual(ln.get("cap"), "flat")
        clr = find(ln, "a:solidFill/a:srgbClr")
        self.assertEqual(clr.get("val"), "FF0000")
        self.assertIsNone(find(ln, "a:prstDash"))

    def test_dash_and_round_cap(self) -> None:
        ln = line_props(el("a:schemeClr", {"val": "tx1"}), 9525,
                        dash="dash", cap="round")
        self.assertEqual(ln.get("cap"), "rnd")
        self.assertEqual(find(ln, "a:prstDash").get("val"), "dash")
        # solidFill must come before prstDash (OOXML child order).
        tags = [child.tag for child in ln]
        self.assertEqual(tags, [qn("a:solidFill"), qn("a:prstDash")])

    def test_square_cap_alias(self) -> None:
        self.assertEqual(
            line_props(el("a:srgbClr", {"val": "000000"}), 1, cap="sq").get("cap"),
            "sq",
        )

    def test_unknown_cap_raises(self) -> None:
        with self.assertRaises(BuildError):
            line_props(el("a:srgbClr", {"val": "000000"}), 1, cap="pointy")


class ConnectorElTests(unittest.TestCase):
    def test_left_to_right_descending(self) -> None:
        ln = el("a:ln")
        cxn = connector_el(5, "Line 4", 100, 200, 400, 600, ln)
        self.assertEqual(cxn.tag, qn("p:cxnSp"))
        cnv = find(cxn, "p:nvCxnSpPr/p:cNvPr")
        self.assertEqual(cnv.get("id"), "5")
        self.assertEqual(cnv.get("name"), "Line 4")
        xfrm = find(cxn, "p:spPr/a:xfrm")
        self.assertIsNone(xfrm.get("flipH"))
        self.assertIsNone(xfrm.get("flipV"))
        off = find(xfrm, "a:off")
        ext = find(xfrm, "a:ext")
        self.assertEqual((off.get("x"), off.get("y")), ("100", "200"))
        self.assertEqual((ext.get("cx"), ext.get("cy")), ("300", "400"))
        self.assertEqual(find(cxn, "p:spPr/a:prstGeom").get("prst"), "line")
        self.assertIsNotNone(find(cxn, "p:spPr/a:ln"))

    def test_flips_when_endpoints_reversed(self) -> None:
        cxn = connector_el(2, "L", 400, 600, 100, 200, el("a:ln"))
        xfrm = find(cxn, "p:spPr/a:xfrm")
        self.assertEqual(xfrm.get("flipH"), "1")
        self.assertEqual(xfrm.get("flipV"), "1")
        off = find(xfrm, "a:off")
        ext = find(xfrm, "a:ext")
        self.assertEqual((off.get("x"), off.get("y")), ("100", "200"))
        self.assertEqual((ext.get("cx"), ext.get("cy")), ("300", "400"))

    def test_horizontal_line_zero_height(self) -> None:
        cxn = connector_el(2, "L", 0, 500, 1000, 500, el("a:ln"))
        ext = find(cxn, "p:spPr/a:xfrm/a:ext")
        self.assertEqual((ext.get("cx"), ext.get("cy")), ("1000", "0"))


class PictureElTests(unittest.TestCase):
    def test_structure_and_embed(self) -> None:
        pic = picture_el(7, "Picture 6", "rId2", Box(10, 20, 30, 40))
        self.assertEqual(pic.tag, qn("p:pic"))
        cnv = find(pic, "p:nvPicPr/p:cNvPr")
        self.assertEqual(cnv.get("id"), "7")
        self.assertEqual(cnv.get("name"), "Picture 6")
        blip = find(pic, "p:blipFill/a:blip")
        self.assertEqual(get(blip, "r:embed"), "rId2")
        self.assertIsNotNone(find(pic, "p:blipFill/a:stretch/a:fillRect"))
        off = find(pic, "p:spPr/a:xfrm/a:off")
        ext = find(pic, "p:spPr/a:xfrm/a:ext")
        self.assertEqual((off.get("x"), off.get("y")), ("10", "20"))
        self.assertEqual((ext.get("cx"), ext.get("cy")), ("30", "40"))
        self.assertEqual(find(pic, "p:spPr/a:prstGeom").get("prst"), "rect")

    def test_temp_rid_token(self) -> None:
        pic = picture_el(2, "P", "img:1", Box(0, 0, 1, 1))
        self.assertEqual(get(find(pic, "p:blipFill/a:blip"), "r:embed"), "img:1")


if __name__ == "__main__":
    unittest.main()
