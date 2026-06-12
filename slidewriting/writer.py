"""Valid mutation of presentation packages: slides, images, core properties.

:class:`SlideWriter` implements the five-step "add one new slide" checklist
from ARCHITECTURE.md section 1 against a live :class:`~slidewriting.opc.Package`:

1. create the slide part under ``/ppt/slides/``,
2. create its ``.rels`` (layout rel plus one image rel per picture),
3. register the ``CT_SLIDE`` content-type override,
4. add the ``RT_SLIDE`` relationship from ``presentation.xml``,
5. append a ``<p:sldId>`` entry to ``p:sldIdLst`` in ``presentation.xml``.

Images arrive from :class:`~slidewriting.slide.SlideBuilder` as
``pending_images`` — pairs of a temporary relationship token (``"img:N"``)
and the raw blob. The writer registers each blob as a deduplicated media
part, adds an ``RT_IMAGE`` relationship from the new slide part, and
byte-replaces the temporary tokens with the real rIds before the slide part
is stored.
"""

from __future__ import annotations

import hashlib
import posixpath
import xml.etree.ElementTree as ET

from .errors import BuildError
from .model import TemplateInfo
from .opc import (
    CT_CORE_PROPS,
    CT_EXT_PROPS,
    CT_SLIDE,
    Package,
    RT_CORE_PROPS,
    RT_EXTENDED_PROPS,
    RT_IMAGE,
    RT_SLIDE,
    RT_SLIDE_LAYOUT,
)
from .shapes import detect_image
from .xmlcore import el, find, findall, parse_xml, qn, serialize, sub

#: Template for new slide partnames (filled via ``Package.next_partname``).
_SLIDE_TEMPLATE = "/ppt/slides/slide{}.xml"

#: Slide ids in ``p:sldIdLst`` must be >= 256 and < 2147483648.
_SLIDE_ID_FLOOR = 255
_SLIDE_ID_LIMIT = 2147483648

#: Fixed timestamp used for deterministic docProps output.
_FIXED_TIMESTAMP = "2026-01-01T00:00:00Z"

#: Partname used when a package has no core-properties part yet.
_DEFAULT_CORE_PARTNAME = "/docProps/core.xml"

#: Elements that may follow ``p:sldIdLst`` inside ``p:presentation``
#: (ECMA-376 schema order); used to insert a missing list at a valid spot.
_SLD_ID_LST_FOLLOWERS = (
    "p:sldSz",
    "p:notesSz",
    "p:smartTags",
    "p:embeddedFontLst",
    "p:custShowLst",
    "p:photoAlbum",
    "p:custDataLst",
    "p:kinsoku",
    "p:defaultTextStyle",
    "p:modifyVerifier",
    "p:extLst",
)

#: Child order of ``cp:coreProperties`` (ECMA-376 Part 2 schema sequence).
_CORE_CHILD_ORDER = (
    "cp:category",
    "cp:contentStatus",
    "dcterms:created",
    "dc:creator",
    "dc:description",
    "dc:identifier",
    "cp:keywords",
    "dc:language",
    "cp:lastModifiedBy",
    "cp:lastPrinted",
    "dcterms:modified",
    "cp:revision",
    "dc:subject",
    "dc:title",
    "cp:version",
)

_APP_CHILD_ORDER = (
    "ep:Application",
    "ep:PresentationFormat",
    "ep:Slides",
    "ep:HeadingPairs",
    "ep:TitlesOfParts",
)

_DEFAULT_APP_PARTNAME = "/docProps/app.xml"


