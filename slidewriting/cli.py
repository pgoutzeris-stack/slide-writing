"""Command-line interface for Slide Writing.

The CLI intentionally stays thin: it loads JSON, delegates all PowerPoint
logic to :mod:`slidewriting.api` / :mod:`slidewriting.spec`, and prints machine
readable JSON where that is useful for automation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from . import __version__
from .api import Deck
from .errors import SlideWritingError, SpecError
from .spec import build_from_spec, validate_spec

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Run the Slide Writing CLI and return a process exit code."""
    parser = _parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        return 2
    try:
        return int(args.func(args))
    except (SlideWritingError, OSError, json.JSONDecodeError) as exc:
        print(f"slide-writing: error: {exc}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    """Create the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="slide-writing",
        description=(
            "Zero-dependency PPTX parser and generator for consulting-style decks."
        ),
    )
    parser.add_argument("--version", action="version", version=f"Slide Writing {__version__}")
    sub = parser.add_subparsers(dest="command")

    inspect = sub.add_parser("inspect", help="Inspect a PPTX template/deck as JSON")
    inspect.add_argument("pptx", help="Path to the .pptx file")
    inspect.add_argument(
        "--json",
        action="store_true",
        help="Compatibility alias for pretty-printed JSON output",
    )
    inspect.add_argument(
        "--compact", action="store_true", help="Print compact JSON instead of pretty JSON"
    )
    inspect.set_defaults(func=_cmd_inspect)

    validate = sub.add_parser("validate", help="Validate a deck JSON specification")
    validate.add_argument("spec", help="Path to the JSON spec")
    validate.set_defaults(func=_cmd_validate)

    generate = sub.add_parser("generate", help="Generate a PPTX from a JSON spec")
    generate.add_argument("--spec", required=True, help="Path to the JSON spec")
    generate.add_argument("--out", required=True, help="Output .pptx path")
    generate.add_argument(
        "--template",
        help="Optional template override; wins over the spec's template field",
    )
    generate.set_defaults(func=_cmd_generate)

    demo = sub.add_parser("demo", help="Generate the built-in consulting showcase deck")
    demo.add_argument("--out", required=True, help="Output .pptx path")
    demo.add_argument("--accent", default="206EFB", help="Theme accent1 hex color")
    demo.set_defaults(func=_cmd_demo)

    bootstrap = sub.add_parser("bootstrap", help="Create a clean default PPTX template")
    bootstrap.add_argument("--out", required=True, help="Output .pptx path")
    bootstrap.add_argument("--accent", default="206EFB", help="Theme accent1 hex color")
    bootstrap.add_argument("--name", default="Slide Writing", help="Theme/template name")
    bootstrap.add_argument("--major-font", default="Aptos Display", help="Major font")
    bootstrap.add_argument("--minor-font", default="Aptos", help="Minor font")
    bootstrap.set_defaults(func=_cmd_bootstrap)

    return parser


def _load_json(path: str) -> dict[str, Any]:
    """Load a JSON object from ``path``."""
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise SpecError("Spec root must be a JSON object")
    return value


def _ensure_parent(path: str) -> None:
    """Create the output directory for ``path`` when one is present."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def _print_json(value: Any, *, compact: bool = False) -> None:
    """Print ``value`` as UTF-8 friendly JSON."""
    if compact:
        print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2))


def _cmd_inspect(args: argparse.Namespace) -> int:
    """Handle ``slide-writing inspect``."""
    deck = Deck.open(args.pptx)
    _print_json(deck.inspect(), compact=bool(args.compact))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    """Handle ``slide-writing validate``."""
    spec = _load_json(args.spec)
    problems = validate_spec(spec)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print("OK")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    """Handle ``slide-writing generate``."""
    spec = _load_json(args.spec)
    deck = build_from_spec(spec, template_path=args.template)
    _ensure_parent(args.out)
    deck.save(args.out)
    print(args.out)
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    """Handle ``slide-writing demo``."""
    spec = dict(_DEMO_SPEC)
    spec["accent"] = args.accent
    deck = build_from_spec(spec)
    _ensure_parent(args.out)
    deck.save(args.out)
    print(args.out)
    return 0


def _cmd_bootstrap(args: argparse.Namespace) -> int:
    """Handle ``slide-writing bootstrap``."""
    deck = Deck.create(
        accent=args.accent,
        name=args.name,
        major_font=args.major_font,
        minor_font=args.minor_font,
    )
    _ensure_parent(args.out)
    deck.save(args.out)
    print(args.out)
    return 0


_DEMO_SPEC: dict[str, Any] = {
    "title": "Slide Writing Consulting Demo",
    "author": "ROOTS Brand Strategy Consultants GmbH",
    "slides": [
        {
            "type": "title",
            "title": "Market Automation Strategy",
            "subtitle": "Generated from JSON with a self-built PPTX engine",
        },
        {
            "type": "agenda",
            "title": "Agenda",
            "active": 1,
            "items": ["Executive summary", "Market evidence", "Operating model", "Roadmap"],
        },
        {
            "type": "bullets",
            "title": "Executive summary",
            "bullets": [
                "Template design is parsed from the PPTX package.",
                {"text": "New slides reuse the original master layouts.", "level": 1},
                "Consulting components are native editable PowerPoint shapes.",
            ],
            "callout": {"kind": "key", "text": "The output remains a real .pptx file."},
        },
        {
            "type": "kpi",
            "title": "KPI snapshot",
            "kpis": [
                {"value": "42%", "label": "manual effort removed", "delta": "+18pp"},
                {"value": "0", "label": "runtime dependencies"},
                {"value": "<1s", "label": "demo deck build time", "delta": "+fast"},
            ],
        },
        {
            "type": "bars",
            "title": "Maturity by workstream",
            "categories": ["Parser", "Builder", "Components", "Spec"],
            "values": [90, 85, 75, 80],
        },
        {
            "type": "waterfall",
            "title": "Efficiency bridge",
            "total_label": "Target",
            "items": [
                {"label": "Today", "value": 100},
                {"label": "Template parsing", "value": -25},
                {"label": "Spec rendering", "value": -20},
                {"label": "Component reuse", "value": -15},
            ],
        },
        {
            "type": "timeline",
            "title": "Automation roadmap",
            "phases": [
                {"label": "Parse", "sub": "Template model", "active": True},
                {"label": "Compose", "sub": "Slide spec"},
                {"label": "Generate", "sub": "PPTX package"},
                {"label": "Scale", "sub": "Content pipeline"},
            ],
        },
        {
            "type": "comparison",
            "title": "Option assessment",
            "options": ["Manual build", "Generic library", "Slide Writing"],
            "criteria": ["Design fidelity", "Automation depth", "Control"],
            "cells": [[0.5, 0.75, 1], [0.25, 0.5, 1], [0.25, 0.5, 1]],
        },
        {
            "type": "table",
            "title": "Implementation backlog",
            "columns": [
                {"label": "Module", "width": 1.2},
                {"label": "Scope", "width": 2.0},
                {"label": "Status", "align": "ctr"},
            ],
            "rows": [
                ["Parser", "Theme, masters, layouts, slides", "Done"],
                ["Builder", "Shapes, text, tables, images", "Done"],
                ["Spec", "Declarative consulting deck rendering", "Done"],
            ],
        },
    ],
}


if __name__ == "__main__":  # pragma: no cover - exercised via __main__.py
    raise SystemExit(main())
