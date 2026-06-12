"""Tests for slidewriting.xmlcore."""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from slidewriting.errors import SlideWritingError, ParseError
from slidewriting.xmlcore import NSMAP, el, find, findall, get, parse_xml, qn, serialize, sub

A_URI = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_URI = "http://schemas.openxmlformats.org/presentationml/2006/main"
R_URI = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


class TestQn(unittest.TestCase):
    def test_element_name(self):
        self.assertEqual(qn("a:t"), "{%s}t" % A_URI)
        self.assertEqual(qn("p:sld"), "{%s}sld" % P_URI)

    def test_attribute_name(self):
        self.assertEqual(qn("r:id"), "{%s}id" % R_URI)

    def test_passthrough_without_colon(self):
        self.assertEqual(qn("Relationship"), "Relationship")
        self.assertEqual(qn("idx"), "idx")

    def test_passthrough_clark_notation(self):
        clark = "{%s}t" % A_URI
        self.assertEqual(qn(clark), clark)

    def test_unknown_prefix_raises(self):
        with self.assertRaises(SlideWritingError):
            qn("nope:thing")

    def test_all_nsmap_prefixes_expand(self):
        for prefix, uri in NSMAP.items():
            self.assertEqual(qn(f"{prefix}:x"), "{%s}x" % uri)


class TestElSub(unittest.TestCase):
    def test_el_basic(self):
        node = el("a:p")
        self.assertEqual(node.tag, qn("a:p"))
        self.assertIsNone(node.text)

    def test_el_with_text_and_attrib(self):
        node = el("a:t", text="Hallo")
        self.assertEqual(node.text, "Hallo")
        node = el("a:off", {"x": "0", "y": "100"})
        self.assertEqual(node.get("x"), "0")
        self.assertEqual(node.get("y"), "100")

    def test_el_prefixed_attribute_key(self):
        node = el("a:blip", {"r:embed": "rId2"})
        self.assertEqual(node.get("{%s}embed" % R_URI), "rId2")
        self.assertEqual(get(node, "r:embed"), "rId2")

    def test_el_with_parent(self):
        parent = el("p:spTree")
        child = el("p:sp", parent=parent)
        self.assertIs(parent[0], child)

    def test_sub(self):
        parent = el("a:p")
        child = sub(parent, "a:r", {"x": "1"}, text=None)
        self.assertIs(parent[0], child)
        self.assertEqual(child.tag, qn("a:r"))
        self.assertEqual(child.get("x"), "1")
        grandchild = sub(child, "a:t", text="Text")
        self.assertEqual(grandchild.text, "Text")


class TestFindGet(unittest.TestCase):
    def setUp(self):
        self.root = el("p:sld")
        csld = sub(self.root, "p:cSld")
        self.sptree = sub(csld, "p:spTree")
        sub(self.sptree, "p:sp")
        sub(self.sptree, "p:sp")
        self.pic = sub(self.sptree, "p:pic")
        blipfill = sub(self.pic, "p:blipFill")
        sub(blipfill, "a:blip", {"r:embed": "rId7"})

    def test_find_prefixed_path(self):
        self.assertIs(find(self.root, "p:cSld/p:spTree"), self.sptree)
        self.assertIsNone(find(self.root, "p:cSld/p:nope"))

    def test_findall(self):
        sps = findall(self.sptree, "p:sp")
        self.assertEqual(len(sps), 2)
        self.assertEqual(findall(self.root, "p:cSld/p:spTree/p:pic"), [self.pic])

    def test_get_prefixed_attribute(self):
        blip = find(self.pic, "p:blipFill/a:blip")
        self.assertEqual(get(blip, "r:embed"), "rId7")
        self.assertIsNone(get(blip, "r:link"))
        self.assertEqual(get(blip, "r:link", "fallback"), "fallback")

    def test_get_plain_attribute(self):
        node = el("a:off", {"x": "5"})
        self.assertEqual(get(node, "x"), "5")


class TestParseSerialize(unittest.TestCase):
    def test_serialize_declaration(self):
        blob = serialize(el("p:sld"))
        self.assertTrue(
            blob.startswith(
                b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
            )
        )

    def test_serialize_uses_canonical_prefixes(self):
        root = el("p:sld")
        csld = sub(root, "p:cSld")
        tree = sub(csld, "p:spTree")
        sp = sub(tree, "p:sp")
        sub(sp, "a:t", text="x")
        blob = serialize(root)
        text = blob.decode("utf-8")
        self.assertIn("<p:sld", text)
        self.assertIn("<a:t>", text)
        self.assertIn('xmlns:p="%s"' % P_URI, text)
        self.assertIn('xmlns:a="%s"' % A_URI, text)
        self.assertNotIn("ns0:", text)

    def test_serialize_prefixed_attribute(self):
        root = el("p:pic")
        sub(root, "a:blip", {"r:embed": "rId3"})
        text = serialize(root).decode("utf-8")
        self.assertIn('r:embed="rId3"', text)
        self.assertIn('xmlns:r="%s"' % R_URI, text)

    def test_parse_roundtrip(self):
        root = el("p:sld")
        sub(root, "a:t", text="Umlaute äöü & <Sonderzeichen> \U0001f600")
        reparsed = parse_xml(serialize(root))
        self.assertEqual(reparsed.tag, qn("p:sld"))
        t = find(reparsed, "a:t")
        self.assertEqual(t.text, "Umlaute äöü & <Sonderzeichen> \U0001f600")

    def test_text_escaping_is_automatic(self):
        root = el("a:t", text='a & b < c > d "e"')
        body = serialize(root).decode("utf-8")
        self.assertIn("a &amp; b &lt; c", body)

    def test_parse_xml_invalid_raises(self):
        with self.assertRaises(ParseError):
            parse_xml(b"<unclosed")
        with self.assertRaises(ParseError):
            parse_xml(b"not xml at all")

    def test_parse_xml_returns_element(self):
        root = parse_xml(b"<root><child a='1'/></root>")
        self.assertIsInstance(root, ET.Element)
        self.assertEqual(root[0].get("a"), "1")


class TestNsmap(unittest.TestCase):
    def test_required_prefixes_present(self):
        for prefix in ("a", "p", "r", "ct", "rel", "cp", "dc", "dcterms", "xsi", "ep", "vt"):
            self.assertIn(prefix, NSMAP)
        self.assertEqual(len(NSMAP), 11)


if __name__ == "__main__":
    unittest.main()
