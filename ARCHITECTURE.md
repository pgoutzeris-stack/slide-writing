# Slide Writing — Architecture & Module Contracts

This document is the **single source of truth** for all implementers. Code written for
Slide Writing MUST follow the contracts below exactly (module names, class names, signatures,
dataclass fields), because modules are implemented in parallel against this spec.

## 0. Ground rules

- Python ≥ 3.9, **standard library only**. Allowed imports: `zipfile`, `xml.etree.ElementTree`,
  `dataclasses`, `json`, `struct`, `hashlib`, `io`, `os`, `re`, `typing`, `argparse`, `copy`,
  `posixpath`, `enum`, `math`, `unittest`, `tempfile`, `sys`, `collections`, `functools`.
  **Nothing else. No pip packages, ever.**
- Every module starts with `from __future__ import annotations`.
- Full type hints, docstrings on every public symbol. Library code never prints.
- Errors: raise the exceptions from `slidewriting.errors` with helpful messages.
- All coordinates/sizes in **EMU** (int). Public helpers accept pt/cm/inches via `emu.py`.
- All XML creation goes through `xmlcore` helpers (`qn`, `el`, `find`, `findall`, `serialize`).
  Never hand-concatenate XML strings in builder code (bootstrap.py is the only exception:
  it may use raw template strings for static parts, but must escape nothing dynamic).
- Text escaping is handled by ElementTree automatically — never pre-escape user text.
- Determinism: no randomness, no timestamps except fixed constants in docProps.

## 1. OOXML primer (what implementers must know)

A `.pptx` is a ZIP ("OPC package"):

```
[Content_Types].xml
_rels/.rels                              → officeDocument → /ppt/presentation.xml, docProps
docProps/core.xml, docProps/app.xml
ppt/presentation.xml                     → sldMasterIdLst, sldIdLst, sldSz, notesSz
ppt/_rels/presentation.xml.rels          → masters, slides, theme, presProps, viewProps, tableStyles
ppt/presProps.xml  ppt/viewProps.xml  ppt/tableStyles.xml
ppt/theme/theme1.xml                     → a:clrScheme, a:fontScheme, a:fmtScheme
ppt/slideMasters/slideMaster1.xml (+ _rels) → p:clrMap, p:txStyles, p:sldLayoutIdLst
ppt/slideLayouts/slideLayoutN.xml (+ _rels) → placeholders; rel to master
ppt/slides/slideN.xml (+ _rels)             → rel to its layout (+ images)
ppt/media/image1.png ...
```

Key namespaces (canonical prefixes — register exactly these):

| prefix | uri |
|---|---|
| `a`   | `http://schemas.openxmlformats.org/drawingml/2006/main` |
| `p`   | `http://schemas.openxmlformats.org/presentationml/2006/main` |
| `r`   | `http://schemas.openxmlformats.org/officeDocument/2006/relationships` |
| `ct`  | `http://schemas.openxmlformats.org/package/2006/content-types` |
| `rel` | `http://schemas.openxmlformats.org/package/2006/relationships` |
| `cp`  | `http://schemas.openxmlformats.org/package/2006/metadata/core-properties` |
| `dc`  | `http://purl.org/dc/elements/1.1/` |
| `dcterms` | `http://purl.org/dc/terms/` |
| `xsi` | `http://www.w3.org/2001/XMLSchema-instance` |
| `ep`  | `http://schemas.openxmlformats.org/officeDocument/2006/extended-properties` |
| `vt`  | `http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes` |

Relationship types (constants in `opc.py`, names as given):

```python
RT_OFFICE_DOCUMENT = ".../officeDocument/2006/relationships/officeDocument"
RT_SLIDE_MASTER, RT_SLIDE_LAYOUT, RT_SLIDE, RT_THEME, RT_IMAGE,
RT_PRES_PROPS, RT_VIEW_PROPS, RT_TABLE_STYLES, RT_CORE_PROPS, RT_EXTENDED_PROPS
# full URIs: http://schemas.openxmlformats.org/officeDocument/2006/relationships/<slideMaster|slideLayout|slide|theme|image|presProps|viewProps|tableStyles|extendedProperties>
# core props: http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties
```

Content types (constants in `opc.py`):

