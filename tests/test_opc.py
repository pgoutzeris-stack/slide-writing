"""Tests for slidewriting.opc."""

from __future__ import annotations

import io
import unittest
import zipfile

from slidewriting.errors import PackageError
from slidewriting.opc import (
    CT_PNG,
    CT_PRESENTATION,
    CT_RELS,
    CT_SLIDE,
    CT_SLIDE_LAYOUT,
    CT_XML,
    RT_IMAGE,
    RT_OFFICE_DOCUMENT,
    RT_SLIDE,
    RT_SLIDE_LAYOUT,
    Package,
    Part,
    Relationship,
    Relationships,
)

PRESENTATION_XML = b"<presentation/>"
SLIDE_XML = b"<slide/>"
LAYOUT_XML = b"<layout/>"
PNG_BLOB = b"\x89PNG\r\n\x1a\nfakepayload"


def build_tiny_package() -> Package:
    """A minimal but representative package used by several tests."""
    pkg = Package.create()
    pkg.default_content_type("png", CT_PNG)
    pkg.add_part("/ppt/presentation.xml", CT_PRESENTATION, PRESENTATION_XML)
    pkg.add_part("/ppt/slides/slide1.xml", CT_SLIDE, SLIDE_XML)
    pkg.add_part("/ppt/slideLayouts/slideLayout1.xml", CT_SLIDE_LAYOUT, LAYOUT_XML)
    pkg.add_part("/ppt/media/image1.png", CT_PNG, PNG_BLOB)
    pkg.rels(None).add(RT_OFFICE_DOCUMENT, "ppt/presentation.xml")
    pkg.rels("/ppt/presentation.xml").add(RT_SLIDE, "slides/slide1.xml")
    slide_rels = pkg.rels("/ppt/slides/slide1.xml")
    slide_rels.add(RT_SLIDE_LAYOUT, "../slideLayouts/slideLayout1.xml")
    slide_rels.add(RT_IMAGE, "../media/image1.png")
    slide_rels.add(
        RT_IMAGE, "https://example.com/logo.png", external=True
    )
    return pkg