class SlideWriter:
    """Appends slides and media parts to an open package.

    One writer instance is bound to a package (and the template model parsed
    from it) and keeps a SHA-256 index of all media blobs so identical images
    are stored only once, even across multiple slides.
    """

    def __init__(self, package: Package, info: TemplateInfo) -> None:
        """Bind the writer to a package and its parsed template model.

        Existing parts under ``/ppt/media/`` are indexed by content hash so
        :meth:`add_image` can deduplicate against pre-existing template media.
        """
        self.package = package
        self.info = info
        self._image_index: dict[str, str] = {}
        for part in package.parts():
            if part.partname.startswith("/ppt/media/"):
                digest = hashlib.sha256(part.blob).hexdigest()
                self._image_index.setdefault(digest, part.partname)

    def add_slide(
        self,
        slide_xml: bytes,
        layout_partname: str,
        pending_images: list[tuple[str, bytes]] | None = None,
    ) -> str:
        """Add one finished slide to the package and return its partname.

        Performs the full section-1 checklist: slide part, slide rels
        (layout + images), content-type override, presentation rel, and
        ``p:sldIdLst`` entry. ``pending_images`` pairs temporary relationship
        tokens (``"img:N"``) with image blobs; every token in ``slide_xml``
        is byte-replaced with the real rId before the part is stored.

        Args:
            slide_xml: Serialized ``<p:sld>`` part bytes (from
                ``SlideBuilder.to_xml``), possibly containing temporary
                ``r:embed="img:N"`` tokens.
            layout_partname: Absolute partname of the layout the slide is
                based on (must exist in the package).
            pending_images: ``[(temp_rid, blob), ...]`` or ``None``.

        Returns:
            The new slide partname, e.g. ``"/ppt/slides/slide1.xml"``.

        Raises:
            BuildError: If the layout part does not exist, an image blob has
                an unsupported format, or slide ids are exhausted.
        """
        if not self.package.has_part(layout_partname):
            raise BuildError(
                f"Cannot add slide: layout part {layout_partname!r} does not "
                f"exist in the package"
            )
        # Step 1+2: slide partname and its relationships.
        slide_partname = self.package.next_partname(_SLIDE_TEMPLATE)
        slide_dir = posixpath.dirname(slide_partname)
        slide_rels = self.package.rels(slide_partname)
        slide_rels.add(
            RT_SLIDE_LAYOUT, posixpath.relpath(layout_partname, slide_dir)
        )
        # Media parts + image rels; replace temp tokens BEFORE storing the part.
        for temp_rid, blob in pending_images or []:
            media_partname = self.add_image(blob)
            target = posixpath.relpath(media_partname, slide_dir)
            rid = None
            for rel in slide_rels.by_type(RT_IMAGE):
                if rel.target == target:
                    rid = rel.rid
                    break
            if rid is None:
                rid = slide_rels.add(RT_IMAGE, target)
            slide_xml = slide_xml.replace(
                f'"{temp_rid}"'.encode("ascii"), f'"{rid}"'.encode("ascii")
            )
        # Step 3: add_part registers the CT_SLIDE override automatically.
        self.package.add_part(slide_partname, CT_SLIDE, slide_xml)
        # Step 4: RT_SLIDE relationship from presentation.xml.
        pres_partname = self.package.main_part().partname
        pres_dir = posixpath.dirname(pres_partname)
        pres_rid = self.package.rels(pres_partname).add(
            RT_SLIDE, posixpath.relpath(slide_partname, pres_dir)
        )
        # Step 5: append <p:sldId> to p:sldIdLst and write the blob back.
        slide_id = self._next_slide_id()
        root = parse_xml(self.package.part(pres_partname).blob)
        sld_id_lst = self._sld_id_lst(root)
        sub(sld_id_lst, "p:sldId", {"id": str(slide_id), "r:id": pres_rid})
        self.package.replace_blob(pres_partname, serialize(root))
        return slide_partname

    def add_image(self, blob: bytes) -> str:
        """Store an image blob as a media part and return its partname.

        Identical blobs (by SHA-256) are stored only once; repeated calls
        return the existing partname. The image format is sniffed via
        :func:`slidewriting.shapes.detect_image`, a ``<Default>`` content type
        is registered for the extension, and the partname is allocated as
        ``/ppt/media/imageN.<ext>`` via ``Package.next_partname``.

        Raises:
            BuildError: For unsupported or corrupt image data.
        """
        digest = hashlib.sha256(blob).hexdigest()
        existing = self._image_index.get(digest)
        if existing is not None:
            return existing
        ext, content_type, _width, _height = detect_image(blob)
        self.package.default_content_type(ext, content_type)
        partname = self.package.next_partname(f"/ppt/media/image{{}}.{ext}")
        self.package.add_part(partname, content_type, blob)
        self._image_index[digest] = partname
        return partname

    def _next_slide_id(self) -> int:
        """Next numeric slide id: ``max(existing ids, 255) + 1``.

        Slide ids live in ``p:sldIdLst`` of ``presentation.xml`` and must be
        >= 256 and < 2147483648. Raises :class:`BuildError` when the id space
        is exhausted.
        """
        pres_part = self.package.main_part()
        root = parse_xml(pres_part.blob)
        highest = _SLIDE_ID_FLOOR
        for sld_id in findall(root, "p:sldIdLst/p:sldId"):
            raw = sld_id.get("id")
            if raw is not None and raw.isdigit():
                highest = max(highest, int(raw))
        next_id = highest + 1
        if next_id >= _SLIDE_ID_LIMIT:
            raise BuildError(
                f"Slide id space exhausted: next id {next_id} would exceed "
                f"the maximum of {_SLIDE_ID_LIMIT - 1}"
            )
        return next_id

    @staticmethod
    def _sld_id_lst(presentation_root: ET.Element) -> ET.Element:
        """Return ``p:sldIdLst``, inserting an empty one at a valid position.

        When the list is missing it is inserted before the first child that
        the schema places after it (``p:sldSz``, ``p:notesSz``, ...), or
        appended if no such child exists.
        """
        node = find(presentation_root, "p:sldIdLst")
        if node is not None:
            return node
        followers = {qn(tag) for tag in _SLD_ID_LST_FOLLOWERS}
        insert_at = len(presentation_root)
        for index, child in enumerate(presentation_root):
            if child.tag in followers:
                insert_at = index
                break
        node = el("p:sldIdLst")
        presentation_root.insert(insert_at, node)
        return node