```python
CT_PRESENTATION = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
CT_SLIDE        = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
CT_SLIDE_LAYOUT = "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"
CT_SLIDE_MASTER = "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"
CT_THEME        = "application/vnd.openxmlformats-officedocument.theme+xml"
CT_PRES_PROPS   = "application/vnd.openxmlformats-officedocument.presentationml.presProps+xml"
CT_VIEW_PROPS   = "application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml"
CT_TABLE_STYLES = "application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml"
CT_CORE_PROPS   = "application/vnd.openxmlformats-package.core-properties+xml"
CT_EXT_PROPS    = "application/vnd.openxmlformats-officedocument.extended-properties+xml"
CT_RELS         = "application/vnd.openxmlformats-package.relationships+xml"
CT_XML, CT_PNG ("image/png"), CT_JPEG ("image/jpeg")
```

**Checklist to add one new slide** (implemented in `writer.py`):
1. Create part `/ppt/slides/slideN.xml` (N = first free number).
2. Create `/ppt/slides/_rels/slideN.xml.rels` with rel `RT_SLIDE_LAYOUT` →
   `../slideLayouts/slideLayoutK.xml` (+ one `RT_IMAGE` rel per picture → `../media/imageM.ext`).
3. Add `<Override>` in `[Content_Types].xml` with `CT_SLIDE`.
4. Add rel `RT_SLIDE` → `slides/slideN.xml` in `/ppt/_rels/presentation.xml.rels`.
5. Append `<p:sldId id="..." r:id="...">` to `p:sldIdLst` in `presentation.xml`
   (numeric id: max(existing, 255) + 1; must be ≥ 256 and < 2147483648).

**Placeholder inheritance:** a slide shape with `<p:ph type="T" idx="I"/>` and NO
`<a:xfrm>` inherits position/size/format from the layout placeholder with matching
(type, idx); the layout inherits from the master placeholder with matching type.
Body text styles fall back to master `p:txStyles`. `idx` default is 0 when absent;
`type` default is `"body"` when absent. Title matches by type only (`title`/`ctrTitle`).

**Color map:** master `<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" ... hlink="hlink" folHlink="folHlink"/>`
maps logical names (`bg1`, `tx1`, …) to theme slots (`lt1`, `dk1`, …). `<a:schemeClr val="X"/>`
inside slides resolves through this map.

**Units:** 1 inch = 914400 EMU, 1 cm = 360000 EMU, 1 pt = 12700 EMU. Font sizes in
DrawingML are in hundredths of a point (`sz="1800"` = 18 pt). Angles: 60000 = 1°.
Default slide size 16:9 = 12192000 × 6858000 EMU.

### Canonical XML skeletons

Minimal slide part:
```xml
<p:sld xmlns:a="…" xmlns:p="…" xmlns:r="…">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr>
        <a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>
        <a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm>
      </p:grpSpPr>
      <!-- shapes go here, ids start at 2 -->
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:overrideClrMapping … no: use <a:masterClrMapping/></p:clrMapOvr>
</p:sld>
```
(`<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>` is the correct child.)

Placeholder shape on a slide (inherits geometry from layout):
```xml
<p:sp>
  <p:nvSpPr>
    <p:cNvPr id="2" name="Title 1"/>
    <p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>
    <p:nvPr><p:ph type="title"/></p:nvPr>
  </p:nvSpPr>
  <p:spPr/>
  <p:txBody><a:bodyPr/><a:lstStyle/><a:p>…runs…</a:p></p:txBody>
</p:sp>
```

Free shape:
```xml
<p:sp>
  <p:nvSpPr><p:cNvPr id="3" name="Box 2"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
  <p:spPr>
    <a:xfrm><a:off x="…" y="…"/><a:ext cx="…" cy="…"/></a:xfrm>
    <a:prstGeom prst="roundRect"><a:avLst/></a:prstGeom>
    <a:solidFill><a:schemeClr val="accent1"/></a:solidFill>
    <a:ln w="12700"><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill></a:ln>
  </p:spPr>
  <p:txBody><a:bodyPr anchor="ctr"/><a:lstStyle/><a:p>…</a:p></p:txBody>
</p:sp>
```

Paragraph & run:
```xml
<a:p>
  <a:pPr lvl="0" algn="l"/>
  <a:r>
    <a:rPr lang="de-DE" sz="1800" b="1" dirty="0">
      <a:solidFill><a:schemeClr val="tx1"/></a:solidFill>
      <a:latin typeface="+mn-lt"/>
    </a:rPr>
    <a:t>Text</a:t>
  </a:r>
</a:p>
```
(`+mj-lt` = theme major latin, `+mn-lt` = theme minor latin. Omit `<a:latin>` to inherit.)

