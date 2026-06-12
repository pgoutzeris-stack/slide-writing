from __future__ import annotations

import os
import tempfile
import unittest

from deckforge import Deck, build_from_spec


class TestEndToEnd(unittest.TestCase):
    def test_generate_demo_deck_and_reopen(self) -> None:
        spec = {
            "accent": "206EFB",
            "title": "E2E Consulting Deck",
            "author": "DeckForge Tests",
            "slides": [
                {
                    "type": "title",
                    "title": "Automation Strategy",
                    "subtitle": "Self-built PPTX generation",
                },
                {
                    "type": "agenda",
                    "items": ["Context", "Evidence", "Roadmap"],
                    "active": 1,
                },
                {
                    "type": "bullets",
                    "title": "Key messages",
                    "bullets": [
                        "Parse the template.",
                        {"text": "Reuse placeholders and theme colors.", "level": 1},
                        "Write a valid package.",
                    ],
                    "callout": {"kind": "key", "text": "Everything is editable."},
                },
                {
                    "type": "kpi",
                    "title": "Impact",
                    "kpis": [
                        {"value": "0", "label": "dependencies"},
                        {"value": "8", "label": "slide types"},
                        {"value": "+42%", "label": "speed"},
                    ],
                },
                {
                    "type": "waterfall",
                    "title": "Bridge",
                    "items": [
                        {"label": "Base", "value": 100},
                        {"label": "Automation", "value": -30},
                        {"label": "Reuse", "value": -20},
                    ],
                },
                {
                    "type": "bars",
                    "title": "Maturity",
                    "categories": ["Parse", "Build", "Scale"],
                    "values": [80, 65, 45],
                },
                {
                    "type": "timeline",
                    "title": "Roadmap",
                    "phases": [
                        {"label": "V1", "sub": "Engine", "active": True},
                        {"label": "V2", "sub": "Charts"},
                        {"label": "V3", "sub": "Pipelines"},
                    ],
                },
                {
                    "type": "comparison",
                    "title": "Decision",
                    "options": ["Manual", "DeckForge"],
                    "criteria": ["Fidelity", "Speed"],
                    "cells": [[0.5, 1], [0.25, 1]],
                },
                {
                    "type": "table",
                    "title": "Backlog",
                    "columns": ["Workstream", "Owner", {"label": "Score", "align": "r"}],
                    "rows": [["Parser", "Core", 100], ["Builder", "Core", 90]],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "deckforge-e2e.pptx")
            deck = build_from_spec(spec)
            deck.save(out)

            reopened = Deck.open(out)
            info = reopened.inspect()

        self.assertEqual(len(info["slides"]), len(spec["slides"]))
        self.assertEqual(info["theme"]["colors"]["accent1"], "206EFB")
        self.assertEqual(info["slides"][0]["title"], "Automation Strategy")


if __name__ == "__main__":
    unittest.main()
