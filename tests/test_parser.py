"""Tests for deckforge.parser and deckforge.model.

A minimal but complete template package (presentation + 1 master + 2 layouts
+ theme + 1 slide, with correct rels and content types) is hand-built
in memory via the :class:`deckforge.opc.Package` APIs and raw XML strings,
then parsed with :class:`deckforge.parser.TemplateParser`.
"""

from __future__ import annotations

import io
import unittest

from deckforge.emu import SLIDE_H_16_9, SLIDE_W_16_9, Box
from deckforge.errors import ParseError
from deckforge.model import LayoutSpec, MasterSpec, TemplateInfo
from deckforge.opc import (
    CT_PRESENTATION,
    CT_SLIDE,
    CT_SLIDE_LAYOUT,
    CT_SLIDE_MASTER,
    CT_THEME,
    RT_OFFICE_DOCUMENT,
    RT_SLIDE,
    RT_SLIDE_LAYOUT,
    RT_SLIDE_MASTER,
    RT_THEME,
    Package,
)
from deckforge.parser import (
    TemplateParser,
    effective_box,
    extract_placeholders,
    slide_title_text,
)
from deckforge.theme import ColorResolver
from deckforge.xmlcore import find, parse_xml

_NS = (
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)

# Non-default 4:3 size so reading p:sldSz is distinguishable from the default.
SLIDE_W_4_3 = 9144000
SLIDE_H_4_3 = 6858000

PRESENTATION_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation {_NS}>
  <p:sldMasterIdLst>
    <p:sldMasterId id="2147483648" r:id="rId1"/>
  </p:sldMasterIdLst>
  <p:sldIdLst>
    <p:sldId id="256" r:id="rId2"/>
  </p:sldIdLst>
  <p:sldSz cx="{SLIDE_W_4_3}" cy="{SLIDE_H_4_3}"/>
  <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>
""".encode("utf-8")

PRESENTATION_XML_NO_SLDSZ = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation {_NS}>
  <p:sldMasterIdLst>
    <p:sldMasterId id="2147483648" r:id="rId1"/>
  </p:sldMasterIdLst>
  <p:sldIdLst>
    <p:sldId id="256" r:id="rId2"/>
  </p:sldIdLst>
</p:presentation>
""".encode("utf-8")

# Master: title ph (box), body ph idx=1 (box), attribute-less ph (defaults),
# one plain shape that must be ignored by extract_placeholders.
MASTER_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster {_NS}>
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr/>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="2" name="Title Placeholder 1"/>
          <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
          <p:nvPr><p:ph type="title"/></p:nvPr>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="838200" y="365125"/><a:ext cx="10515600" cy="1325563"/></a:xfrm>
        </p:spPr>
        <p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>
      </p:sp>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="3" name="Text Placeholder 2"/>
          <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
          <p:nvPr><p:ph type="body" idx="1"/></p:nvPr>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="838200" y="1825625"/><a:ext cx="10515600" cy="4351338"/></a:xfrm>
        </p:spPr>
        <p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>
      </p:sp>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="4" name="Default Placeholder 3"/>
          <p:cNvSpPr/>
          <p:nvPr><p:ph/></p:nvPr>
        </p:nvSpPr>
        <p:spPr/>
        <p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>
      </p:sp>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="5" name="Decoration"/><p:cNvSpPr/><p:nvPr/>
        </p:nvSpPr>
        <p:spPr/>
      </p:sp>
    </p:spTree>
  </p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst>
    <p:sldLayoutId id="2147483649" r:id="rId1"/>
    <p:sldLayoutId id="2147483650" r:id="rId2"/>
  </p:sldLayoutIdLst>
