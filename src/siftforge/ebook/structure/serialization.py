"""Stable JSON serialization for pagination-independent ebook structure."""

from __future__ import annotations

from typing import Any

from siftforge.ebook.evidence import MarkerEvidence, NormalizedRegion, SourceTypography

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
    ImageNode,
    InsetNode,
    ListItemNode,
    ListNode,
    ParagraphNode,
    QuotationNode,
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
