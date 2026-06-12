"""Tests for deckforge.emu."""

from __future__ import annotations

import unittest

from deckforge.emu import (
    EMU_PER_CM,
    EMU_PER_INCH,
    EMU_PER_PT,
    SLIDE_H_16_9,
    SLIDE_W_16_9,
    Box,
    cm,
    emu_to_pt,
    hundredths_pt,
    inches,
    pt,
)


class TestConstants(unittest.TestCase):
    def test_unit_constants(self):
        self.assertEqual(EMU_PER_INCH, 914400)
        self.assertEqual(EMU_PER_CM, 360000)
        self.assertEqual(EMU_PER_PT, 12700)

    def test_slide_size_16_9(self):
        self.assertEqual(SLIDE_W_16_9, 12192000)
        self.assertEqual(SLIDE_H_16_9, 6858000)
        # 16:9 sanity check
        self.assertEqual(SLIDE_W_16_9 * 9, SLIDE_H_16_9 * 16)


class TestConversions(unittest.TestCase):
    def test_inches(self):
        self.assertEqual(inches(1), 914400)
        self.assertEqual(inches(0.5), 457200)
        self.assertIsInstance(inches(1.5), int)

    def test_cm(self):
        self.assertEqual(cm(1), 360000)
        self.assertEqual(cm(2.54), inches(1))
        self.assertEqual(cm(1.2), 432000)

    def test_pt(self):
        self.assertEqual(pt(1), 12700)
        self.assertEqual(pt(18), 228600)
        self.assertEqual(pt(0.75), 9525)

    def test_rounding(self):
        # 1/3 cm = 120000 EMU exactly; odd fractions round to nearest int
        self.assertEqual(cm(1 / 3), 120000)
        self.assertEqual(pt(0.1), 1270)
        self.assertEqual(inches(0.0000005), 0)  # rounds down to 0

    def test_emu_to_pt(self):
        self.assertEqual(emu_to_pt(12700), 1.0)
        self.assertEqual(emu_to_pt(228600), 18.0)
        self.assertAlmostEqual(emu_to_pt(pt(10.5)), 10.5)

    def test_hundredths_pt(self):
        self.assertEqual(hundredths_pt(18), 1800)
        self.assertEqual(hundredths_pt(10.5), 1050)
        self.assertEqual(hundredths_pt(11.25), 1125)
        self.assertIsInstance(hundredths_pt(18.0), int)


class TestBox(unittest.TestCase):
    def test_fields_and_tuple_behavior(self):
        b = Box(10, 20, 300, 400)
        self.assertEqual(b.x, 10)
        self.assertEqual(b.y, 20)
        self.assertEqual(b.w, 300)
        self.assertEqual(b.h, 400)
        x, y, w, h = b
        self.assertEqual((x, y, w, h), (10, 20, 300, 400))

    def test_inset(self):
        b = Box(100, 200, 1000, 800)
        inner = b.inset(50, 25)
        self.assertEqual(inner, Box(150, 225, 900, 750))
        self.assertIsInstance(inner, Box)
        # original untouched
        self.assertEqual(b, Box(100, 200, 1000, 800))

    def test_inset_negative_grows(self):
        b = Box(100, 100, 100, 100)
        self.assertEqual(b.inset(-10, -20), Box(90, 80, 120, 140))


if __name__ == "__main__":
    unittest.main()
