# Slide Writing

Slide Writing is a self-built, zero-dependency PowerPoint engine for automated
consulting-deck creation. It reads `.pptx` templates as Office Open XML
packages, extracts their design model, and writes new slides that reuse the
original masters, layouts, theme colors, fonts, and placeholders.

The goal is simple: turn structured content into editable, CI-consistent
PowerPoint slides without `python-pptx`, without `pip install`, and without
opening PowerPoint.

## What It Can Do

- Parse PPTX packages, relationships, content types, themes, slide masters,
  layouts, placeholders, and existing slide metadata.
- Create new slides against existing layouts so backgrounds, logos,
  placeholders, fonts, and colors are inherited from the source template.
- Build native editable PowerPoint content: textboxes, shapes, lines, images,
  and formatted tables.
- Render consulting components from code: agenda, KPI tiles, Harvey balls,
  waterfall charts, bar charts, timelines, comparison matrices, traffic lights,
  callouts, and section numbers.
- Generate complete decks from a declarative JSON spec.
- Run entirely on the Python standard library.

## PDF Import (Web Tool)

The browser tool (`docs/index.html`) accepts **PDF uploads** in addition to
`.pptx`. Each PDF page is analysed client-side with a vendored copy of
[pdf.js](https://mozilla.github.io/pdf.js/) (`docs/vendor/`, no server, no API)
and **rebuilt into native, editable PowerPoint slides** — then shown in the same
preview and exported as `.pptx` exactly like an uploaded deck:

- **Text** → native editable text boxes (position + font size).
- **Vectors** → native shapes (`prstGeom` rectangles, `custGeom` freeform paths).
- **Tables** → native PowerPoint tables (`a:tbl`), reconstructed from the page's
  ruling lines and cell text.
- **Charts** → real, editable chart objects (`c:barChart` / `c:lineChart`) with a
  reconstructed category/value data table (bar height ↔ axis-tick scale).
- **Images** → embedded pictures; any page that can't be safely reconstructed
  falls back to a full-page raster image so fidelity is never lost.

The PDF is synthesised into the same in-memory OOXML package an uploaded `.pptx`
produces, so analysis, SVG preview, and `.pptx` export all reuse the existing
pipeline.

## Repository Status

This is a V1 engineering baseline:

- `slidewriting/` contains the PPTX parser, model, builder, writer, component
  library, JSON spec renderer, and CLI.
- `tests/` contains unit and end-to-end tests using `unittest`.
- `examples/consulting_deck.json` is a ready-to-run consulting demo spec.
- `docs/ZIELBILD.md` describes the product vision in German.
- `ARCHITECTURE.md` documents the internal module contracts and OOXML rules.

## Quick Start

Run the package directly from the repository root:

```bash
python3 -m slidewriting bootstrap --out out/template.pptx
python3 -m slidewriting inspect out/template.pptx
python3 -m slidewriting validate examples/consulting_deck.json
python3 -m slidewriting demo --out out/showcase.pptx
python3 -m slidewriting generate --spec examples/consulting_deck.json --out out/demo.pptx
```

After installation, use the branded CLI command:

```bash
slide-writing generate --spec examples/consulting_deck.json --out out/demo.pptx
```

Use an existing corporate PowerPoint master as the design source:

```bash
python3 -m slidewriting generate \
  --template path/to/company-master.pptx \
  --spec examples/consulting_deck.json \
  --out out/company-demo.pptx
```

## Python API

```python
from slidewriting import Deck, build_from_spec

deck = Deck.create(accent="206EFB")
slide = deck.add_slide("obj")
slide.title("Market analysis 2026")
slide.placeholder("body").bullets([
    "Demand is shifting toward automated delivery.",
    {"text": "Template fidelity remains non-negotiable.", "level": 1},
])
deck.save("out/manual-api-demo.pptx")

spec_deck = build_from_spec({
    "title": "Generated strategy deck",
    "slides": [
        {"type": "title", "title": "Strategy 2026"},
        {"type": "agenda", "items": ["Context", "Options", "Roadmap"]},
    ],
})
spec_deck.save("out/spec-demo.pptx")
```

The consulting components are also available as an explicit module API:

```python
from slidewriting.components import add_agenda, add_kpi_row, add_waterfall
```

## JSON Spec Slide Types

Slide Writing currently supports:

- `title`
- `section`
- `bullets`
- `agenda`
- `kpi`
- `table`
- `waterfall`
- `bars`
- `timeline`
- `comparison`
- `blank`

Unknown JSON keys are ignored for forward compatibility. Invalid required
fields are reported with slide indexes by `slide-writing validate`.

## Design Principles

- Standard library only.
- Native OOXML package reading and writing.
- Theme-first output: generated content uses PowerPoint theme slots wherever
  possible.
- Editable output: components are built from native shapes and text, not image
  screenshots.
- Deterministic output for reliable testing and reproducible automation.

## Test

```bash
python3 -m unittest discover -s tests -v
```

## Important Limitations

- V1 reads templates and appends new slides; it does not edit existing slide
  content in place.
- Shape-based charts are implemented; native PowerPoint chart parts are a
  planned later extension.
- Visual rendering is delegated to PowerPoint or compatible office software.
