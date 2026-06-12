"""Open Packaging Conventions (OPC) layer: parts, relationships, package I/O.

A ``.pptx`` file is a ZIP container with parts (XML and media files),
relationship files (``.rels``) wiring parts together, and a
``[Content_Types].xml`` mapping parts to MIME content types. This module
reads and writes such containers deterministically: fixed zip timestamps,
stable part ordering, and regenerated rels/content types on every save.

Partnames are absolute POSIX paths with a leading slash
(``"/ppt/slides/slide1.xml"``); zip entry names have no leading slash.
"""

from __future__ import annotations

import io
import os
import posixpath
import re
import zipfile
from dataclasses import dataclass

from .errors import PackageError
from .xmlcore import el, findall, parse_xml, serialize, sub

# --- Relationship type URIs (ARCHITECTURE.md §1) -------------------------------------

_RT_BASE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"

RT_OFFICE_DOCUMENT = _RT_BASE + "officeDocument"
RT_SLIDE_MASTER = _RT_BASE + "slideMaster"
RT_SLIDE_LAYOUT = _RT_BASE + "slideLayout"
RT_SLIDE = _RT_BASE + "slide"
RT_THEME = _RT_BASE + "theme"
RT_IMAGE = _RT_BASE + "image"
RT_PRES_PROPS = _RT_BASE + "presProps"
RT_VIEW_PROPS = _RT_BASE + "viewProps"
RT_TABLE_STYLES = _RT_BASE + "tableStyles"
RT_EXTENDED_PROPS = _RT_BASE + "extendedProperties"
RT_CORE_PROPS = (
    "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"
)

# --- Content type strings (ARCHITECTURE.md §1) ---------------------------------------

CT_PRESENTATION = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
)
CT_SLIDE = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
CT_SLIDE_LAYOUT = (
    "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"
)
CT_SLIDE_MASTER = (
    "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"
)
CT_THEME = "application/vnd.openxmlformats-officedocument.theme+xml"
CT_PRES_PROPS = "application/vnd.openxmlformats-officedocument.presentationml.presProps+xml"
CT_VIEW_PROPS = "application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml"
CT_TABLE_STYLES = (
    "application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml"
)
CT_CORE_PROPS = "application/vnd.openxmlformats-package.core-properties+xml"
CT_EXT_PROPS = "application/vnd.openxmlformats-officedocument.extended-properties+xml"
CT_RELS = "application/vnd.openxmlformats-package.relationships+xml"
CT_XML = "application/xml"
CT_PNG = "image/png"
CT_JPEG = "image/jpeg"

_CONTENT_TYPES_NAME = "[Content_Types].xml"
_RELS_SUFFIX = ".rels"
_ZIP_DATE_TIME = (2026, 1, 1, 0, 0, 0)
_RID_RE = re.compile(r"rId(\d+)\Z")


def _rels_partname(source_partname: str | None) -> str:
    """Return the rels partname for a source part (``None`` = package level)."""
    if source_partname is None:
        return "/_rels/.rels"
    directory, base = posixpath.split(source_partname)
    return posixpath.join(directory, "_rels", base + _RELS_SUFFIX)


def _is_rels_partname(partname: str) -> bool:
    """True if ``partname`` denotes a relationships part (``.../_rels/*.rels``)."""
    return (
        partname.endswith(_RELS_SUFFIX)
        and posixpath.basename(posixpath.dirname(partname)) == "_rels"
    )


def _rels_source(rels_partname: str) -> str | None:
    """Map a rels partname back to its source partname (``None`` = package level).

    ``"/ppt/_rels/presentation.xml.rels"`` -> ``"/ppt/presentation.xml"``;
    ``"/_rels/.rels"`` -> ``None``.
    """
    rels_dir = posixpath.dirname(rels_partname)
    parent = posixpath.dirname(rels_dir)
    base = posixpath.basename(rels_partname)[: -len(_RELS_SUFFIX)]
    if not base:
        return None
    return posixpath.join(parent, base)