Table (inside `p:graphicFrame`):
```xml
<p:graphicFrame>
  <p:nvGraphicFramePr><p:cNvPr id="…" name="Table …"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr>
  <p:xfrm><a:off …/><a:ext …/></p:xfrm>
  <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">
    <a:tbl>
      <a:tblPr firstRow="1" bandRow="1"/>
      <a:tblGrid><a:gridCol w="…"/>…</a:tblGrid>
      <a:tr h="…"><a:tc><a:txBody>…</a:txBody><a:tcPr>…fill…</a:tcPr></a:tc>…</a:tr>
    </a:tbl>
  </a:graphicData></a:graphic>
</p:graphicFrame>
```

Picture:
```xml
<p:pic>
  <p:nvPicPr><p:cNvPr id="…" name="Picture …"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>
  <p:blipFill><a:blip r:embed="rId2"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>
  <p:spPr><a:xfrm>…</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>
</p:pic>
```

Useful preset geometries: `rect`, `roundRect`, `ellipse`, `triangle`, `rightArrow`,
`chevron`, `pie` (with `<a:avLst><a:gd name="adj1" fmla="val 0"/><a:gd name="adj2" fmla="val 16200000"/></a:avLst>`
— adj values are 60000ths of a degree, 0° = 3 o'clock, clockwise), `line` (use `p:cxnSp`
or a thin rect), `donut`, `blockArc`, `homePlate` (pentagon arrow).

## 2. Repository layout & file ownership

```
slidewriting/                  package (flat modules)
  __init__.py               [F]  __version__ = "1.0.0" (final exports added by integrator)
  errors.py                 [F]
  emu.py                    [F]
  xmlcore.py                [F]
  opc.py                    [F]
  theme.py                  [P1]
  model.py                  [P2]
  parser.py                 [P2]
  text.py                   [P3]
  slide.py                  [P3]
  shapes.py                 [P4]
  table.py                  [P4]
  components.py             [P5]
  writer.py                 [P6]
  bootstrap.py              [P6]
  api.py                    [P7]
  spec.py                   [P7]
  cli.py                    [P7]
  __main__.py               [P7]
tests/test_<module>.py      owned by the module's owner; test_e2e.py by integrator
examples/                   [P7]
docs/, README.md            [docs agent]
```

Owners write ONLY their files. Cross-module imports may not exist yet while you work —
write against the contracts; the integrator wires everything.

## 3. Module contracts

### 3.1 `errors.py` [F]

```python
class SlideWritingError(Exception): ...
class PackageError(SlideWritingError): ...   # zip/opc level problems
class ParseError(SlideWritingError): ...     # malformed/unsupported template
class BuildError(SlideWritingError): ...     # invalid build-time input
class SpecError(SlideWritingError): ...      # invalid JSON spec
```

### 3.2 `emu.py` [F]

```python
EMU_PER_INCH: int; EMU_PER_CM: int; EMU_PER_PT: int
def inches(v: float) -> int
def cm(v: float) -> int
def pt(v: float) -> int
def emu_to_pt(v: int) -> float
def hundredths_pt(size_pt: float) -> int          # 18 -> 1800 (for a:rPr sz)
class Box(NamedTuple):                            # all EMU
    x: int; y: int; w: int; h: int
    def inset(self, dx: int, dy: int) -> "Box"
SLIDE_W_16_9: int = 12192000
SLIDE_H_16_9: int = 6858000
```

### 3.3 `xmlcore.py` [F]

```python
NSMAP: dict[str, str]                              # prefixes from section 1
def qn(tag: str) -> str                            # "a:t" -> "{uri}t"; passthrough if no ':'
def parse_xml(blob: bytes) -> ET.Element
def serialize(root: ET.Element) -> bytes           # with XML declaration (utf-8, standalone)
def el(tag: str, attrib: dict[str, str] | None = None, *,
       parent: ET.Element | None = None, text: str | None = None) -> ET.Element
       # tag like "a:p"; attrib KEYS may also use prefixes ("r:id")
def sub(parent, tag, attrib=None, text=None) -> ET.Element   # alias for el(parent=…)
def find(root, path: str) -> ET.Element | None     # path with prefixes "p:cSld/p:spTree"
def findall(root, path: str) -> list[ET.Element]
def get(elem, attr: str, default: str | None = None) -> str | None  # attr may be "r:id"
```
At import time call `ET.register_namespace(prefix, uri)` for every NSMAP entry
(register `""` for none; keep canonical prefixes so output looks like Office output).
`serialize` must produce `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n` + body.