class TestRelationships(unittest.TestCase):
    def test_add_allocates_rids_max_plus_one(self):
        rels = Relationships("/ppt/presentation.xml")
        self.assertEqual(rels.add(RT_SLIDE, "slides/slide1.xml"), "rId1")
        self.assertEqual(rels.add(RT_SLIDE, "slides/slide2.xml"), "rId2")
        self.assertEqual(rels.add(RT_SLIDE, "slides/slide3.xml", rid="rId7"), "rId7")
        # gaps are NOT reused: next id is max+1
        self.assertEqual(rels.add(RT_SLIDE, "slides/slide4.xml"), "rId8")

    def test_add_duplicate_rid_raises(self):
        rels = Relationships("/x.xml")
        rels.add(RT_SLIDE, "a.xml", rid="rId1")
        with self.assertRaises(PackageError):
            rels.add(RT_SLIDE, "b.xml", rid="rId1")

    def test_get_and_by_type_and_iter_len(self):
        rels = Relationships("/x.xml")
        rid1 = rels.add(RT_SLIDE, "a.xml")
        rels.add(RT_SLIDE_LAYOUT, "l.xml")
        rels.add(RT_SLIDE, "b.xml")
        self.assertEqual(rels.get(rid1).target, "a.xml")
        self.assertIsNone(rels.get("rId99"))
        slides = rels.by_type(RT_SLIDE)
        self.assertEqual([r.target for r in slides], ["a.xml", "b.xml"])
        self.assertEqual(len(rels), 3)
        self.assertEqual(len(list(iter(rels))), 3)

    def test_external_relationship(self):
        rels = Relationships("/ppt/slides/slide1.xml")
        rid = rels.add(RT_IMAGE, "https://example.com/x.png", external=True)
        rel = rels.get(rid)
        self.assertEqual(rel.target_mode, "External")
        self.assertEqual(rel.target, "https://example.com/x.png")
        xml = rels.to_xml().decode("utf-8")
        self.assertIn('TargetMode="External"', xml)

    def test_internal_relationship_omits_target_mode(self):
        rels = Relationships("/x.xml")
        rels.add(RT_SLIDE, "a.xml")
        self.assertNotIn(b"TargetMode", rels.to_xml())

    def test_resolve_relative_target(self):
        rels = Relationships("/ppt/slides/slide1.xml")
        self.assertEqual(
            rels.resolve("../slideLayouts/slideLayout1.xml"),
            "/ppt/slideLayouts/slideLayout1.xml",
        )
        self.assertEqual(rels.resolve("../media/image1.png"), "/ppt/media/image1.png")

    def test_resolve_sibling_and_absolute(self):
        rels = Relationships("/ppt/presentation.xml")
        self.assertEqual(rels.resolve("slides/slide1.xml"), "/ppt/slides/slide1.xml")
        self.assertEqual(rels.resolve("/ppt/theme/theme1.xml"), "/ppt/theme/theme1.xml")

    def test_resolve_package_level(self):
        rels = Relationships("/")
        self.assertEqual(rels.resolve("ppt/presentation.xml"), "/ppt/presentation.xml")
        self.assertEqual(rels.resolve("docProps/core.xml"), "/docProps/core.xml")

    def test_parse_roundtrip(self):
        rels = Relationships("/ppt/slides/slide1.xml")
        rels.add(RT_SLIDE_LAYOUT, "../slideLayouts/slideLayout1.xml")
        rels.add(RT_IMAGE, "https://example.com", external=True)
        reparsed = Relationships.parse("/ppt/slides/slide1.xml", rels.to_xml())
        self.assertEqual(len(reparsed), 2)
        self.assertEqual(list(reparsed), list(rels))

    def test_parse_office_style_default_namespace(self):
        # Real Office .rels files use a default (unprefixed) namespace.
        blob = (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rId1" Type="' + RT_OFFICE_DOCUMENT.encode() + b'" '
            b'Target="ppt/presentation.xml"/></Relationships>'
        )
        rels = Relationships.parse("/", blob)
        self.assertEqual(len(rels), 1)
        rel = rels.get("rId1")
        self.assertEqual(rel.reltype, RT_OFFICE_DOCUMENT)
        self.assertEqual(rel.target, "ppt/presentation.xml")
        self.assertEqual(rel.target_mode, "Internal")


