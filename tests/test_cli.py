from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest

from deckforge import Deck
from deckforge.cli import main


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


class TestCli(unittest.TestCase):
    def test_validate_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = os.path.join(tmp, "spec.json")
            with open(spec_path, "w", encoding="utf-8") as handle:
                json.dump({"slides": [{"type": "title", "title": "Hello"}]}, handle)

            code, stdout, stderr = _run_cli(["validate", spec_path])

        self.assertEqual(code, 0)
        self.assertEqual(stdout.strip(), "OK")
        self.assertEqual(stderr, "")

    def test_validate_bad_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = os.path.join(tmp, "spec.json")
            with open(spec_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "slides": [
                            {
                                "type": "bars",
                                "title": "Bad",
                                "categories": ["A"],
                                "values": [-1],
                            }
                        ]
                    },
                    handle,
                )

            code, stdout, stderr = _run_cli(["validate", spec_path])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("darf nicht negativ", stderr)

    def test_bootstrap_generate_and_inspect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            template = os.path.join(tmp, "template.pptx")
            generated = os.path.join(tmp, "generated.pptx")
            spec_path = os.path.join(tmp, "spec.json")
            with open(spec_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "title": "CLI Deck",
                        "slides": [
                            {"type": "title", "title": "CLI Title"},
                            {"type": "agenda", "items": ["One", "Two"]},
                        ],
                    },
                    handle,
                )

            code, stdout, stderr = _run_cli(["bootstrap", "--out", template])
            self.assertEqual((code, stderr), (0, ""))
            self.assertTrue(os.path.exists(stdout.strip()))

            code, stdout, stderr = _run_cli(
                [
                    "generate",
                    "--template",
                    template,
                    "--spec",
                    spec_path,
                    "--out",
                    generated,
                ]
            )
            self.assertEqual((code, stderr), (0, ""))
            self.assertTrue(os.path.exists(stdout.strip()))

            code, stdout, stderr = _run_cli(["inspect", generated, "--compact"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        info = json.loads(stdout)
        self.assertEqual(len(info["slides"]), 2)
        self.assertEqual(info["slides"][0]["title"], "CLI Title")

    def test_app_properties_slide_count_is_updated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deck.pptx")
            deck = Deck.create()
            deck.add_slide("title").title("One")
            deck.add_slide("title").title("Two")
            deck.title = "App Props Deck"
            deck.save(path)

            reopened = Deck.open(path)
            app_blob = reopened.package.part("/docProps/app.xml").blob.decode("utf-8")

        self.assertIn("<ep:Slides>2</ep:Slides>", app_blob)
        self.assertIn("<vt:lpstr>App Props Deck</vt:lpstr>", app_blob)


if __name__ == "__main__":
    unittest.main()
