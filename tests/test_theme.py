"""Tests for deckforge.theme."""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from deckforge.errors import BuildError, ParseError
from deckforge.theme import (
    SCHEME_SLOTS,
    ColorResolver,
    ColorScheme,
    FontScheme,
    Theme,
    color_el,
    fill_for,
    parse_theme,
    scheme_fill,
    srgb_fill,
)
from deckforge.xmlcore import find, get, qn, serialize

#: Realistic hand-written theme part: two a:sysClr slots (dk1/lt1, like every
#: Office theme), lowercase hex in dk2 (must be normalized), extra fontScheme
#: children (a:ea/a:cs) and an a:fmtScheme stub that parsing must tolerate.
THEME_XML = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="ROOTS">
  <a:themeElements>
    <a:clrScheme name="ROOTS">
      <a:dk1><a:sysClr val="windowText" lastClr="0B0B0B"/></a:dk1>
      <a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="1f3864"/></a:dk2>
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
    <a:fontScheme name="ROOTS">
      <a:majorFont>
        <a:latin typeface="Circular Std"/>
        <a:ea typeface=""/>
        <a:cs typeface=""/>
      </a:majorFont>
      <a:minorFont>
        <a:latin typeface="Circular Std Book"/>
        <a:ea typeface=""/>
        <a:cs typeface=""/>
      </a:minorFont>
    </a:fontScheme>
    <a:fmtScheme name="Office">
      <a:fillStyleLst>
        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
      </a:fillStyleLst>
      <a:lnStyleLst>
        <a:ln><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
        <a:ln><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
        <a:ln><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
      </a:lnStyleLst>
      <a:effectStyleLst>
        <a:effectStyle><a:effectLst/></a:effectStyle>
        <a:effectStyle><a:effectLst/></a:effectStyle>
        <a:effectStyle><a:effectLst/></a:effectStyle>
      </a:effectStyleLst>
      <a:bgFillStyleLst>
        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
      </a:bgFillStyleLst>
    </a:fmtScheme>
  </a:themeElements>