</p:sldMaster>
""".encode("utf-8")

# Layout 1 ("Titelfolie", type "title"): ctrTitle + subTitle, both with boxes.
LAYOUT1_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout {_NS} type="title">
  <p:cSld name="Titelfolie">
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr/>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="2" name="Titel 1"/>
          <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
          <p:nvPr><p:ph type="ctrTitle"/></p:nvPr>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="1524000" y="1122363"/><a:ext cx="9144000" cy="2387600"/></a:xfrm>
        </p:spPr>
        <p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>
      </p:sp>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="3" name="Untertitel 2"/>
          <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
          <p:nvPr><p:ph type="subTitle" idx="1"/></p:nvPr>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="1524000" y="3602038"/><a:ext cx="9144000" cy="1655762"/></a:xfrm>
        </p:spPr>
        <p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sldLayout>
""".encode("utf-8")

# Layout 2 ("Titel und Inhalt", type "obj"): title WITHOUT a:xfrm (inherits
# from master), body idx=1 with its own box.
LAYOUT2_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout {_NS} type="obj">
  <p:cSld name="Titel und Inhalt">
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr/>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="2" name="Titel 1"/>
          <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
          <p:nvPr><p:ph type="title"/></p:nvPr>
        </p:nvSpPr>
        <p:spPr/>
        <p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>
      </p:sp>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="3" name="Inhaltsplatzhalter 2"/>
          <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
          <p:nvPr><p:ph idx="1"/></p:nvPr>
        </p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="838200" y="1825625"/><a:ext cx="10515600" cy="4000000"/></a:xfrm>
        </p:spPr>
        <p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sldLayout>
""".encode("utf-8")

THEME_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="TestTheme">
  <a:themeElements>
    <a:clrScheme name="Test">
      <a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>
      <a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="1F2937"/></a:dk2>
      <a:lt2><a:srgbClr val="E7E6E6"/></a:lt2>
      <a:accent1><a:srgbClr val="206EFB"/></a:accent1>
      <a:accent2><a:srgbClr val="ED7D31"/></a:accent2>
      <a:accent3><a:srgbClr val="A5A5A5"/></a:accent3>
      <a:accent4><a:srgbClr val="FFC000"/></a:accent4>
      <a:accent5><a:srgbClr val="5B9BD5"/></a:accent5>
      <a:accent6><a:srgbClr val="70AD47"/></a:accent6>
      <a:hlink><a:srgbClr val="0563C1"/></a:hlink>
      <a:folHlink><a:srgbClr val="954F72"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="Test">
      <a:majorFont><a:latin typeface="Calibri Light"/></a:majorFont>
      <a:minorFont><a:latin typeface="Calibri"/></a:minorFont>
    </a:fontScheme>
    <a:fmtScheme name="Office">
      <a:fillStyleLst/><a:lnStyleLst/><a:effectStyleLst/><a:bgFillStyleLst/>
    </a:fmtScheme>
  </a:themeElements>
</a:theme>
""".encode("utf-8")

# Slide based on layout 2; title text split across two runs and a second
# paragraph, plus a body placeholder that must not influence the title.
SLIDE1_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld {_NS}>
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr/>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="2" name="Inhalt 1"/>
          <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
          <p:nvPr><p:ph idx="1"/></p:nvPr>
        </p:nvSpPr>
        <p:spPr/>
        <p:txBody><a:bodyPr/><a:lstStyle/>
          <a:p><a:r><a:rPr lang="de-DE"/><a:t>Inhaltstext</a:t></a:r></a:p>
        </p:txBody>
      </p:sp>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="3" name="Titel 2"/>
          <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
          <p:nvPr><p:ph type="title"/></p:nvPr>
        </p:nvSpPr>
        <p:spPr/>
        <p:txBody><a:bodyPr/><a:lstStyle/>
          <a:p>
            <a:r><a:rPr lang="de-DE"/><a:t>Hallo </a:t></a:r>
            <a:r><a:rPr lang="de-DE" b="1"/><a:t>Welt</a:t></a:r>
          </a:p>
          <a:p><a:r><a:rPr lang="de-DE"/><a:t>!</a:t></a:r></a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>
