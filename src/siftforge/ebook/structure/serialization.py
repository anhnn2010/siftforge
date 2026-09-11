"""Stable JSON serialization for pagination-independent ebook structure."""

from __future__ import annotations

import math
from typing import Any

from siftforge.ebook.evidence import (
    MarkerEvidence,
    MarkerKind,
    NormalizedRegion,
    SourceTypography,
)
from siftforge.ebook.models import (
    CapsStyle,
    FontPosture,
    FontWeight,
    TextDecoration,
    VerticalPosition,
)

from .models import (
    AttributionNode,
    BookDocument,
    CaptionNode,
    DocumentRelationship,
    DocumentTextSpan,
    FigureNode,
    FlowNode,
    FootnoteNode,
    HeadingNode,
    HeadingRole,
    ImageNode,
    InsetNode,
    InsetRole,
    ListItemNode,
    ListKind,
    ListNode,
    ParagraphNode,
    QuotationNode,
    RelationshipKind,
    SemanticMark,
    SourceFragment,
    VerseLineNode,
    VerseNode,
)


def book_document_to_dict(document: BookDocument) -> dict[str, Any]:
    """Serialize one logical book document into deterministic JSON data."""
    return {
        "nodes": [_node_to_dict(node) for node in document.nodes],
        "relationships": [
            _relationship_to_dict(relationship)
            for relationship in document.relationships
        ],
    }


def _node_to_dict(node: FlowNode) -> dict[str, Any]:
    """Serialize one supported flow node with an explicit type discriminator."""
    if isinstance(node, ParagraphNode):
        return _text_node("paragraph", node.node_id, node.spans, node.provenance)
    if isinstance(node, HeadingNode):
        payload = _text_node("heading", node.node_id, node.spans, node.provenance)
        payload["role"] = node.role.value
        payload["level"] = node.level
        return payload
    if isinstance(node, FootnoteNode):
        payload = _text_node("footnote", node.node_id, node.spans, node.provenance)
        payload["label"] = node.label
        return payload
    if isinstance(node, AttributionNode):
        return _text_node(
            "attribution",
            node.node_id,
            node.spans,
            node.provenance,
        )
    if isinstance(node, ListNode):
        return {
            "type": "list",
            "node_id": node.node_id,
            "kind": node.kind.value,
            "items": [_list_item_to_dict(item) for item in node.items],
            "provenance": [_fragment_to_dict(item) for item in node.provenance],
        }
    if isinstance(node, VerseNode):
        return {
            "type": "verse",
            "node_id": node.node_id,
            "lines": [_verse_line_to_dict(line) for line in node.lines],
            "provenance": [_fragment_to_dict(item) for item in node.provenance],
        }
    if isinstance(node, QuotationNode):
        return {
            "type": "quotation",
            "node_id": node.node_id,
            "children": [_node_to_dict(child) for child in node.children],
            "provenance": [_fragment_to_dict(item) for item in node.provenance],
        }
    if isinstance(node, FigureNode):
        return _figure_to_dict(node)
    if isinstance(node, InsetNode):
        return {
            "type": "inset",
            "node_id": node.node_id,
            "role": node.role.value,
            "children": [_node_to_dict(child) for child in node.children],
            "provenance": [_fragment_to_dict(item) for item in node.provenance],
        }
    raise TypeError(f"unsupported flow node type: {type(node).__name__}")


def _text_node(
    node_type: str,
    node_id: str,
    spans: tuple[DocumentTextSpan, ...],
    provenance: tuple[SourceFragment, ...],
) -> dict[str, Any]:
    """Serialize a logical node whose primary content is text spans."""
    return {
        "type": node_type,
        "node_id": node_id,
        "spans": [_span_to_dict(span) for span in spans],
        "provenance": [_fragment_to_dict(item) for item in provenance],
    }


def _list_item_to_dict(item: ListItemNode) -> dict[str, Any]:
    """Serialize one logical list item."""
    return {
        "node_id": item.node_id,
        "spans": [_span_to_dict(span) for span in item.spans],
        "marker": _marker_to_dict(item.marker),
        "ordinal": item.ordinal,
        "provenance": [_fragment_to_dict(value) for value in item.provenance],
    }