### 3.4 `opc.py` [F]

```python
# constants RT_* and CT_* from section 1
@dataclass
class Part:
    partname: str          # absolute, e.g. "/ppt/slides/slide1.xml"
    content_type: str
    blob: bytes

@dataclass
class Relationship:
    rid: str; reltype: str; target: str; target_mode: str = "Internal"

class Relationships:
    def __init__(self, source_partname: str): ...
    @classmethod
    def parse(cls, source_partname: str, blob: bytes) -> "Relationships"
    def add(self, reltype: str, target: str, rid: str | None = None,
            external: bool = False) -> str            # returns rId (next free "rIdN")
    def get(self, rid: str) -> Relationship | None
    def by_type(self, reltype: str) -> list[Relationship]
    def to_xml(self) -> bytes
    def __iter__(self) / __len__(self)
    def resolve(self, target: str) -> str             # rel target -> absolute partname
                                                      # (posixpath.normpath against source dir)

class Package:
    @classmethod
    def open(cls, path: str | os.PathLike | io.BytesIO) -> "Package"
    @classmethod
    def create(cls) -> "Package"                      # empty, default Defaults: rels, xml
    def part(self, partname: str) -> Part             # raises PackageError if missing
    def has_part(self, partname: str) -> bool
    def parts(self) -> list[Part]
    def add_part(self, partname: str, content_type: str, blob: bytes) -> Part
    def replace_blob(self, partname: str, blob: bytes) -> None
    def rels(self, partname: str | None = None) -> Relationships
        # None => package-level "/_rels/.rels"; auto-creates empty Relationships if absent
    def default_content_type(self, ext: str, content_type: str) -> None
    def next_partname(self, template: str) -> str     # "/ppt/slides/slide{}.xml" -> first free
    def main_part(self) -> Part                       # follows RT_OFFICE_DOCUMENT from package rels
    def save(self, path: str | os.PathLike | io.BytesIO) -> None
```
`open` reads every zip entry; `[Content_Types].xml` is parsed into Defaults (ext→ct,
case-insensitive ext) and Overrides (partname→ct). `save` regenerates
`[Content_Types].xml` and every `.rels` from the live objects, writes parts sorted:
`[Content_Types].xml` first, then `_rels/.rels`, then remaining parts in stable
(original-order-then-added) order. Use `zipfile.ZIP_DEFLATED`, fixed date_time
`(2026, 1, 1, 0, 0, 0)` on every `ZipInfo` for determinism. Rels partname mapping:
`/ppt/slides/slide1.xml` ↔ `/ppt/slides/_rels/slide1.xml.rels`.

### 3.5 `theme.py` [P1]

```python
SCHEME_SLOTS = ("dk1","lt1","dk2","lt2","accent1","accent2","accent3",
                "accent4","accent5","accent6","hlink","folHlink")

@dataclass
class ColorScheme:        # values: "RRGGBB" uppercase, no '#'
    dk1: str; lt1: str; dk2: str; lt2: str
    accent1: str; accent2: str; accent3: str; accent4: str; accent5: str; accent6: str
    hlink: str; folHlink: str
    def get(self, slot: str) -> str

@dataclass
class FontScheme:
    major_latin: str
    minor_latin: str

@dataclass
class Theme:
    name: str
    colors: ColorScheme
    fonts: FontScheme
    element: ET.Element            # parsed root, kept for fidelity

def parse_theme(blob: bytes) -> Theme
    # a:sysClr -> use lastClr attr (fallback: windowText->000000, window->FFFFFF)

class ColorResolver:
    def __init__(self, theme: Theme, clr_map: dict[str, str]): ...
    def rgb(self, name: str) -> str
        # accepts theme slots ("accent1"), mapped logical names ("tx1","bg1","tx2","bg2"),
        # and "RRGGBB" literals; raises ParseError on unknown names

# element factories (return new ET.Element):
def srgb_fill(rgb: str) -> ET.Element                 # <a:solidFill><a:srgbClr/></a:solidFill>
def scheme_fill(slot: str) -> ET.Element              # <a:solidFill><a:schemeClr/></a:solidFill>
def color_el(color: str) -> ET.Element
    # "accent1"/"tx1"/… -> a:schemeClr; "RRGGBB" or "#RRGGBB" -> a:srgbClr
def fill_for(color: str, alpha_pct: int | None = None) -> ET.Element
    # solidFill wrapping color_el; alpha via <a:alpha val="…"/> (val = pct*1000)
```