""".encode("utf-8")

SLIDE_NO_TITLE_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld {_NS}>
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr/>
      <p:sp>
        <p:nvSpPr>
          <p:cNvPr id="2" name="Inhalt 1"/><p:cNvSpPr/>
          <p:nvPr><p:ph type="body" idx="1"/></p:nvPr>
        </p:nvSpPr>
        <p:spPr/>
        <p:txBody><a:bodyPr/><a:lstStyle/>
          <a:p><a:r><a:rPr lang="de-DE"/><a:t>Nur Inhalt</a:t></a:r></a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>
""".encode("utf-8")

_EXPECTED_CLR_MAP = {
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
}


def build_template_package(
    *,
    presentation_xml: bytes = PRESENTATION_XML,
    slide_layout_rel: bool = True,
) -> Package:
    """Hand-build the complete in-memory test template package."""
    pkg = Package.create()
    pkg.rels(None).add(RT_OFFICE_DOCUMENT, "ppt/presentation.xml")

    pkg.add_part("/ppt/presentation.xml", CT_PRESENTATION, presentation_xml)
    pres_rels = pkg.rels("/ppt/presentation.xml")
    pres_rels.add(RT_SLIDE_MASTER, "slideMasters/slideMaster1.xml", rid="rId1")
    pres_rels.add(RT_SLIDE, "slides/slide1.xml", rid="rId2")

    pkg.add_part("/ppt/slideMasters/slideMaster1.xml", CT_SLIDE_MASTER, MASTER_XML)
    master_rels = pkg.rels("/ppt/slideMasters/slideMaster1.xml")
    master_rels.add(RT_SLIDE_LAYOUT, "../slideLayouts/slideLayout1.xml", rid="rId1")
    master_rels.add(RT_SLIDE_LAYOUT, "../slideLayouts/slideLayout2.xml", rid="rId2")
    master_rels.add(RT_THEME, "../theme/theme1.xml", rid="rId3")

    pkg.add_part("/ppt/slideLayouts/slideLayout1.xml", CT_SLIDE_LAYOUT, LAYOUT1_XML)
    pkg.rels("/ppt/slideLayouts/slideLayout1.xml").add(
        RT_SLIDE_MASTER, "../slideMasters/slideMaster1.xml"
    )
    pkg.add_part("/ppt/slideLayouts/slideLayout2.xml", CT_SLIDE_LAYOUT, LAYOUT2_XML)
    pkg.rels("/ppt/slideLayouts/slideLayout2.xml").add(
        RT_SLIDE_MASTER, "../slideMasters/slideMaster1.xml"
    )

    pkg.add_part("/ppt/theme/theme1.xml", CT_THEME, THEME_XML)

    pkg.add_part("/ppt/slides/slide1.xml", CT_SLIDE, SLIDE1_XML)
    if slide_layout_rel:
        pkg.rels("/ppt/slides/slide1.xml").add(
            RT_SLIDE_LAYOUT, "../slideLayouts/slideLayout2.xml"
        )
    return pkg