def _verse_line_to_dict(line: VerseLineNode) -> dict[str, Any]:
    """Serialize one semantic verse line."""
    return {
        "node_id": line.node_id,
        "spans": [_span_to_dict(span) for span in line.spans],
        "provenance": [_fragment_to_dict(value) for value in line.provenance],
    }


def _figure_to_dict(figure: FigureNode) -> dict[str, Any]:
    """Serialize one figure, its renderable asset, and optional caption."""
    return {
        "type": "figure",
        "node_id": figure.node_id,
        "image": _image_to_dict(figure.image),
        "caption": (
            _caption_to_dict(figure.caption)
            if figure.caption is not None
            else None
        ),
        "provenance": [
            _fragment_to_dict(value) for value in figure.provenance
        ],
    }


def _image_to_dict(image: ImageNode) -> dict[str, Any]:
    """Serialize a logical image and its source crop region."""
    return {
        "node_id": image.node_id,
        "source_region": _region_to_dict(image.source_region),
        "asset_id": image.asset_id,
        "provenance": [_fragment_to_dict(value) for value in image.provenance],
    }


def _caption_to_dict(caption: CaptionNode) -> dict[str, Any]:
    """Serialize a figure caption."""
    return {
        "node_id": caption.node_id,
        "spans": [_span_to_dict(span) for span in caption.spans],
        "provenance": [
            _fragment_to_dict(value) for value in caption.provenance
        ],
    }


def _span_to_dict(span: DocumentTextSpan) -> dict[str, Any]:
    """Serialize logical text while retaining source typography and lineage."""
    return {
        "span_id": span.span_id,
        "text": span.text,
        "language": span.language,
        "source_typography": _typography_to_dict(span.source_typography),
        "semantic_marks": [mark.value for mark in span.semantic_marks],
        "provenance": [_fragment_to_dict(value) for value in span.provenance],
    }


def _typography_to_dict(typography: SourceTypography) -> dict[str, Any]:
    """Serialize source typography without implying semantic emphasis."""
    return {
        "posture": typography.posture.value,
        "weight": typography.weight.value,
        "vertical_position": typography.vertical_position.value,
        "caps_style": typography.caps_style.value,
        "decorations": [value.value for value in typography.decorations],
    }


def _marker_to_dict(marker: MarkerEvidence | None) -> dict[str, Any] | None:
    """Serialize optional visual marker evidence."""
    if marker is None:
        return None
    return {
        "kind": marker.kind.value,
        "raw_text": marker.raw_text,
        "ordinal": marker.ordinal,
    }


def _region_to_dict(region: NormalizedRegion) -> dict[str, float]:
    """Serialize normalized source coordinates."""
    return {
        "x": region.x,
        "y": region.y,
        "width": region.width,
        "height": region.height,
    }


def _fragment_to_dict(fragment: SourceFragment) -> dict[str, Any]:
    """Serialize one source-lineage fragment."""
    return {
        "page_id": fragment.page_id,
        "block_id": fragment.block_id,
        "span_ids": list(fragment.span_ids),
    }


def _relationship_to_dict(
    relationship: DocumentRelationship,
) -> dict[str, Any]:
    """Serialize one semantic or continuation relationship."""
    return {
        "relationship_id": relationship.relationship_id,
        "kind": relationship.kind.value,
        "source_id": relationship.source_id,
        "target_id": relationship.target_id,
        "confidence": relationship.confidence,
        "reasons": list(relationship.reasons),
    }


def book_document_from_dict(payload: dict[str, Any]) -> BookDocument:
    """Deserialize one canonical ``BookDocument`` JSON object.

    This loader is intended for SiftForge's own persisted assembly artifacts.
    It validates explicit type discriminators and enum values while preserving
    all semantic relationships and source provenance.
    """
    nodes_value = _required_list(payload, "nodes")
    relationships_value = _required_list(payload, "relationships")
    return BookDocument(
        nodes=tuple(_node_from_dict(_required_dict(value)) for value in nodes_value),
        relationships=tuple(
            _relationship_from_dict(_required_dict(value))
            for value in relationships_value
        ),
    )