</a:theme>
"""

#: A typical master color map (logical name -> theme slot).
CLR_MAP = {
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


def _theme_with(replacement_pairs):
    """Return THEME_XML with literal byte replacements applied."""
    blob = THEME_XML
    for old, new in replacement_pairs:
        blob = blob.replace(old, new)
    return blob


class TestParseTheme(unittest.TestCase):
    def setUp(self):
        self.theme = parse_theme(THEME_XML)

    def test_name(self):
        self.assertEqual(self.theme.name, "ROOTS")

    def test_sysclr_uses_lastclr(self):
        self.assertEqual(self.theme.colors.dk1, "0B0B0B")
        self.assertEqual(self.theme.colors.lt1, "FFFFFF")

    def test_srgb_values_normalized_uppercase(self):
        self.assertEqual(self.theme.colors.dk2, "1F3864")

    def test_all_slots_parsed(self):
        expected = {
            "lt2": "E7E6E6",
            "accent1": "206EFB",
            "accent2": "ED7D31",
            "accent3": "A5A5A5",
            "accent4": "FFC000",
            "accent5": "5B9BD5",
            "accent6": "70AD47",
            "hlink": "0563C1",
            "folHlink": "954F72",
        }
        for slot, rgb in expected.items():
            self.assertEqual(self.theme.colors.get(slot), rgb)

    def test_fonts(self):
        self.assertEqual(self.theme.fonts.major_latin, "Circular Std")
        self.assertEqual(self.theme.fonts.minor_latin, "Circular Std Book")

    def test_element_is_parsed_root(self):
        self.assertIsInstance(self.theme.element, ET.Element)
        self.assertEqual(self.theme.element.tag, qn("a:theme"))
        self.assertIsNotNone(
            find(self.theme.element, "a:themeElements/a:fmtScheme")
        )

    def test_dataclass_types(self):
        self.assertIsInstance(self.theme, Theme)
        self.assertIsInstance(self.theme.colors, ColorScheme)
        self.assertIsInstance(self.theme.fonts, FontScheme)

    def test_sysclr_fallback_windowtext(self):
        blob = _theme_with(
            [(b'<a:sysClr val="windowText" lastClr="0B0B0B"/>',
              b'<a:sysClr val="windowText"/>')]
        )
        self.assertEqual(parse_theme(blob).colors.dk1, "000000")

    def test_sysclr_fallback_window(self):
        blob = _theme_with(
            [(b'<a:sysClr val="window" lastClr="FFFFFF"/>',
              b'<a:sysClr val="window"/>')]
        )
        self.assertEqual(parse_theme(blob).colors.lt1, "FFFFFF")

    def test_sysclr_unknown_without_lastclr_raises(self):
        blob = _theme_with(
            [(b'<a:sysClr val="windowText" lastClr="0B0B0B"/>',
              b'<a:sysClr val="highlightText"/>')]
        )
        with self.assertRaises(ParseError):
            parse_theme(blob)

    def test_missing_slot_raises(self):
        blob = _theme_with(
            [(b"<a:accent3><a:srgbClr val=\"A5A5A5\"/></a:accent3>", b"")]
        )
        with self.assertRaisesRegex(ParseError, "accent3"):
            parse_theme(blob)

    def test_unsupported_color_definition_raises(self):
        blob = _theme_with(
            [(b'<a:srgbClr val="206EFB"/>',
              b'<a:scrgbClr r="50000" g="50000" b="50000"/>')]
        )
        with self.assertRaisesRegex(ParseError, "accent1"):
            parse_theme(blob)

    def test_invalid_hex_in_slot_raises(self):
        blob = _theme_with(
            [(b'<a:srgbClr val="206EFB"/>', b'<a:srgbClr val="20FBX"/>')]
        )
        with self.assertRaises(ParseError):
            parse_theme(blob)

    def test_missing_clrscheme_raises(self):
        blob = (
            b'<a:theme xmlns:a="http://schemas.openxmlformats.org/'
            b'drawingml/2006/main" name="X"><a:themeElements/></a:theme>'
        )
        with self.assertRaises(ParseError):
            parse_theme(blob)

    def test_missing_fontscheme_raises(self):
        blob = _theme_with([(b'<a:latin typeface="Circular Std"/>', b"")])
        with self.assertRaisesRegex(ParseError, "majorFont"):
            parse_theme(blob)

    def test_malformed_xml_raises(self):
        with self.assertRaises(ParseError):
            parse_theme(b"<a:theme")


class TestColorScheme(unittest.TestCase):
    def test_get_every_slot(self):
        theme = parse_theme(THEME_XML)
        for slot in SCHEME_SLOTS:
            value = theme.colors.get(slot)
            self.assertRegex(value, r"^[0-9A-F]{6}$")

    def test_get_unknown_slot_raises(self):
        theme = parse_theme(THEME_XML)
        with self.assertRaisesRegex(ParseError, "tx9"):
            theme.colors.get("tx9")


class TestColorResolver(unittest.TestCase):
    def setUp(self):
        self.resolver = ColorResolver(parse_theme(THEME_XML), CLR_MAP)

    def test_theme_slots_direct(self):
        self.assertEqual(self.resolver.rgb("accent1"), "206EFB")
        self.assertEqual(self.resolver.rgb("dk1"), "0B0B0B")
        self.assertEqual(self.resolver.rgb("folHlink"), "954F72")

    def test_logical_names_via_clr_map(self):
        self.assertEqual(self.resolver.rgb("tx1"), "0B0B0B")
        self.assertEqual(self.resolver.rgb("bg1"), "FFFFFF")
        self.assertEqual(self.resolver.rgb("tx2"), "1F3864")
        self.assertEqual(self.resolver.rgb("bg2"), "E7E6E6")

    def test_swapped_clr_map_is_honored(self):
        swapped = dict(CLR_MAP, tx1="lt1", bg1="dk1")
        resolver = ColorResolver(parse_theme(THEME_XML), swapped)
        self.assertEqual(resolver.rgb("tx1"), "FFFFFF")
        self.assertEqual(resolver.rgb("bg1"), "0B0B0B")

    def test_hex_literals_normalized(self):
        self.assertEqual(self.resolver.rgb("a1b2c3"), "A1B2C3")
        self.assertEqual(self.resolver.rgb("#ff0000"), "FF0000")
        self.assertEqual(self.resolver.rgb("206EFB"), "206EFB")

    def test_unknown_name_raises_naming_input(self):
        with self.assertRaisesRegex(ParseError, "chartreuse"):
            self.resolver.rgb("chartreuse")

    def test_short_hex_rejected(self):
        with self.assertRaises(ParseError):
            self.resolver.rgb("#FFF")

    def test_clr_map_is_copied(self):
        clr_map = dict(CLR_MAP)
        resolver = ColorResolver(parse_theme(THEME_XML), clr_map)
        clr_map["tx1"] = "lt1"
        self.assertEqual(resolver.rgb("tx1"), "0B0B0B")


class TestColorEl(unittest.TestCase):
    def test_scheme_slot(self):
        node = color_el("accent1")
        self.assertEqual(node.tag, qn("a:schemeClr"))
        self.assertEqual(node.get("val"), "accent1")

    def test_logical_name(self):
        node = color_el("tx1")
        self.assertEqual(node.tag, qn("a:schemeClr"))
        self.assertEqual(node.get("val"), "tx1")

    def test_hex_literal(self):
        node = color_el("206EFB")
        self.assertEqual(node.tag, qn("a:srgbClr"))
        self.assertEqual(node.get("val"), "206EFB")

    def test_hash_hex_normalized(self):
        node = color_el("#a1b2c3")
        self.assertEqual(node.tag, qn("a:srgbClr"))
        self.assertEqual(node.get("val"), "A1B2C3")

    def test_unknown_raises_naming_input(self):
        with self.assertRaisesRegex(ParseError, "mauve"):
            color_el("mauve")


class TestFillFactories(unittest.TestCase):
    def test_srgb_fill_structure(self):
        fill = srgb_fill("#1f3864")
        self.assertEqual(fill.tag, qn("a:solidFill"))
        child = find(fill, "a:srgbClr")
        self.assertIsNotNone(child)
        self.assertEqual(child.get("val"), "1F3864")
        self.assertEqual(len(fill), 1)

    def test_srgb_fill_invalid_raises(self):
        with self.assertRaises(ParseError):
            srgb_fill("accent1")

    def test_scheme_fill_structure(self):
        fill = scheme_fill("accent2")
        self.assertEqual(fill.tag, qn("a:solidFill"))
        child = find(fill, "a:schemeClr")
        self.assertIsNotNone(child)
        self.assertEqual(child.get("val"), "accent2")

    def test_scheme_fill_accepts_logical_name(self):
        child = find(scheme_fill("bg2"), "a:schemeClr")
        self.assertEqual(child.get("val"), "bg2")

    def test_scheme_fill_unknown_raises(self):
        with self.assertRaisesRegex(ParseError, "accentX"):
            scheme_fill("accentX")

    def test_fill_for_scheme_without_alpha(self):
        fill = fill_for("accent1")
        self.assertEqual(fill.tag, qn("a:solidFill"))
        clr = find(fill, "a:schemeClr")
        self.assertEqual(clr.get("val"), "accent1")
        self.assertEqual(len(clr), 0)

    def test_fill_for_hex(self):
        fill = fill_for("#206efb")
        clr = find(fill, "a:srgbClr")
        self.assertEqual(clr.get("val"), "206EFB")

    def test_fill_for_alpha_inside_color_element(self):
        fill = fill_for("accent1", alpha_pct=60)
        clr = find(fill, "a:schemeClr")
        alpha = find(clr, "a:alpha")
        self.assertIsNotNone(alpha)
        self.assertEqual(alpha.get("val"), "60000")

    def test_fill_for_alpha_bounds(self):
        self.assertEqual(
            get(find(fill_for("tx1", alpha_pct=0), "a:schemeClr/a:alpha"), "val"),
            "0",
        )
        self.assertEqual(
            get(find(fill_for("tx1", alpha_pct=100), "a:schemeClr/a:alpha"), "val"),
            "100000",
        )

    def test_fill_for_alpha_out_of_range_raises(self):
        with self.assertRaises(BuildError):
            fill_for("accent1", alpha_pct=101)
        with self.assertRaises(BuildError):
            fill_for("accent1", alpha_pct=-1)

    def test_fill_for_unknown_color_raises(self):
        with self.assertRaisesRegex(ParseError, "nope"):
            fill_for("nope")

    def test_serialized_output_uses_canonical_prefixes(self):
        blob = serialize(fill_for("accent1", alpha_pct=50))
        self.assertIn(b'<a:solidFill', blob)
        self.assertIn(b'<a:schemeClr val="accent1">', blob)
        self.assertIn(b'<a:alpha val="50000"', blob)


if __name__ == "__main__":
    unittest.main()