class TestTemplateParserFullParse(unittest.TestCase):
    """End-to-end parse of the hand-built template package."""

    @classmethod
    def setUpClass(cls):
        cls.info = TemplateParser(build_template_package()).parse()

    def test_returns_template_info(self):
        self.assertIsInstance(self.info, TemplateInfo)

    def test_slide_size_from_sldsz(self):
        self.assertEqual(self.info.slide_width, SLIDE_W_4_3)
        self.assertEqual(self.info.slide_height, SLIDE_H_4_3)

    def test_one_master_with_partname(self):
        self.assertEqual(len(self.info.masters), 1)
        master = self.info.masters[0]
        self.assertIsInstance(master, MasterSpec)
        self.assertEqual(master.partname, "/ppt/slideMasters/slideMaster1.xml")

    def test_master_clr_map(self):
        self.assertEqual(self.info.masters[0].clr_map, _EXPECTED_CLR_MAP)

    def test_master_placeholders(self):
        phs = self.info.masters[0].placeholders
        self.assertEqual(len(phs), 3)
        title, body, default = phs
        self.assertEqual(title.ph_type, "title")
        self.assertEqual(title.idx, 0)
        self.assertEqual(title.shape_id, 2)
        self.assertEqual(title.name, "Title Placeholder 1")
        self.assertEqual(title.box, Box(838200, 365125, 10515600, 1325563))
        self.assertEqual(body.ph_type, "body")
        self.assertEqual(body.idx, 1)
        self.assertEqual(body.box, Box(838200, 1825625, 10515600, 4351338))
        # attribute-less <p:ph/> defaults to ("body", 0) and has no box
        self.assertEqual(default.ph_type, "body")
        self.assertEqual(default.idx, 0)
        self.assertIsNone(default.box)

    def test_master_theme(self):
        theme = self.info.masters[0].theme
        self.assertEqual(theme.name, "TestTheme")
        self.assertEqual(theme.colors.accent1, "206EFB")
        self.assertEqual(theme.colors.dk1, "000000")
        self.assertEqual(theme.fonts.major_latin, "Calibri Light")
        self.assertEqual(theme.fonts.minor_latin, "Calibri")

    def test_layouts_in_master_order(self):
        layouts = self.info.layouts
        self.assertEqual(len(layouts), 2)
        self.assertEqual(layouts, self.info.masters[0].layouts)
        first, second = layouts
        self.assertIsInstance(first, LayoutSpec)
        self.assertEqual(first.partname, "/ppt/slideLayouts/slideLayout1.xml")
        self.assertEqual(first.name, "Titelfolie")
        self.assertEqual(first.ltype, "title")
        self.assertEqual(first.master_partname, "/ppt/slideMasters/slideMaster1.xml")
        self.assertEqual(second.partname, "/ppt/slideLayouts/slideLayout2.xml")
        self.assertEqual(second.name, "Titel und Inhalt")
        self.assertEqual(second.ltype, "obj")
        self.assertEqual(second.master_partname, "/ppt/slideMasters/slideMaster1.xml")

    def test_layout_placeholders(self):
        first, second = self.info.layouts
        self.assertEqual(
            [(ph.ph_type, ph.idx) for ph in first.placeholders],
            [("ctrTitle", 0), ("subTitle", 1)],
        )
        self.assertEqual(
            first.placeholders[0].box, Box(1524000, 1122363, 9144000, 2387600)
        )
        self.assertEqual(
            [(ph.ph_type, ph.idx) for ph in second.placeholders],
            [("title", 0), ("body", 1)],
        )
        self.assertIsNone(second.placeholders[0].box)  # no a:xfrm on the layout title
        self.assertEqual(
            second.placeholders[1].box, Box(838200, 1825625, 10515600, 4000000)
        )

    def test_slides(self):
        self.assertEqual(len(self.info.slides), 1)
        slide = self.info.slides[0]
        self.assertEqual(slide.partname, "/ppt/slides/slide1.xml")
        self.assertEqual(slide.layout_partname, "/ppt/slideLayouts/slideLayout2.xml")
        self.assertEqual(slide.title, "Hallo Welt!")

    def test_resolver_for_layout(self):
        layout = self.info.find_layout("Titel und Inhalt")
        resolver = self.info.resolver(layout)
        self.assertIsInstance(resolver, ColorResolver)
        self.assertEqual(resolver.rgb("accent1"), "206EFB")
        self.assertEqual(resolver.rgb("tx1"), "000000")  # tx1 -> dk1 via clrMap
        self.assertEqual(resolver.rgb("bg1"), "FFFFFF")  # bg1 -> lt1 via clrMap

    def test_resolver_unknown_master_raises(self):
        layout = self.info.layouts[0]
        orphan = LayoutSpec(
            partname=layout.partname,
            name=layout.name,
            ltype=layout.ltype,
            placeholders=layout.placeholders,
            element=layout.element,
            master_partname="/ppt/slideMasters/slideMaster99.xml",
        )
        with self.assertRaises(ParseError):
            self.info.resolver(orphan)

    def test_roundtrip_save_open_parse(self):
        """The package survives save -> open -> parse with identical results."""
        buf = io.BytesIO()
        build_template_package().save(buf)
        buf.seek(0)
        info = TemplateParser(Package.open(buf)).parse()
        self.assertEqual(info.slide_width, SLIDE_W_4_3)
        self.assertEqual(len(info.masters), 1)
        self.assertEqual(
            [(layout.name, layout.ltype) for layout in info.layouts],
            [("Titelfolie", "title"), ("Titel und Inhalt", "obj")],
        )
        self.assertEqual(info.slides[0].title, "Hallo Welt!")


