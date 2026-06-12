from __future__ import annotations

import os
import tempfile
import unittest

from slidewriting import Box, Deck

PNG_100x50 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00d\x00\x00\x002"
    b"\x08\x02\x00\x00\x00"
    b"\x00\x00\x00\x00"
)


class TestAnalysis(unittest.TestCase):
    def test_analyze_reports_text_image_and_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "analysis.pptx")
            deck = Deck.create()
            slide = deck.add_slide()
            slide.title("Analysis title")
            slide.placeholder("body").bullets(["First point", "Second point"])
            slide.add_picture(PNG_100x50, Box(0, 0, 1_000_000, 600_000))
            slide.add_table(
                Box(0, 700_000, 3_000_000, 1_000_000),
                ["Column A", "Column B"],
                [["Alpha", "Beta"]],
            )
            deck.save(path)

            reopened = Deck.open(path)
            analysis = reopened.analyze()

        self.assertEqual(analysis["summary"]["slides"], 1)
        self.assertEqual(analysis["totals"]["images"], 1)
        self.assertEqual(analysis["totals"]["tables"], 1)
        slide_info = analysis["slides"][0]
        self.assertIn("Analysis title", slide_info["text"])
        self.assertEqual(slide_info["counts"]["images"], 1)
        self.assertEqual(slide_info["counts"]["tables"], 1)
        self.assertTrue(any(item["kind"] == "image" for item in slide_info["shapes"]))
        self.assertTrue(any(item["kind"] == "table" for item in slide_info["shapes"]))


if __name__ == "__main__":
    unittest.main()