### 3.6 `model.py` [P2]

```python
@dataclass
class PlaceholderSpec:
    ph_type: str            # "title","ctrTitle","subTitle","body","ftr","dt","sldNum","pic",…
    idx: int                # 0 if absent
    shape_id: int
    name: str
    box: Box | None         # explicit a:xfrm on this element, else None
    element: ET.Element     # the <p:sp> from layout/master (read-only reference)

@dataclass
class LayoutSpec:
    partname: str
    name: str               # p:cSld@name
    ltype: str              # p:sldLayout@type, "" if absent ("custom")
    placeholders: list[PlaceholderSpec]
    element: ET.Element
    master_partname: str

@dataclass
class MasterSpec:
    partname: str
    clr_map: dict[str, str]                 # logical -> theme slot, from p:clrMap attribs
    placeholders: list[PlaceholderSpec]
    layouts: list[LayoutSpec]
    theme: Theme
    element: ET.Element

@dataclass
class SlideInfo:
    partname: str
    layout_partname: str
    title: str | None

@dataclass
class TemplateInfo:
    slide_width: int
    slide_height: int
    masters: list[MasterSpec]
    slides: list[SlideInfo]
    @property def layouts(self) -> list[LayoutSpec]    # all masters' layouts flattened
    def find_layout(self, query: str | int) -> LayoutSpec
        # int -> index; str -> match (case-insensitive): exact name, then ltype,
        # then name-substring; raises ParseError listing available layouts on miss
    def resolver(self, layout: LayoutSpec) -> ColorResolver   # via its master
```

### 3.7 `parser.py` [P2]

```python
class TemplateParser:
    def __init__(self, package: Package): ...
    def parse(self) -> TemplateInfo
def effective_box(layout: LayoutSpec, master: MasterSpec, ph_type: str, idx: int) -> Box | None
    # box of matching layout ph; if None, fall back to master ph matching by type
def extract_placeholders(sp_tree: ET.Element) -> list[PlaceholderSpec]
def slide_title_text(slide_root: ET.Element) -> str | None
```
Parsing walks: presentation.xml (`p:sldSz`, `p:sldMasterIdLst`, `p:sldIdLst`) →
presentation rels → master parts → master rels (layouts via `p:sldLayoutIdLst` r:id +
theme) → layout parts. Tolerate missing optional bits; raise `ParseError` only for
structurally unusable files.

### 3.8 `text.py` [P3]

```python
@dataclass
class RunFormat:
    size_pt: float | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    color: str | None = None        # scheme slot / logical / "RRGGBB"
    font: str | None = None         # explicit typeface, or "+mj-lt"/"+mn-lt"

@dataclass
class ParaFormat:
    level: int = 0                  # 0-8
    align: str | None = None        # "l","ctr","r","just"
    space_before_pt: float | None = None
    space_after_pt: float | None = None
    line_spacing: float | None = None     # multiple, e.g. 1.0, 1.2
    bullet: str | None = None       # None=inherit, "none"=buNone, else literal char e.g. "•"

def run_el(text: str, fmt: RunFormat | None = None, lang: str = "de-DE") -> ET.Element
def para_el(runs: list[ET.Element] | str, pf: ParaFormat | None = None,
            default_fmt: RunFormat | None = None) -> ET.Element
def txbody_el(paragraphs: list[ET.Element], *, anchor: str | None = None,
              wrap: bool = True, autofit: str | None = "norm",
              insets_emu: tuple[int,int,int,int] | None = None) -> ET.Element
    # autofit: None | "norm" (<a:normAutofit/>) | "shrink" | "spAuto"

class TextFrame:
    """Wrapper around an existing <p:txBody> element inside a shape."""
    def __init__(self, txbody: ET.Element): ...
    def clear(self) -> None
    def text(self, value: str, fmt: RunFormat | None = None,
             pf: ParaFormat | None = None) -> "TextFrame"
    def paragraph(self, value: str | list[tuple[str, RunFormat | None]],
                  pf: ParaFormat | None = None) -> "TextFrame"
    def bullets(self, items: "list[BulletItem]",
                base_fmt: RunFormat | None = None) -> "TextFrame"
# BulletItem = str | tuple[str, int] | dict(text=…, level=0, bold=…, color=…, size_pt=…)
```
Multi-line strings ("a\nb") become multiple paragraphs.