def set_core_properties(
    package: Package, title: str, creator: str = "Slide Writing"
) -> None:
    """Write ``dc:title``, ``dc:creator``, and ``cp:lastModifiedBy``.

    Updates the existing ``docProps/core.xml`` in place. If the package has
    no core-properties part yet, a complete one is created (including the
    fixed ``dcterms:created``/``dcterms:modified`` timestamps with
    ``xsi:type``), registered with its content-type override, and wired up
    with a package-level ``RT_CORE_PROPS`` relationship.
    """
    pkg_rels = package.rels(None)
    core_rels = pkg_rels.by_type(RT_CORE_PROPS)
    if core_rels:
        partname = pkg_rels.resolve(core_rels[0].target)
    else:
        partname = _DEFAULT_CORE_PARTNAME
    exists = package.has_part(partname)
    if exists:
        root = parse_xml(package.part(partname).blob)
    else:
        root = el("cp:coreProperties")
        for tag in ("dcterms:created", "dcterms:modified"):
            node = _ensure_core_child(root, tag)
            node.set(qn("xsi:type"), "dcterms:W3CDTF")
            node.text = _FIXED_TIMESTAMP
    _ensure_core_child(root, "dc:title").text = title
    _ensure_core_child(root, "dc:creator").text = creator
    _ensure_core_child(root, "cp:lastModifiedBy").text = creator
    blob = serialize(root)
    if exists:
        package.replace_blob(partname, blob)
    else:
        package.add_part(partname, CT_CORE_PROPS, blob)
    if not core_rels:
        pkg_rels.add(RT_CORE_PROPS, partname.lstrip("/"))


def _ensure_core_child(root: ET.Element, tag: str) -> ET.Element:
    """Return the child ``tag`` of ``cp:coreProperties``, creating it in order.

    A missing element is inserted at its position in the ECMA-376 core
    properties sequence so the part stays schema-valid.
    """
    node = find(root, tag)
    if node is not None:
        return node
    order = [qn(entry) for entry in _CORE_CHILD_ORDER]
    position = order.index(qn(tag))
    insert_at = len(root)
    for index, child in enumerate(root):
        if child.tag in order and order.index(child.tag) > position:
            insert_at = index
            break
    node = el(tag)
    root.insert(insert_at, node)
    return node


def set_app_properties(package: Package, slide_count: int, title: str) -> None:
    """Write slide count and title metadata to ``docProps/app.xml``."""
    pkg_rels = package.rels(None)
    app_rels = pkg_rels.by_type(RT_EXTENDED_PROPS)
    if app_rels:
        partname = pkg_rels.resolve(app_rels[0].target)
    else:
        partname = _DEFAULT_APP_PARTNAME
    exists = package.has_part(partname)
    root = parse_xml(package.part(partname).blob) if exists else el("ep:Properties")
    _ensure_app_child(root, "ep:Application").text = "Slide Writing"
    _ensure_app_child(root, "ep:Slides").text = str(slide_count)
    _set_titles_of_parts(root, title)
    blob = serialize(root)
    if exists:
        package.replace_blob(partname, blob)
    else:
        package.add_part(partname, CT_EXT_PROPS, blob)
    if not app_rels:
        pkg_rels.add(RT_EXTENDED_PROPS, partname.lstrip("/"))


def _ensure_app_child(root: ET.Element, tag: str) -> ET.Element:
    """Return the child ``tag`` of ``ep:Properties``, creating it in order."""
    node = find(root, tag)
    if node is not None:
        return node
    order = [qn(entry) for entry in _APP_CHILD_ORDER]
    position = order.index(qn(tag))
    insert_at = len(root)
    for index, child in enumerate(root):
        if child.tag in order and order.index(child.tag) > position:
            insert_at = index
            break
    node = el(tag)
    root.insert(insert_at, node)
    return node


def _set_titles_of_parts(root: ET.Element, title: str) -> None:
    """Set ``ep:TitlesOfParts`` to a one-item vector with the deck title."""
    titles = _ensure_app_child(root, "ep:TitlesOfParts")
    titles.clear()
    vector = sub(titles, "vt:vector", {"size": "1", "baseType": "lpstr"})
    sub(vector, "vt:lpstr", text=title)