def _node_from_dict(payload: dict[str, Any]) -> FlowNode:
    """Deserialize one canonical structural flow node."""
    node_type = _required_str(payload, "type")
    node_id = _required_str(payload, "node_id")
    provenance = _fragments_from_value(payload.get("provenance", []))
    if node_type == "paragraph":
        return ParagraphNode(
            node_id=node_id,
            spans=_spans_from_value(payload.get("spans", [])),
            provenance=provenance,
        )
    if node_type == "heading":
        return HeadingNode(
            node_id=node_id,
            spans=_spans_from_value(payload.get("spans", [])),
            role=HeadingRole(_required_str(payload, "role")),
            level=_optional_int(payload.get("level")),
            provenance=provenance,
        )
    if node_type == "footnote":
        return FootnoteNode(
            node_id=node_id,
            spans=_spans_from_value(payload.get("spans", [])),
            label=_optional_str(payload.get("label")),
            provenance=provenance,
        )
    if node_type == "attribution":
        return AttributionNode(
            node_id=node_id,
            spans=_spans_from_value(payload.get("spans", [])),
            provenance=provenance,
        )
    if node_type == "list":
        return ListNode(
            node_id=node_id,
            kind=ListKind(_required_str(payload, "kind")),
            items=tuple(
                _list_item_from_dict(_required_dict(value))
                for value in _required_list(payload, "items")
            ),
            provenance=provenance,
        )
    if node_type == "verse":
        return VerseNode(
            node_id=node_id,
            lines=tuple(
                _verse_line_from_dict(_required_dict(value))
                for value in _required_list(payload, "lines")
            ),
            provenance=provenance,
        )
    if node_type == "quotation":
        return QuotationNode(
            node_id=node_id,
            children=tuple(
                _node_from_dict(_required_dict(value))
                for value in _required_list(payload, "children")
            ),
            provenance=provenance,
        )
    if node_type == "figure":
        return _figure_from_dict(payload, provenance)
    if node_type == "inset":
        return InsetNode(
            node_id=node_id,
            role=InsetRole(_required_str(payload, "role")),
            children=tuple(
                _node_from_dict(_required_dict(value))
                for value in _required_list(payload, "children")
            ),
            provenance=provenance,
        )
    raise ValueError(f"unsupported structural node type: {node_type!r}")


def _list_item_from_dict(payload: dict[str, Any]) -> ListItemNode:
    """Deserialize one list item."""
    marker_value = payload.get("marker")
    return ListItemNode(
        node_id=_required_str(payload, "node_id"),
        spans=_spans_from_value(payload.get("spans", [])),
        marker=(
            _marker_from_dict(_required_dict(marker_value))
            if marker_value is not None
            else None
        ),
        ordinal=_optional_int(payload.get("ordinal")),
        provenance=_fragments_from_value(payload.get("provenance", [])),
    )


def _verse_line_from_dict(payload: dict[str, Any]) -> VerseLineNode:
    """Deserialize one semantic verse line."""
    return VerseLineNode(
        node_id=_required_str(payload, "node_id"),
        spans=_spans_from_value(payload.get("spans", [])),
        provenance=_fragments_from_value(payload.get("provenance", [])),
    )


def _figure_from_dict(
    payload: dict[str, Any],
    provenance: tuple[SourceFragment, ...],
) -> FigureNode:
    """Deserialize one figure with source region and optional caption."""
    image = _image_from_dict(_required_dict(payload.get("image")))
    caption_value = payload.get("caption")
    caption = (
        _caption_from_dict(_required_dict(caption_value))
        if caption_value is not None
        else None
    )
    return FigureNode(
        node_id=_required_str(payload, "node_id"),
        image=image,
        caption=caption,
        provenance=provenance,
    )


def _image_from_dict(payload: dict[str, Any]) -> ImageNode:
    """Deserialize one source-backed logical image."""
    region = _required_dict(payload.get("source_region"))
    return ImageNode(
        node_id=_required_str(payload, "node_id"),
        source_region=NormalizedRegion(
            x=_required_number(region, "x"),
            y=_required_number(region, "y"),
            width=_required_number(region, "width"),
            height=_required_number(region, "height"),
        ),
        asset_id=_optional_str(payload.get("asset_id")),
        provenance=_fragments_from_value(payload.get("provenance", [])),
    )


def _caption_from_dict(payload: dict[str, Any]) -> CaptionNode:
    """Deserialize one figure caption."""
    return CaptionNode(
        node_id=_required_str(payload, "node_id"),
        spans=_spans_from_value(payload.get("spans", [])),
        provenance=_fragments_from_value(payload.get("provenance", [])),
    )