def _extension(partname: str) -> str:
    """Lower-cased file extension of a partname, without the dot."""
    return posixpath.splitext(partname)[1].lstrip(".").lower()


@dataclass
class Part:
    """One package part: absolute partname, content type, and raw bytes."""

    partname: str
    content_type: str
    blob: bytes


@dataclass
class Relationship:
    """One relationship entry of a ``.rels`` part."""

    rid: str
    reltype: str
    target: str
    target_mode: str = "Internal"


class Relationships:
    """The set of relationships originating from one source part.

    For package-level relationships (``/_rels/.rels``) the source partname
    is ``"/"``. Iteration yields :class:`Relationship` objects in insertion
    order, which is also the serialization order.
    """

    def __init__(self, source_partname: str) -> None:
        """Create an empty relationship set for the given source partname."""
        self.source_partname = source_partname
        self._rels: dict[str, Relationship] = {}

    @classmethod
    def parse(cls, source_partname: str, blob: bytes) -> "Relationships":
        """Parse the XML of a ``.rels`` part into a :class:`Relationships` object."""
        rels = cls(source_partname)
        root = parse_xml(blob)
        for node in findall(root, "rel:Relationship"):
            rid = node.get("Id")
            reltype = node.get("Type")
            target = node.get("Target")
            if not rid or not reltype or target is None:
                raise PackageError(
                    f"Relationship in rels of {source_partname!r} is missing "
                    f"Id, Type, or Target"
                )
            mode = node.get("TargetMode", "Internal")
            if rid in rels._rels:
                raise PackageError(
                    f"Duplicate relationship id {rid!r} in rels of {source_partname!r}"
                )
            rels._rels[rid] = Relationship(rid, reltype, target, mode)
        return rels

    def add(
        self,
        reltype: str,
        target: str,
        rid: str | None = None,
        external: bool = False,
    ) -> str:
        """Add a relationship and return its rId.

        When ``rid`` is omitted, the next free id is allocated as
        ``max(existing numeric rIds) + 1`` (gaps are not reused). External
        relationships keep their target verbatim (``TargetMode="External"``).
        """
        if rid is None:
            rid = self._next_rid()
        elif rid in self._rels:
            raise PackageError(
                f"Relationship id {rid!r} already exists in rels of "
                f"{self.source_partname!r}"
            )
        mode = "External" if external else "Internal"
        self._rels[rid] = Relationship(rid, reltype, target, mode)
        return rid

    def get(self, rid: str) -> Relationship | None:
        """Return the relationship with the given rId, or ``None``."""
        return self._rels.get(rid)

    def by_type(self, reltype: str) -> list[Relationship]:
        """Return all relationships of the given type, in insertion order."""
        return [r for r in self._rels.values() if r.reltype == reltype]

    def to_xml(self) -> bytes:
        """Serialize to the XML body of a ``.rels`` part."""
        root = el("rel:Relationships")
        for r in self._rels.values():
            attrs = {"Id": r.rid, "Type": r.reltype, "Target": r.target}
            if r.target_mode == "External":
                attrs["TargetMode"] = "External"
            sub(root, "rel:Relationship", attrs)
        return serialize(root)

    def resolve(self, target: str) -> str:
        """Resolve an internal relationship target to an absolute partname.

        Relative targets such as ``"../slideLayouts/slideLayout1.xml"`` are
        resolved against the source part's directory; absolute targets are
        normalized as-is. Not meaningful for external targets.
        """
        if target.startswith("/"):
            return posixpath.normpath(target)
        base_dir = posixpath.dirname(self.source_partname) or "/"
        return posixpath.normpath(posixpath.join(base_dir, target))

    def __iter__(self):
        """Iterate over :class:`Relationship` objects in insertion order."""
        return iter(self._rels.values())

    def __len__(self) -> int:
        """Number of relationships in this set."""
        return len(self._rels)

    def _next_rid(self) -> str:
        """Next free rId: max of existing numeric ids plus one."""
        highest = 0
        for rid in self._rels:
            match = _RID_RE.match(rid)
            if match:
                highest = max(highest, int(match.group(1)))
        return f"rId{highest + 1}"


