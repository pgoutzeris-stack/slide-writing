"""Namespace-aware XML helpers for all Slide Writing modules.

Every piece of XML in Slide Writing is created, queried, and serialized through
the helpers in this module so that namespace handling is uniform. The
canonical OOXML prefixes from :data:`NSMAP` are registered with
:mod:`xml.etree.ElementTree` at import time, which makes serialized output
use the same prefixes Office itself writes (``a:``, ``p:``, ``r:``, ...).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .errors import SlideWritingError, ParseError

#: Canonical namespace prefixes used throughout Slide Writing (see ARCHITECTURE.md §1).
NSMAP: dict[str, str] = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
    "vt": "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes",
}

for _prefix, _uri in NSMAP.items():
    ET.register_namespace(_prefix, _uri)

_XML_DECL: bytes = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'


def qn(tag: str) -> str:
    """Expand a prefixed name to Clark notation: ``"a:t"`` -> ``"{uri}t"``.

    Works for element tags and attribute names alike (e.g. ``"r:id"``).
    Names without a colon, and names already in Clark notation, are returned
    unchanged. Raises :class:`SlideWritingError` for unknown prefixes.
    """
    if tag.startswith("{") or ":" not in tag:
        return tag
    prefix, _, local = tag.partition(":")
    try:
        uri = NSMAP[prefix]
    except KeyError:
        raise SlideWritingError(
            f"Unknown namespace prefix {prefix!r} in {tag!r}; "
            f"known prefixes: {', '.join(sorted(NSMAP))}"
        ) from None
    return f"{{{uri}}}{local}"


def parse_xml(blob: bytes) -> ET.Element:
    """Parse a bytes blob into an :class:`ET.Element` root.

    Raises :class:`ParseError` if the blob is not well-formed XML.
    """
    try:
        return ET.fromstring(blob)
    except ET.ParseError as exc:
        raise ParseError(f"Malformed XML: {exc}") from exc


def serialize(root: ET.Element) -> bytes:
    """Serialize an element tree to UTF-8 bytes with the standard XML declaration.

    Output starts with
    ``<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\\r\\n``
    followed by the document body using the canonical prefixes from :data:`NSMAP`.
    """
    body = ET.tostring(root, encoding="unicode")
    return _XML_DECL + body.encode("utf-8")


def el(
    tag: str,
    attrib: dict[str, str] | None = None,
    *,
    parent: ET.Element | None = None,
    text: str | None = None,
) -> ET.Element:
    """Create an element from a prefixed tag like ``"a:p"``.

    Attribute keys may also carry prefixes (``"r:id"``); values are taken
    verbatim. If ``parent`` is given, the new element is appended to it.
    """
    attrs = {qn(k): v for k, v in attrib.items()} if attrib else {}
    node = ET.Element(qn(tag), attrs)
    if text is not None:
        node.text = text
    if parent is not None:
        parent.append(node)
    return node


def sub(
    parent: ET.Element,
    tag: str,
    attrib: dict[str, str] | None = None,
    text: str | None = None,
) -> ET.Element:
    """Create a child element under ``parent``; alias for ``el(tag, attrib, parent=...)``."""
    return el(tag, attrib, parent=parent, text=text)


def find(root: ET.Element, path: str) -> ET.Element | None:
    """Find the first element matching a prefixed path like ``"p:cSld/p:spTree"``."""
    return root.find(path, NSMAP)


def findall(root: ET.Element, path: str) -> list[ET.Element]:
    """Find all elements matching a prefixed path like ``"a:p/a:r"``."""
    return root.findall(path, NSMAP)


def get(elem: ET.Element, attr: str, default: str | None = None) -> str | None:
    """Read an attribute; the name may be prefixed (e.g. ``"r:id"``)."""
    return elem.get(qn(attr), default)
