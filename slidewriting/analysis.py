"""Deep slide/deck analysis for uploaded PowerPoint files."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .model import SlideInfo, TemplateInfo
from .opc import RT_CHART, Package, Relationships
from .shapes import detect_image
from .xmlcore import find, findall, get, parse_xml, qn

TABLE_URI = "http://schemas.openxmlformats.org/drawingml/2006/table"
CHART_URI = "http://schemas.openxmlformats.org/drawingml/2006/chart"


def analyze_deck(package: Package, info: TemplateInfo) -> dict:
    """Return a deep JSON-serializable analysis for a parsed deck."""
    slides = [analyze_slide(package, slide) for slide in info.slides]
    totals = {
        "slides": len(slides),
        "shapes": sum(item["counts"]["shapes"] for item in slides),
        "text_shapes": sum(item["counts"]["text_shapes"] for item in slides),
        "images": sum(item["counts"]["images"] for item in slides),
        "tables": sum(item["counts"]["tables"] for item in slides),
        "charts": sum(item["counts"]["charts"] for item in slides),
        "connectors": sum(item["counts"]["connectors"] for item in slides),
        "groups": sum(item["counts"]["groups"] for item in slides),
    }
    return {
        "summary": {
            "slide_size": [info.slide_width, info.slide_height],
            "masters": len(info.masters),
            "layouts": len(info.layouts),
            "slides": len(info.slides),
        },
        "slides": slides,
        "totals": totals,
    }


def analyze_slide(package: Package, slide: SlideInfo) -> dict:
    """Return a deep record for a single existing slide."""
    root = parse_xml(package.part(slide.partname).blob)
    rels = package.rels(slide.partname)
    sp_tree = find(root, "p:cSld/p:spTree")
    shape_records = []
    if sp_tree is not None:
        for child in list(sp_tree):
            if _local_name(child.tag) in {"nvGrpSpPr", "grpSpPr"}:
                continue
            shape_records.extend(_shape_records(child, rels, package))

    slide_text_parts = [item["text"] for item in shape_records if item.get("text")]
    counts = {
        "shapes": len(shape_records),
        "text_shapes": sum(1 for item in shape_records if item.get("text")),
        "images": sum(1 for item in shape_records if item.get("kind") == "image"),
        "tables": sum(1 for item in shape_records if item.get("kind") == "table"),
        "charts": sum(1 for item in shape_records if item.get("kind") == "chart"),
        "connectors": sum(1 for item in shape_records if item.get("kind") == "connector"),
        "groups": sum(1 for item in shape_records if item.get("kind") == "group"),
    }
    return {
        "partname": slide.partname,
        "layout": slide.layout_partname,
        "title": slide.title,
        "text": "\n".join(slide_text_parts),
        "shapes": shape_records,
        "counts": counts,
    }


def _shape_records(node: ET.Element, slide_rels: Relationships, package: Package) -> list[dict]:
    local = _local_name(node.tag)
    if local == "grpSp":
        group_box = _box_from_node(node)
        children = []
        for child in list(node):
            if _local_name(child.tag) in {"nvGrpSpPr", "grpSpPr"}:
                continue
            children.extend(_shape_records(child, slide_rels, package))
        text = "\n".join(item["text"] for item in children if item.get("text"))
        return [
            {
                "id": _shape_id(node),
                "name": _shape_name(node),
                "kind": "group",
                "tag": "p:grpSp",
                "box": group_box,
                "text": text or None,
                "children": children,
            }
        ]
    return [_shape_record(node, slide_rels, package)]


def _shape_record(node: ET.Element, slide_rels: Relationships, package: Package) -> dict:
    local = _local_name(node.tag)
    record = {
        "id": _shape_id(node),
        "name": _shape_name(node),
        "tag": _prefixed_tag(node.tag),
        "box": _box_from_node(node),
    }
    if local == "sp":
        record["kind"] = "placeholder" if find(node, "p:nvSpPr/p:nvPr/p:ph") is not None else "shape"
        placeholder = find(node, "p:nvSpPr/p:nvPr/p:ph")
        if placeholder is not None:
            record["placeholder"] = {
                "type": placeholder.get("type", "body"),
                "idx": _int_or_none(placeholder.get("idx")),
            }
        text = _text_from_shape(node)
        if text:
            record["text"] = text
        return record
    if local == "pic":
        record["kind"] = "image"
        image = _image_record(node, slide_rels, package)
        if image:
            record["image"] = image
        return record
    if local == "cxnSp":
        record["kind"] = "connector"
        text = _text_from_shape(node)
        if text:
            record["text"] = text
        return record
    if local == "graphicFrame":
        graphic_data = find(node, "a:graphic/a:graphicData")
        uri = graphic_data.get("uri", "") if graphic_data is not None else ""
        if uri == TABLE_URI:
            record["kind"] = "table"
            table = find(graphic_data, "a:tbl") if graphic_data is not None else None
            record.update(_table_record(table))
            return record
        chart = find(graphic_data, "c:chart") if graphic_data is not None else None
        if uri == CHART_URI or chart is not None:
            record["kind"] = "chart"
            if chart is not None:
                rid = get(chart, "r:id")
                record["chart"] = _chart_record(rid, slide_rels)
            return record
        record["kind"] = "graphicFrame"
        text = _text_from_shape(node)
        if text:
            record["text"] = text
        return record
    record["kind"] = local
    text = _text_from_shape(node)
    if text:
        record["text"] = text
    return record


def _image_record(node: ET.Element, slide_rels: Relationships, package: Package) -> dict | None:
    blip = find(node, "p:blipFill/a:blip")
    rid = get(blip, "r:embed") if blip is not None else None
    if not rid:
        return None
    rel = slide_rels.get(rid)
    if rel is None:
        return {"rid": rid, "missing": True}
    partname = slide_rels.resolve(rel.target)
    part = package.part(partname)
    payload = {
        "rid": rid,
        "partname": partname,
        "content_type": part.content_type,
    }
    try:
        _ext, _ctype, width, height = detect_image(part.blob)
        payload["px_size"] = [width, height]
    except Exception:
        pass
    return payload


def _table_record(table: ET.Element | None) -> dict:
    if table is None:
        return {}
    rows = findall(table, "a:tr")
    cols = findall(table, "a:tblGrid/a:gridCol")
    texts = []
    for txbody in findall(table, ".//a:txBody"):
        text = _text_from_txbody(txbody)
        if text:
            texts.append(text)
    return {
        "rows": len(rows),
        "cols": len(cols),
        "text": "\n".join(texts) if texts else None,
    }


def _chart_record(rid: str | None, slide_rels: Relationships) -> dict:
    if not rid:
        return {"missing": True}
    rel = slide_rels.get(rid)
    if rel is None:
        return {"rid": rid, "missing": True}
    return {
        "rid": rid,
        "relationship_type": rel.rtype,
        "partname": slide_rels.resolve(rel.target),
        "is_native_chart": rel.rtype == RT_CHART,
    }


def _text_from_shape(node: ET.Element) -> str | None:
    texts = []
    for txbody in findall(node, ".//p:txBody"):
        text = _text_from_txbody(txbody)
        if text:
            texts.append(text)
    for txbody in findall(node, ".//a:txBody"):
        text = _text_from_txbody(txbody)
        if text:
            texts.append(text)
    if not texts:
        return None
    return "\n".join(texts)


def _text_from_txbody(txbody: ET.Element) -> str | None:
    paragraphs = []
    for para in findall(txbody, "a:p"):
        parts = []
        for text_node in findall(para, ".//a:t"):
            if text_node.text:
                parts.append(text_node.text)
        line = "".join(parts).strip()
        if line:
            paragraphs.append(line)
    if not paragraphs:
        return None
    return "\n".join(paragraphs)


def _box_from_node(node: ET.Element) -> list[int] | None:
    xfrm = None
    for path in ("p:spPr/a:xfrm", "p:xfrm", "p:grpSpPr/a:xfrm"):
        xfrm = find(node, path)
        if xfrm is not None:
            break
    if xfrm is None:
        return None
    off = find(xfrm, "a:off")
    ext = find(xfrm, "a:ext")
    if off is None or ext is None:
        return None
    try:
        return [
            int(off.get("x", "")),
            int(off.get("y", "")),
            int(ext.get("cx", "")),
            int(ext.get("cy", "")),
        ]
    except ValueError:
        return None


def _shape_id(node: ET.Element) -> int | None:
    c_nv_pr = _c_nv_pr(node)
    return _int_or_none(c_nv_pr.get("id")) if c_nv_pr is not None else None


def _shape_name(node: ET.Element) -> str | None:
    c_nv_pr = _c_nv_pr(node)
    return c_nv_pr.get("name") if c_nv_pr is not None else None


def _c_nv_pr(node: ET.Element) -> ET.Element | None:
    for path in (
        "p:nvSpPr/p:cNvPr",
        "p:nvPicPr/p:cNvPr",
        "p:nvCxnSpPr/p:cNvPr",
        "p:nvGraphicFramePr/p:cNvPr",
        "p:nvGrpSpPr/p:cNvPr",
    ):
        match = find(node, path)
        if match is not None:
            return match
    return None


def _int_or_none(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _prefixed_tag(tag: str) -> str:
    for prefix, expanded in (
        ("p", qn("p:sld").split("}")[0] + "}"),
        ("a", qn("a:t").split("}")[0] + "}"),
        ("c", qn("c:chart").split("}")[0] + "}"),
    ):
        if tag.startswith(expanded):
            return f"{prefix}:{tag.split('}', 1)[1]}"
    return tag