### 3.9 `slide.py` [P3]

```python
class PlaceholderShape:
    """A <p:sp> with <p:ph> on a slide under construction."""
    frame: TextFrame
    element: ET.Element
    def text(self, value, **fmt_kwargs) -> "PlaceholderShape"
    def bullets(self, items, **kwargs) -> "PlaceholderShape"

class SlideBuilder:
    def __init__(self, layout: LayoutSpec, master: MasterSpec,
                 slide_width: int, slide_height: int): ...
    # creates the canonical empty <p:sld> skeleton (section 1)
    width: int; height: int
    resolver: ColorResolver            # built from master.theme + master.clr_map
    def next_id(self) -> int           # shape ids, starts at 2
    def placeholder(self, ref: str | int) -> PlaceholderShape
        # ref: "title" (matches title|ctrTitle), "subtitle" (subTitle), "body",
        # int = idx, or layout-placeholder name; copies (type, idx) from the layout's
        # matching PlaceholderSpec so inheritance works; raises BuildError if the
        # layout has no such placeholder (message lists available ones)
    def title(self, value: str, **fmt) -> PlaceholderShape
    def add_textbox(self, box: Box, *, anchor: str | None = None) -> TextFrame
        # appends <p:sp> with txBox="1" on cNvSpPr, returns its TextFrame
    def add_shape(self, preset: str, box: Box, *, fill: str | None = None,
                  line: str | None = None, line_w_pt: float = 1.0,
                  text: str | None = None, text_fmt: RunFormat | None = None,
                  anchor: str = "ctr", align: str = "ctr",
                  adj: dict[str, int] | None = None, rot: int | None = None) -> ET.Element
    def add_line(self, x1: int, y1: int, x2: int, y2: int,
                 color: str = "tx1", w_pt: float = 1.0, dash: str | None = None) -> ET.Element
    def add_picture(self, image: bytes | str, box: Box) -> ET.Element
        # registers via self._pending_images: list[tuple[placeholder_rid, bytes]]
        # rid placeholder format: use add_pending_image(blob) -> temp rid "img:N";
        # writer.py replaces temp rids with real rIds when the slide part is created
    def add_table(self, box: Box, columns: list, rows: list, style=None) -> ET.Element
        # delegates to table.table_el using self.resolver
    pending_images: list[tuple[str, bytes]]      # [(temp_rid, blob)]
    def to_xml(self) -> bytes
```
Image temp-rid mechanism (contract between P3 and P6): `add_picture` stores
`("img:1", blob)` in `pending_images` and writes `r:embed="img:1"` in the XML;
`writer.add_slide` adds the media part + rel, then replaces every `img:N` token in the
blob with the real rId before storing the part.

### 3.10 `shapes.py` [P4]

```python
def shape_el(shape_id: int, name: str, preset: str, box: Box, *,
             fill: ET.Element | None = None, line: ET.Element | None = None,
             txbody: ET.Element | None = None, adj: dict[str, int] | None = None,
             rot: int | None = None, flip_h: bool = False, flip_v: bool = False) -> ET.Element
def line_props(color_el_: ET.Element, w_emu: int, dash: str | None = None,
               cap: str = "flat") -> ET.Element          # <a:ln>
def no_fill() -> ET.Element                              # <a:noFill/> wrapped appropriately
def connector_el(shape_id: int, name: str, x1, y1, x2, y2,
                 line: ET.Element) -> ET.Element          # <p:cxnSp> with prst "line"
def picture_el(shape_id: int, name: str, rid: str, box: Box) -> ET.Element
def detect_image(blob: bytes) -> tuple[str, str, int, int]
    # -> (ext "png"/"jpeg", content_type, px_width, px_height); struct-based:
    # PNG: bytes 16:24 of IHDR; JPEG: scan SOFn markers (0xC0-0xCF except C4,C8,CC)
    # raises BuildError for unsupported formats
```

### 3.11 `table.py` [P4]