class TestSlideSizeDefault(unittest.TestCase):
    """p:sldSz absent -> default 16:9 dimensions."""

    def test_default_slide_size(self):
        pkg = build_template_package(presentation_xml=PRESENTATION_XML_NO_SLDSZ)
        info = TemplateParser(pkg).parse()
        self.assertEqual(info.slide_width, SLIDE_W_16_9)
        self.assertEqual(info.slide_height, SLIDE_H_16_9)
        self.assertEqual((info.slide_width, info.slide_height), (12192000, 6858000))


class TestFindLayout(unittest.TestCase):
    """find_layout: int index, exact name, ltype, substring, error message."""

    @classmethod
    def setUpClass(cls):
        cls.info = TemplateParser(build_template_package()).parse()

    def test_by_int_index(self):
        self.assertEqual(self.info.find_layout(0).name, "Titelfolie")
        self.assertEqual(self.info.find_layout(1).name, "Titel und Inhalt")

    def test_by_int_out_of_range(self):
        with self.assertRaises(ParseError):
            self.info.find_layout(99)

    def test_by_exact_name_case_insensitive(self):
        self.assertEqual(self.info.find_layout("Titelfolie").ltype, "title")
        self.assertEqual(self.info.find_layout("TITELFOLIE").ltype, "title")
        self.assertEqual(self.info.find_layout("titel und inhalt").ltype, "obj")

    def test_exact_name_beats_substring(self):
        # "Titelfolie" is also a substring-style hit for "titel und inhalt";
        # exact name must win before any substring matching happens.
        self.assertEqual(
            self.info.find_layout("Titel und Inhalt").partname,
            "/ppt/slideLayouts/slideLayout2.xml",
        )

    def test_by_ltype(self):
        self.assertEqual(self.info.find_layout("obj").name, "Titel und Inhalt")
        self.assertEqual(self.info.find_layout("title").name, "Titelfolie")

    def test_by_name_substring(self):
        self.assertEqual(self.info.find_layout("inhalt").ltype, "obj")
        self.assertEqual(self.info.find_layout("folie").name, "Titelfolie")

    def test_miss_lists_available_layouts(self):
        with self.assertRaises(ParseError) as ctx:
            self.info.find_layout("gibtsnicht")
        message = str(ctx.exception)
        self.assertIn("Titelfolie", message)
        self.assertIn("title", message)
        self.assertIn("Titel und Inhalt", message)
        self.assertIn("obj", message)


