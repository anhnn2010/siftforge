"""Stable JSON serialization for EPUB-ready semantic documents."""

from __future__ import annotations

from typing import Any

from .models import (
    SemanticAttribution,
    SemanticBookDocument,
    SemanticFigure,
    SemanticFlowNode,
    SemanticFootnote,
    SemanticHeading,
    SemanticInline,
    SemanticInset,
    SemanticList,
    SemanticParagraph,
    SemanticQuotation,
    SemanticVerse,
)


def semantic_book_to_dict(document: SemanticBookDocument) -> dict[str, Any]:
    """Serialize semantic ebook content into deterministic JSON data."""
    return {
        "title": document.title,
        "language": document.language,
        "author": document.author,
        "nodes": [_node_to_dict(node) for node in document.nodes],
        "relationships": [
            {
                "kind": relationship.kind,
                "source_id": relationship.source_id,
                "target_id": relationship.target_id,
            }
            for relationship in document.relationships
        ],
    }


def _node_to_dict(node: SemanticFlowNode) -> dict[str, Any]:
    """Serialize one supported semantic flow node."""
    if isinstance(node, SemanticParagraph):
        return _text_node("paragraph", node.node_id, node.content)
    if isinstance(node, SemanticHeading):
        payload = _text_node("heading", node.node_id, node.content)
        payload["role"] = node.role.value
        payload["level"] = node.level
        return payload
    if isinstance(node, SemanticList):
        return {
            "type": "list",
            "node_id": node.node_id,
            "kind": node.kind.value,
            "items": [
                {
                    "node_id": item.node_id,
                    "ordinal": item.ordinal,
                    "content": [_inline_to_dict(value) for value in item.content],
                }
                for item in node.items
            ],
        }
    if isinstance(node, SemanticVerse):
        return {
            "type": "verse",
            "node_id": node.node_id,
            "lines": [
                {
                    "node_id": line.node_id,
                    "content": [_inline_to_dict(value) for value in line.content],
                }
                for line in node.lines
            ],
        }
    if isinstance(node, SemanticQuotation):
        return {
            "type": "quotation",
            "node_id": node.node_id,
            "children": [_node_to_dict(child) for child in node.children],
        }
    if isinstance(node, SemanticFigure):
        return {
            "type": "figure",
            "node_id": node.node_id,
            "asset_id": node.asset_id,
            "caption": [_inline_to_dict(value) for value in node.caption],
        }
    if isinstance(node, SemanticInset):
        return {
            "type": "inset",
            "node_id": node.node_id,
            "role": node.role.value,
            "children": [_node_to_dict(child) for child in node.children],
        }
    if isinstance(node, SemanticFootnote):
        payload = _text_node("footnote", node.node_id, node.content)
        payload["label"] = node.label
        return payload
    if isinstance(node, SemanticAttribution):
        return _text_node("attribution", node.node_id, node.content)
    raise TypeError(f"unsupported semantic node: {type(node).__name__}")


def _text_node(
    node_type: str,
    node_id: str,
    content: tuple[SemanticInline, ...],
) -> dict[str, Any]:
    """Serialize one semantic text node."""
    return {
        "type": node_type,
        "node_id": node_id,
        "content": [_inline_to_dict(value) for value in content],
    }


def _inline_to_dict(value: SemanticInline) -> dict[str, Any]:
    """Serialize one semantic inline fragment."""
    return {
        "text": value.text,
        "language": value.language,
        "marks": [mark.value for mark in value.marks],
        "presentations": [item.value for item in value.presentations],
        "role": value.role.value,
        "target_id": value.target_id,
        "source_span_id": value.source_span_id,
    }