```python
@dataclass
class TableStyle:
    header_fill: str = "accent1"; header_color: str = "FFFFFF"
    header_bold: bool = True; header_size_pt: float = 11.0
    body_size_pt: float = 11.0; body_color: str = "tx1"
    band_fill: str | None = None          # zebra fill for even rows, e.g. "F2F2F2"
    border_color: str = "D9D9D9"; border_w_pt: float = 0.75
    row_height_pt: float = 22.0; cell_margin_pt: float = 4.0
    align_numbers_right: bool = True      # right-align cells that look numeric

def table_el(shape_id: int, box: Box, columns: list[str | dict],
             rows: list[list[str]], style: TableStyle | None = None,
             col_widths: list[float] | None = None) -> ET.Element
    # columns: str or {"label": str, "width": rel_float, "align": "l|ctr|r"}
    # col widths distributed proportionally to fill box.w exactly (last col absorbs rounding)
```

### 3.12 `components.py` [P5]

All functions take a `SlideBuilder` and use `slide.width/height` for default geometry;
all colors via scheme slots through `slide.resolver`/scheme color elements (theme-true).
Margins: content area defaults to x=cm(1.2), content top y≈cm(3.2) (below title),
bottom margin cm(1.2).

```python
def add_agenda(slide, items: list[str], active: int | None = None, box: Box | None = None)
def add_kpi_row(slide, kpis: list[dict], box: Box | None = None)
    # kpi: {"value": "42 %", "label": "Marktanteil", "delta": "+3 pp"|None,
    #       "color": scheme-slot|None}  → rounded tiles, value large+accent, delta green/red
def add_harvey(slide, box: Box, fraction: float, color: str = "accent1")
    # 0/.25/.5/.75/1 (round to nearest quarter): outline ellipse + pie overlay
def add_harvey_matrix(slide, options: list[str], criteria: list[str],
                      scores: list[list[float]], box: Box | None = None)
def add_traffic_light(slide, box: Box, status: str)        # "red"|"yellow"|"green"
def add_waterfall(slide, box: Box, items: list[dict], total_label: str = "Summe")
    # item: {"label": str, "value": float}; pos=accent1, neg=accent2, sum=dk2-ish;
    # value labels above bars, dashed connectors between bars, baseline axis
def add_bar_chart(slide, box: Box, categories: list[str], values: list[float],
                  color: str = "accent1", show_values: bool = True,
                  horizontal: bool = True)
def add_column_chart(slide, box, categories, values, color="accent1", show_values=True)
def add_timeline(slide, phases: list[dict], box: Box | None = None)
    # phase: {"label": str, "sub": str|None, "active": bool}  → chevron band
def add_comparison(slide, options: list[str], criteria: list[str],
                   cells: list[list[str | float]], box: Box | None = None)
    # cell str → text, float → harvey
def add_callout(slide, text: str, kind: str = "info", box: Box | None = None)
    # kind: info(accent1) | success(green 2E9E4F) | warning(amber E8A33D) | key(dk2)
    # rounded rect, left accent bar, padded text
def add_section_number(slide, current: int, total: int)     # small "3/12" top-right
```

### 3.13 `writer.py` [P6]

```python
class SlideWriter:
    def __init__(self, package: Package, info: TemplateInfo): ...
    def add_slide(self, slide_xml: bytes, layout_partname: str,
                  pending_images: list[tuple[str, bytes]] | None = None) -> str
        # full checklist from section 1; returns new slide partname
    def add_image(self, blob: bytes) -> str
        # dedups by sha256 → existing media partname; detects ext via shapes.detect_image;
        # ensures Default content type for ext; returns media partname
    def _next_slide_id(self) -> int
def set_core_properties(package: Package, title: str, creator: str = "Slide Writing") -> None
```

### 3.14 `bootstrap.py` [P6]

```python
def create_default_template(accent: str = "206EFB", *, name: str = "Slide Writing",
                            major_font: str = "Calibri Light",
                            minor_font: str = "Calibri") -> Package
DEFAULT_LAYOUTS = [("Titelfolie","title"), ("Titel und Inhalt","obj"),
                   ("Abschnittsüberschrift","secHead"), ("Zwei Inhalte","twoObj"),
                   ("Nur Titel","titleOnly"), ("Leer","blank")]
```
Builds a complete, valid 16:9 presentation **from scratch**: content types, package rels,
docProps (core+app), presentation.xml (+rels), presProps, viewProps, tableStyles
(`<a:tblStyleLst def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>` minimal), theme1.xml
(clrScheme with the accent param as accent1 + sensible derived palette; full fmtScheme
with 3 fill styles / 3 line styles / 3 effect styles / 3 bg fill styles like Office
default), slideMaster1 (clrMap, title/body/footer placeholders with real boxes,
txStyles with sizes: title 36pt mj-lt, body lvl1 18pt → decreasing), the six layouts
with correctly typed+positioned placeholders, and **no slides**. Title bar styling:
clean consulting look — title top-left, thin accent rule under title (in master),
footer with dt/ftr/sldNum.

