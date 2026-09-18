"""EPUB-ready semantic ebook projection."""

from .models import (
    InlinePresentation,
    InlineRole,
    SemanticAttribution,
    SemanticBookDocument,
    SemanticFigure,
    SemanticFlowNode,
    SemanticFootnote,
    SemanticHeading,
    SemanticInline,
    SemanticInset,
    SemanticList,
    SemanticListItem,
    SemanticParagraph,
    SemanticQuotation,
    SemanticRelationship,
    SemanticVerse,
    SemanticVerseLine,
)
from .projector import (
    EbookSemanticProjector,
    SemanticProjectionError,
    SemanticProjectionResult,
)
from .serialization import semantic_book_to_dict

__all__: list[str] = [
    "EbookSemanticProjector",
    "InlinePresentation",
    "InlineRole",
    "SemanticAttribution",
    "SemanticBookDocument",
    "SemanticFigure",
    "SemanticFlowNode",
    "SemanticFootnote",
    "SemanticHeading",
    "SemanticInline",
    "SemanticInset",
    "SemanticList",
    "SemanticListItem",
    "SemanticParagraph",
    "SemanticProjectionError",
    "SemanticProjectionResult",
    "SemanticQuotation",
    "SemanticRelationship",
    "SemanticVerse",
    "SemanticVerseLine",
    "semantic_book_to_dict",
]