class Package:
    """An OPC package: ordered parts, relationship sets, and content types.

    Use :meth:`open` to read an existing ``.pptx`` or :meth:`create` for an
    empty package. Parts keep their original order; added parts append at the
    end. :meth:`save` regenerates ``[Content_Types].xml`` and every ``.rels``
    from the live objects and writes a deterministic zip.
    """

    def __init__(self) -> None:
        """Create a completely empty package (no parts, rels, or content types)."""
        self._parts: dict[str, Part] = {}
        self._rels: dict[str | None, Relationships] = {}
        self._defaults: dict[str, str] = {}
        self._overrides: dict[str, str] = {}

    @classmethod
    def open(cls, path: str | os.PathLike | io.BytesIO) -> "Package":
        """Read a package from a file path or binary file object."""
        pkg = cls()
        try:
            zf = zipfile.ZipFile(path, "r")
        except zipfile.BadZipFile as exc:
            raise PackageError(f"Not a valid OPC package (bad zip): {exc}") from exc
        with zf:
            names = [info.filename for info in zf.infolist() if not info.is_dir()]
            if _CONTENT_TYPES_NAME not in names:
                raise PackageError(
                    f"Package is missing {_CONTENT_TYPES_NAME}; not a valid OPC package"
                )
            pkg._parse_content_types(zf.read(_CONTENT_TYPES_NAME))
            for name in names:
                if name == _CONTENT_TYPES_NAME:
                    continue
                partname = "/" + name
                blob = zf.read(name)
                if _is_rels_partname(partname):
                    source = _rels_source(partname)
                    source_name = "/" if source is None else source
                    pkg._rels[source] = Relationships.parse(source_name, blob)
                else:
                    pkg._parts[partname] = Part(
                        partname, pkg._content_type_for(partname), blob
                    )
        return pkg

    @classmethod
    def create(cls) -> "Package":
        """Create an empty package with the standard Defaults (``rels``, ``xml``)."""
        pkg = cls()
        pkg._defaults["rels"] = CT_RELS
        pkg._defaults["xml"] = CT_XML
        return pkg

    def part(self, partname: str) -> Part:
        """Return the part with the given partname; raise :class:`PackageError` if missing."""
        try:
            return self._parts[partname]
        except KeyError:
            raise PackageError(f"Package has no part {partname!r}") from None

    def has_part(self, partname: str) -> bool:
        """True if a part with the given partname exists."""
        return partname in self._parts

    def parts(self) -> list[Part]:
        """All parts in stable order (original order, then added order)."""
        return list(self._parts.values())

    def add_part(self, partname: str, content_type: str, blob: bytes) -> Part:
        """Add a new part and register its content type.

        An ``<Override>`` is recorded unless the extension's Default already
        yields ``content_type``. Raises :class:`PackageError` for invalid
        partnames or duplicates.
        """
        if not partname.startswith("/"):
            raise PackageError(
                f"Partname must be absolute (start with '/'): {partname!r}"
            )
        if partname in self._parts:
            raise PackageError(f"Part {partname!r} already exists in package")
        if self._defaults.get(_extension(partname)) != content_type:
            self._overrides[partname] = content_type
        part = Part(partname, content_type, blob)
        self._parts[partname] = part
        return part

    def replace_blob(self, partname: str, blob: bytes) -> None:
        """Replace the bytes of an existing part; raise :class:`PackageError` if missing."""
        self.part(partname).blob = blob

    def rels(self, partname: str | None = None) -> Relationships:
        """Relationships of a part, or package-level rels for ``None``.

        An empty :class:`Relationships` object is created (and remembered)
        if none exists yet.
        """
        existing = self._rels.get(partname)
        if existing is None:
            source = "/" if partname is None else partname
            existing = Relationships(source)
            self._rels[partname] = existing
        return existing

    def default_content_type(self, ext: str, content_type: str) -> None:
        """Register a Default content type for an extension (case-insensitive)."""
        self._defaults[ext.lstrip(".").lower()] = content_type

    def next_partname(self, template: str) -> str:
        """First free partname for a template like ``"/ppt/slides/slide{}.xml"``."""
        n = 1
        while template.format(n) in self._parts:
            n += 1
        return template.format(n)

    def main_part(self) -> Part:
        """The main document part, found via the package-level officeDocument rel."""
        pkg_rels = self._rels.get(None)
        if pkg_rels is None:
            raise PackageError("Package has no package-level relationships (/_rels/.rels)")
        office_rels = pkg_rels.by_type(RT_OFFICE_DOCUMENT)
        if not office_rels:
            raise PackageError("Package has no officeDocument relationship in /_rels/.rels")
        return self.part(pkg_rels.resolve(office_rels[0].target))

    def save(self, path: str | os.PathLike | io.BytesIO) -> None:
        """Write the package as a deterministic zip.

        ``[Content_Types].xml`` and all ``.rels`` are regenerated from the
        live objects. Entry order: ``[Content_Types].xml``, ``_rels/.rels``,
        then every part in stable order with its (non-empty) rels right after
        it. All entries use ``ZIP_DEFLATED`` and the fixed timestamp
        ``(2026, 1, 1, 0, 0, 0)``.
        """
        content_types = self._content_types_xml()
        package_rels = self.rels(None)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            self._write_entry(zf, _CONTENT_TYPES_NAME, content_types)
            self._write_entry(zf, _rels_partname(None)[1:], package_rels.to_xml())
            for part in self._parts.values():
                self._write_entry(zf, part.partname[1:], part.blob)
                part_rels = self._rels.get(part.partname)
                if part_rels is not None and len(part_rels) > 0:
                    self._write_entry(
                        zf, _rels_partname(part.partname)[1:], part_rels.to_xml()
                    )

    # --- internal helpers -------------------------------------------------------

    def _parse_content_types(self, blob: bytes) -> None:
        """Populate Defaults and Overrides from ``[Content_Types].xml``."""
        root = parse_xml(blob)
        for node in findall(root, "ct:Default"):
            ext = node.get("Extension")
            content_type = node.get("ContentType")
            if not ext or not content_type:
                raise PackageError(
                    "Invalid <Default> in [Content_Types].xml: "
                    "Extension and ContentType are required"
                )
            self._defaults[ext.lower()] = content_type
        for node in findall(root, "ct:Override"):
            partname = node.get("PartName")
            content_type = node.get("ContentType")
            if not partname or not content_type:
                raise PackageError(
                    "Invalid <Override> in [Content_Types].xml: "
                    "PartName and ContentType are required"
                )
            self._overrides[partname] = content_type

    def _content_type_for(self, partname: str) -> str:
        """Resolve a part's content type: Override first, then Default by extension."""
        content_type = self._overrides.get(partname)
        if content_type is not None:
            return content_type
        content_type = self._defaults.get(_extension(partname))
        if content_type is None:
            raise PackageError(
                f"No content type declared for part {partname!r} "
                f"(neither Override nor Default for its extension)"
            )
        return content_type

    def _content_types_xml(self) -> bytes:
        """Regenerate the ``[Content_Types].xml`` blob from live state."""
        root = el("ct:Types")
        for ext, content_type in self._defaults.items():
            sub(root, "ct:Default", {"Extension": ext, "ContentType": content_type})
        for part in self._parts.values():
            override = self._overrides.get(part.partname)
            if override is not None:
                sub(
                    root,
                    "ct:Override",
                    {"PartName": part.partname, "ContentType": override},
                )
        return serialize(root)

    @staticmethod
    def _write_entry(zf: zipfile.ZipFile, name: str, data: bytes) -> None:
        """Write one zip entry with the fixed timestamp and DEFLATE compression."""
        info = zipfile.ZipInfo(name, date_time=_ZIP_DATE_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, data)