class TestEffectiveBox(unittest.TestCase):
    """effective_box: layout (type, idx) match first, master type fallback."""

    @classmethod
    def setUpClass(cls):
        info = TemplateParser(build_template_package()).parse()
        cls.master = info.masters[0]
        cls.layout1, cls.layout2 = info.layouts

    def test_layout_box_wins(self):
        box = effective_box(self.layout2, self.master, "body", 1)
        self.assertEqual(box, Box(838200, 1825625, 10515600, 4000000))

    def test_layout_ctr_title_box(self):
        box = effective_box(self.layout1, self.master, "ctrTitle", 0)
        self.assertEqual(box, Box(1524000, 1122363, 9144000, 2387600))

    def test_fallback_to_master_when_layout_ph_has_no_box(self):
        # layout 2's title ph exists but carries no a:xfrm -> master title box
        box = effective_box(self.layout2, self.master, "title", 0)
        self.assertEqual(box, Box(838200, 365125, 10515600, 1325563))

    def test_fallback_to_master_by_type_when_idx_differs(self):
        # no (body, 5) on the layout -> first master body placeholder by type
        box = effective_box(self.layout2, self.master, "body", 5)
        self.assertEqual(box, Box(838200, 1825625, 10515600, 4351338))

    def test_ctr_title_falls_back_to_master_title(self):
        # layout 2 has no ctrTitle; title/ctrTitle match by type on the master
        box = effective_box(self.layout2, self.master, "ctrTitle", 0)
        self.assertEqual(box, Box(838200, 365125, 10515600, 1325563))

    def test_none_when_nothing_matches(self):
        self.assertIsNone(effective_box(self.layout2, self.master, "pic", 7))


class TestExtractPlaceholders(unittest.TestCase):
    """extract_placeholders on a hand-parsed shape tree."""

    def test_master_tree(self):
        root = parse_xml(MASTER_XML)
        sp_tree = find(root, "p:cSld/p:spTree")
        phs = extract_placeholders(sp_tree)
        # the plain "Decoration" shape (no p:ph) is ignored
        self.assertEqual(len(phs), 3)
        self.assertEqual(
            [(ph.ph_type, ph.idx, ph.shape_id) for ph in phs],
            [("title", 0, 2), ("body", 1, 3), ("body", 0, 4)],
        )
        self.assertEqual(phs[2].name, "Default Placeholder 3")
        self.assertIsNone(phs[2].box)
        self.assertEqual(phs[0].box, Box(838200, 365125, 10515600, 1325563))

    def test_empty_tree(self):
        root = parse_xml(SLIDE_NO_TITLE_XML)
        sp_tree = find(root, "p:cSld/p:spTree")
        phs = extract_placeholders(sp_tree)
        self.assertEqual([(ph.ph_type, ph.idx) for ph in phs], [("body", 1)])


class TestSlideTitleText(unittest.TestCase):
    """slide_title_text: concatenated runs of the first title placeholder."""

    def test_title_concatenates_all_runs(self):
        self.assertEqual(slide_title_text(parse_xml(SLIDE1_XML)), "Hallo Welt!")

    def test_no_title_returns_none(self):
        self.assertIsNone(slide_title_text(parse_xml(SLIDE_NO_TITLE_XML)))


class TestParserErrors(unittest.TestCase):
    """Structurally unusable packages raise ParseError."""

    def test_slide_without_layout_rel(self):
        pkg = build_template_package(slide_layout_rel=False)
        with self.assertRaises(ParseError) as ctx:
            TemplateParser(pkg).parse()
        self.assertIn("slide1.xml", str(ctx.exception))

    def test_main_part_not_a_presentation(self):
        pkg = Package.create()
        pkg.rels(None).add(RT_OFFICE_DOCUMENT, "ppt/presentation.xml")
        pkg.add_part("/ppt/presentation.xml", CT_PRESENTATION, MASTER_XML)
        with self.assertRaises(ParseError):
            TemplateParser(pkg).parse()

    def test_dangling_master_rid(self):
        broken = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f"<p:presentation {_NS}>"
            f'<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId99"/>'
            f"</p:sldMasterIdLst></p:presentation>"
        ).encode("utf-8")
        pkg = build_template_package(presentation_xml=broken)
        with self.assertRaises(ParseError) as ctx:
            TemplateParser(pkg).parse()
        self.assertIn("rId99", str(ctx.exception))

    def test_no_masters_declared(self):
        empty = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f"<p:presentation {_NS}><p:sldMasterIdLst/></p:presentation>"
        ).encode("utf-8")
        pkg = build_template_package(presentation_xml=empty)
        with self.assertRaises(ParseError):
            TemplateParser(pkg).parse()


if __name__ == "__main__":
    unittest.main()