def _spans_from_value(value: Any) -> tuple[DocumentTextSpan, ...]:
    """Deserialize canonical logical text spans."""
    return tuple(
        _span_from_dict(_required_dict(item))
        for item in _required_list_value(value)
    )


def _span_from_dict(payload: dict[str, Any]) -> DocumentTextSpan:
    """Deserialize one logical text span and its explicit semantic marks."""
    typography = _required_dict(payload.get("source_typography"))
    return DocumentTextSpan(
        span_id=_required_str(payload, "span_id"),
        text=_required_str_allow_empty(payload, "text"),
        language=_optional_str(payload.get("language")),
        source_typography=SourceTypography(
            posture=FontPosture(_required_str(typography, "posture")),
            weight=FontWeight(_required_str(typography, "weight")),
            vertical_position=VerticalPosition(
                _required_str(typography, "vertical_position")
            ),
            caps_style=CapsStyle(_required_str(typography, "caps_style")),
            decorations=tuple(
                TextDecoration(_required_string_value(item))
                for item in _required_list(typography, "decorations")
            ),
        ),
        semantic_marks=tuple(
            SemanticMark(_required_string_value(item))
            for item in _required_list(payload, "semantic_marks")
        ),
        provenance=_fragments_from_value(payload.get("provenance", [])),
    )


def _marker_from_dict(payload: dict[str, Any]) -> MarkerEvidence:
    """Deserialize source marker evidence."""
    return MarkerEvidence(
        kind=MarkerKind(_required_str(payload, "kind")),
        raw_text=_optional_str(payload.get("raw_text")),
        ordinal=_optional_int(payload.get("ordinal")),
    )


def _fragments_from_value(value: Any) -> tuple[SourceFragment, ...]:
    """Deserialize source-lineage fragments."""
    return tuple(
        SourceFragment(
            page_id=_required_str(payload, "page_id"),
            block_id=_required_str(payload, "block_id"),
            span_ids=tuple(
                _required_string_value(item)
                for item in _required_list(payload, "span_ids")
            ),
        )
        for payload in (
            _required_dict(item) for item in _required_list_value(value)
        )
    )


def _relationship_from_dict(payload: dict[str, Any]) -> DocumentRelationship:
    """Deserialize one semantic or continuation relationship."""
    confidence = payload.get("confidence")
    if confidence is not None:
        confidence = _required_number_value(confidence)
    return DocumentRelationship(
        relationship_id=_required_str(payload, "relationship_id"),
        kind=RelationshipKind(_required_str(payload, "kind")),
        source_id=_required_str(payload, "source_id"),
        target_id=_required_str(payload, "target_id"),
        confidence=confidence,
        reasons=tuple(
            _required_string_value(item)
            for item in _required_list(payload, "reasons")
        ),
    )


def _required_dict(value: Any) -> dict[str, Any]:
    """Return one JSON object or raise a stable validation error."""
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def _required_list(payload: dict[str, Any], key: str) -> list[Any]:
    """Return one required JSON list field."""
    if key not in payload:
        raise ValueError(f"missing required field: {key}")
    return _required_list_value(payload[key])


def _required_list_value(value: Any) -> list[Any]:
    """Return one JSON list value."""
    if not isinstance(value, list):
        raise ValueError("expected JSON array")
    return value


def _required_str(payload: dict[str, Any], key: str) -> str:
    """Return one required non-empty string field."""
    if key not in payload:
        raise ValueError(f"missing required field: {key}")
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _required_str_allow_empty(payload: dict[str, Any], key: str) -> str:
    """Return one required string field that may be empty."""
    if key not in payload or not isinstance(payload[key], str):
        raise ValueError(f"{key} must be a string")
    return payload[key]


def _required_string_value(value: Any) -> str:
    """Return a list element only when it is a string."""
    if not isinstance(value, str):
        raise ValueError("expected string value")
    return value


def _optional_str(value: Any) -> str | None:
    """Validate an optional string field."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("expected optional string")
    return value


def _optional_int(value: Any) -> int | None:
    """Validate an optional integer without accepting booleans."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected optional integer")
    return value


def _required_number(payload: dict[str, Any], key: str) -> float:
    """Return one required finite JSON number as float."""
    if key not in payload:
        raise ValueError(f"missing required field: {key}")
    return _required_number_value(payload[key])


def _required_number_value(value: Any) -> float:
    """Validate a finite number without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected JSON number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("expected finite JSON number")
    return result