class TestPackageBasics(unittest.TestCase):
    def test_create_has_standard_defaults(self):
        pkg = Package.create()
        self.assertEqual(pkg._defaults, {"rels": CT_RELS, "xml": CT_XML})
        self.assertEqual(pkg.parts(), [])

    def test_part_accessors(self):
        pkg = build_tiny_package()
        part = pkg.part("/ppt/slides/slide1.xml")
        self.assertIsInstance(part, Part)
        self.assertEqual(part.content_type, CT_SLIDE)
        self.assertEqual(part.blob, SLIDE_XML)
        self.assertTrue(pkg.has_part("/ppt/presentation.xml"))
        self.assertFalse(pkg.has_part("/nope.xml"))
        with self.assertRaises(PackageError):
            pkg.part("/nope.xml")

    def test_parts_order_is_stable(self):
        pkg = build_tiny_package()
        self.assertEqual(
            [p.partname for p in pkg.parts()],
            [
                "/ppt/presentation.xml",
                "/ppt/slides/slide1.xml",
                "/ppt/slideLayouts/slideLayout1.xml",
                "/ppt/media/image1.png",
            ],
        )

    def test_add_part_validations(self):
        pkg = Package.create()
        with self.assertRaises(PackageError):
            pkg.add_part("relative.xml", CT_XML, b"<x/>")
        pkg.add_part("/a.xml", CT_XML, b"<x/>")
        with self.assertRaises(PackageError):
            pkg.add_part("/a.xml", CT_XML, b"<x/>")

    def test_add_part_records_override_only_when_needed(self):
        pkg = Package.create()
        pkg.default_content_type("png", CT_PNG)
        pkg.add_part("/ppt/media/image1.png", CT_PNG, PNG_BLOB)
        pkg.add_part("/ppt/slides/slide1.xml", CT_SLIDE, SLIDE_XML)
        self.assertNotIn("/ppt/media/image1.png", pkg._overrides)
        self.assertEqual(pkg._overrides["/ppt/slides/slide1.xml"], CT_SLIDE)

    def test_replace_blob(self):
        pkg = build_tiny_package()
        pkg.replace_blob("/ppt/slides/slide1.xml", b"<slide2/>")
        self.assertEqual(pkg.part("/ppt/slides/slide1.xml").blob, b"<slide2/>")
        with self.assertRaises(PackageError):
            pkg.replace_blob("/nope.xml", b"")

    def test_rels_auto_creates(self):
        pkg = Package.create()
        rels = pkg.rels("/ppt/presentation.xml")
        self.assertEqual(len(rels), 0)
        self.assertIs(pkg.rels("/ppt/presentation.xml"), rels)
        pkg_rels = pkg.rels()
        self.assertEqual(pkg_rels.source_partname, "/")
        self.assertIs(pkg.rels(None), pkg_rels)

    def test_default_content_type_normalizes(self):
        pkg = Package.create()
        pkg.default_content_type(".PNG", CT_PNG)
        self.assertEqual(pkg._defaults["png"], CT_PNG)

    def test_next_partname(self):
        pkg = Package.create()
        template = "/ppt/slides/slide{}.xml"
        self.assertEqual(pkg.next_partname(template), "/ppt/slides/slide1.xml")
        pkg.add_part("/ppt/slides/slide1.xml", CT_SLIDE, SLIDE_XML)
        pkg.add_part("/ppt/slides/slide3.xml", CT_SLIDE, SLIDE_XML)
        # first free number, not max+1
        self.assertEqual(pkg.next_partname(template), "/ppt/slides/slide2.xml")
        pkg.add_part("/ppt/slides/slide2.xml", CT_SLIDE, SLIDE_XML)
        self.assertEqual(pkg.next_partname(template), "/ppt/slides/slide4.xml")

    def test_main_part(self):
        pkg = build_tiny_package()
        self.assertEqual(pkg.main_part().partname, "/ppt/presentation.xml")

    def test_main_part_missing_rel_raises(self):
        pkg = Package.create()
        with self.assertRaises(PackageError):
            pkg.main_part()
        pkg.rels(None)  # empty package rels exist, but no officeDocument rel
        with self.assertRaises(PackageError):
            pkg.main_part()