### 3.15 `api.py` [P7]

```python
class Deck:
    @classmethod
    def open(cls, path) -> "Deck"            # Package.open + TemplateParser
    @classmethod
    def create(cls, accent: str = "206EFB", **kw) -> "Deck"   # bootstrap template
    info: TemplateInfo; package: Package
    @property def theme(self) -> Theme       # first master's
    @property def layouts(self) -> list[LayoutSpec]
    def layout(self, query) -> LayoutSpec
    def add_slide(self, layout: str | int | LayoutSpec | None = None) -> SlideBuilder
        # default layout: ltype "obj" if present else first; builder is queued
    def save(self, path) -> None
        # flushes queued builders via SlideWriter in order, sets core props, package.save
    def inspect(self) -> dict
        # {"slide_size": [w,h], "masters": n, "layouts": [{name,type,placeholders:[…]}],
        #  "theme": {"colors": {...}, "fonts": {...}}, "slides": [{partname, layout, title}]}
```

### 3.16 `spec.py` [P7]

```python
def build_from_spec(spec: dict, template_path: str | None = None) -> Deck
def validate_spec(spec: dict) -> list[str]        # human-readable problems, [] if ok
```
Spec format (document in docstring; raise SpecError with slide index on problems):

```json
{ "template": "optional/path.pptx", "accent": "206EFB",
  "title": "Deck-Titel", "author": "ROOTS",
  "slides": [
    {"type": "title", "title": "…", "subtitle": "…"},
    {"type": "section", "title": "…", "number": "01"},
    {"type": "bullets", "layout": "Titel und Inhalt", "title": "…",
     "bullets": ["a", {"text": "b", "level": 1}], "callout": {"text": "…", "kind": "key"}},
    {"type": "agenda", "title": "Agenda", "items": ["…"], "active": 0},
    {"type": "kpi", "title": "…", "kpis": [{"value": "…", "label": "…", "delta": "…"}]},
    {"type": "table", "title": "…", "columns": ["…"], "rows": [["…"]]},
    {"type": "waterfall", "title": "…", "items": [{"label": "…", "value": 1.0}]},
    {"type": "bars", "title": "…", "categories": ["…"], "values": [1.0], "horizontal": true},
    {"type": "timeline", "title": "…", "phases": [{"label": "…", "sub": "…", "active": false}]},
    {"type": "comparison", "title": "…", "options": ["…"], "criteria": ["…"], "cells": [[0.5]]},
    {"type": "blank", "layout": "Leer"}
  ] }
```

### 3.17 `cli.py` + `__main__.py` [P7]

```
python3 -m slidewriting inspect <file.pptx> [--json]
python3 -m slidewriting generate --spec spec.json [--template t.pptx] --out out.pptx
python3 -m slidewriting bootstrap --out template.pptx [--accent HEX]
python3 -m slidewriting demo --out demo.pptx            # built-in showcase spec, all components
```
`main(argv=None) -> int`; errors print to stderr, exit 1; never traceback for user errors.

## 4. Testing conventions

- `unittest`, files `tests/test_<module>.py`, runnable via
  `python3 -m unittest discover -s tests -v` from repo root.
- Tests must not require any template file on disk: use `bootstrap.create_default_template()`
  (P6) or hand-built XML snippets. If your module's tests need a sibling module that may
  not exist yet, write the tests anyway — the integrator runs them.
- E2E (integrator): create deck → add one slide of every component → save to temp →
  `Package.open` it again → assert: all parts parse as XML, content types cover every
  part, every rel target exists, sldIdLst count matches slide parts, every slide has
  its layout rel; re-parse with TemplateParser.

## 5. Quality bar

Production quality: clear docstrings (English), small functions, no dead code,
no TODOs left, meaningful exception messages (German user-facing CLI messages are fine).
German content strings in examples are encouraged (target users are German consultants).