class TestSaveAndOpen(unittest.TestCase):
    def test_roundtrip_parts_rels_content_types(self):
        pkg = build_tiny_package()
        buf = io.BytesIO()
        pkg.save(buf)
        buf.seek(0)
        reopened = Package.open(buf)

        # parts identical (name, content type, bytes) in identical order
        self.assertEqual(
            [(p.partname, p.content_type, p.blob) for p in pkg.parts()],
            [(p.partname, p.content_type, p.blob) for p in reopened.parts()],
        )
        # content types identical
        self.assertEqual(pkg._defaults, reopened._defaults)
        self.assertEqual(pkg._overrides, reopened._overrides)
        # rels identical for every source (package level and parts)
        for source in (None, "/ppt/presentation.xml", "/ppt/slides/slide1.xml"):
            self.assertEqual(list(pkg.rels(source)), list(reopened.rels(source)))
        # external relationship survived
        externals = [
            r for r in reopened.rels("/ppt/slides/slide1.xml") if r.target_mode == "External"
        ]
        self.assertEqual(len(externals), 1)
        self.assertEqual(externals[0].target, "https://example.com/logo.png")
        # main part reachable after reopen
        self.assertEqual(reopened.main_part().blob, PRESENTATION_XML)

    def test_zip_entry_order(self):
        pkg = build_tiny_package()
        buf = io.BytesIO()
        pkg.save(buf)
        buf.seek(0)
        names = zipfile.ZipFile(buf).namelist()
        self.assertEqual(
            names,
            [
                "[Content_Types].xml",
                "_rels/.rels",
                "ppt/presentation.xml",
                "ppt/_rels/presentation.xml.rels",
                "ppt/slides/slide1.xml",
                "ppt/slides/_rels/slide1.xml.rels",
                "ppt/slideLayouts/slideLayout1.xml",
                "ppt/media/image1.png",
            ],
        )

    def test_deterministic_save(self):
        pkg = build_tiny_package()
        buf1, buf2 = io.BytesIO(), io.BytesIO()
        pkg.save(buf1)
        pkg.save(buf2)
        self.assertEqual(buf1.getvalue(), buf2.getvalue())

    def test_fixed_zip_timestamps_and_compression(self):
        pkg = build_tiny_package()
        buf = io.BytesIO()
        pkg.save(buf)
        buf.seek(0)
        for info in zipfile.ZipFile(buf).infolist():
            self.assertEqual(info.date_time, (2026, 1, 1, 0, 0, 0))
            self.assertEqual(info.compress_type, zipfile.ZIP_DEFLATED)

    def test_content_types_xml_regenerated(self):
        pkg = build_tiny_package()
        buf = io.BytesIO()
        pkg.save(buf)
        buf.seek(0)
        blob = zipfile.ZipFile(buf).read("[Content_Types].xml").decode("utf-8")
        self.assertIn('Extension="rels"', blob)
        self.assertIn('Extension="png"', blob)
        self.assertIn('PartName="/ppt/slides/slide1.xml"', blob)
        self.assertIn(CT_SLIDE, blob)
        # the png part is covered by its Default, so no Override for it
        self.assertNotIn('PartName="/ppt/media/image1.png"', blob)

    def test_open_missing_content_types_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("ppt/presentation.xml", b"<p/>")
        buf.seek(0)
        with self.assertRaises(PackageError):
            Package.open(buf)

    def test_open_bad_zip_raises(self):
        with self.assertRaises(PackageError):
            Package.open(io.BytesIO(b"this is not a zip file"))

    def test_open_part_without_content_type_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "[Content_Types].xml",
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
            )
            zf.writestr("ppt/odd.bin", b"x")
        buf.seek(0)
        with self.assertRaises(PackageError):
            Package.open(buf)

    def test_added_slide_after_reopen(self):
        # simulate the writer flow: open, add a slide part + rel, save, reopen
        pkg = build_tiny_package()
        buf = io.BytesIO()
        pkg.save(buf)
        buf.seek(0)
        pkg2 = Package.open(buf)
        new_name = pkg2.next_partname("/ppt/slides/slide{}.xml")
        self.assertEqual(new_name, "/ppt/slides/slide2.xml")
        pkg2.add_part(new_name, CT_SLIDE, b"<slide2/>")
        rid = pkg2.rels("/ppt/presentation.xml").add(RT_SLIDE, "slides/slide2.xml")
        self.assertEqual(rid, "rId2")
        pkg2.rels(new_name).add(RT_SLIDE_LAYOUT, "../slideLayouts/slideLayout1.xml")
        buf2 = io.BytesIO()
        pkg2.save(buf2)
        buf2.seek(0)
        pkg3 = Package.open(buf2)
        self.assertEqual(pkg3.part(new_name).content_type, CT_SLIDE)
        layout_rel = pkg3.rels(new_name).by_type(RT_SLIDE_LAYOUT)[0]
        self.assertEqual(
            pkg3.rels(new_name).resolve(layout_rel.target),
            "/ppt/slideLayouts/slideLayout1.xml",
        )

    def test_relationship_dataclass_defaults(self):
        rel = Relationship("rId1", RT_SLIDE, "slides/slide1.xml")
        self.assertEqual(rel.target_mode, "Internal")


if __name__ == "__main__":
    unittest.main()
