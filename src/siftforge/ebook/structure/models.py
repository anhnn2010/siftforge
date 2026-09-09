"""Pagination-independent structural ebook-domain models.

The models in this module represent logical document structure after page-level
extraction evidence has been analyzed. Source page boundaries survive only as
provenance and must not define the logical reading structure of the ebook.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from siftforge.ebook.evidence import (
    MarkerEvidence,
    NormalizedRegion,
    SourceTypography,
)


class SemanticMark(StrEnum):
    """Semantic inline meaning independent of observed source typography."""

    EMPHASIS = "emphasis"
    STRONG = "strong"


class HeadingRole(StrEnum):
    """Resolved logical role of a heading."""

    CHAPTER_LABEL = "chapter_label"
    CHAPTER_TITLE = "chapter_title"
    SECTION_TITLE = "section_title"
    SUBSECTION_TITLE = "subsection_title"
    SUBTITLE = "subtitle"
    GENRE_LABEL = "genre_label"
    SCENARIO_LABEL = "scenario_label"
    SCENARIO_TITLE = "scenario_title"
    UNKNOWN = "unknown"


class ListKind(StrEnum):
    """Logical ordering behavior of a reconstructed list."""

    ORDERED = "ordered"
    UNORDERED = "unordered"


class InsetRole(StrEnum):
    """Semantic role of embedded material inside the main narrative."""

    FABLE = "fable"
    EMBEDDED_STORY = "embedded_story"
    EMBEDDED_EXCERPT = "embedded_excerpt"
    UNKNOWN = "unknown"


class ContainerCandidateKind(StrEnum):
    """Higher-level container kinds awaiting semantic boundary resolution."""

    INSET = "inset"


class RelationshipKind(StrEnum):
    """Relations that cannot be expressed clearly by structural nesting alone.

    Relationship confidence distinguishes exact evidence-backed links from
    conservative candidates that still need later semantic confirmation.
    """

    CONTINUES_TO = "continues_to"
    FOOTNOTE_REF = "footnote_ref"
    ATTRIBUTION_OF = "attribution_of"
    TRANSLATION_OF = "translation_of"


@dataclass(frozen=True, slots=True)
class SourceFragment:
    """Reference from logical content back to page-level source evidence."""

    page_id: str
    block_id: str
    span_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentTextSpan:
    """Logical text retaining source appearance, semantics, and provenance."""

    span_id: str
    text: str
    language: str | None
    source_typography: SourceTypography
    semantic_marks: tuple[SemanticMark, ...] = ()
    provenance: tuple[SourceFragment, ...] = ()


@dataclass(frozen=True, slots=True)
class ParagraphNode:
    """Logical prose paragraph independent of physical pagination."""

    node_id: str
    spans: tuple[DocumentTextSpan, ...]
    provenance: tuple[SourceFragment, ...] = ()


@dataclass(frozen=True, slots=True)
class HeadingNode:
    """Logical heading with semantic role separate from hierarchy level."""

    node_id: str
    spans: tuple[DocumentTextSpan, ...]
    role: HeadingRole
    level: int | None = None
    provenance: tuple[SourceFragment, ...] = ()


@dataclass(frozen=True, slots=True)
class ListItemNode:
    """One logical list item with optional source marker evidence."""

    node_id: str
    spans: tuple[DocumentTextSpan, ...]
    marker: MarkerEvidence | None = None
    ordinal: int | None = None
    provenance: tuple[SourceFragment, ...] = ()


@dataclass(frozen=True, slots=True)
class VerseLineNode:
    """One semantic line whose line boundary must survive reflow."""

    node_id: str
    spans: tuple[DocumentTextSpan, ...]
    provenance: tuple[SourceFragment, ...] = ()


@dataclass(frozen=True, slots=True)
class FootnoteNode:
    """Logical footnote body with an optional visible reference label."""

    node_id: str
    spans: tuple[DocumentTextSpan, ...]
    label: str | None = None
    provenance: tuple[SourceFragment, ...] = ()


@dataclass(frozen=True, slots=True)
class ImageNode:
    """Logical image backed by a source region and optional derived asset."""

    node_id: str
    source_region: NormalizedRegion
    asset_id: str | None = None
    provenance: tuple[SourceFragment, ...] = ()


@dataclass(frozen=True, slots=True)
class CaptionNode:
    """Logical caption associated with a figure through containment."""

    node_id: str
    spans: tuple[DocumentTextSpan, ...]
    provenance: tuple[SourceFragment, ...] = ()


@dataclass(frozen=True, slots=True)
class AttributionNode:
    """Source or attribution content related to another logical entity."""

    node_id: str
    spans: tuple[DocumentTextSpan, ...]
    provenance: tuple[SourceFragment, ...] = ()


@dataclass(frozen=True, slots=True)
class ListNode:
    """Logical list reconstructed independently of physical page boundaries."""

    node_id: str
    kind: ListKind
    items: tuple[ListItemNode, ...]
    provenance: tuple[SourceFragment, ...] = ()


@dataclass(frozen=True, slots=True)
class VerseNode:
    """Verse container preserving semantic line boundaries."""

    node_id: str
    lines: tuple[VerseLineNode, ...]
    provenance: tuple[SourceFragment, ...] = ()


@dataclass(frozen=True, slots=True)
class QuotationNode:
    """Logical quotation containing one or more flow nodes."""

    node_id: str
    children: tuple[FlowNode, ...]
    provenance: tuple[SourceFragment, ...] = ()


@dataclass(frozen=True, slots=True)
class FigureNode:
    """Logical figure containing one source-backed image and optional caption."""

    node_id: str
    image: ImageNode
    caption: CaptionNode | None = None
    provenance: tuple[SourceFragment, ...] = ()


@dataclass(frozen=True, slots=True)
class InsetNode:
    """Embedded content belonging to a distinct logical sub-work or excerpt."""

    node_id: str
    role: InsetRole
    children: tuple[FlowNode, ...]
    provenance: tuple[SourceFragment, ...] = ()


type FlowNode = (
    ParagraphNode
    | HeadingNode
    | ListNode
    | QuotationNode
    | VerseNode
    | FigureNode
    | InsetNode
    | FootnoteNode
    | AttributionNode
)


@dataclass(frozen=True, slots=True)
class ContainerResolutionCandidate:
    """Conservative evidence that a higher-level container may begin here.

    A candidate records only the evidence that can be established without
    guessing the container's full extent. A later semantic resolver may accept
    it and determine boundaries, or leave the source flow unchanged.
    """

    candidate_id: str
    kind: ContainerCandidateKind
    role: InsetRole
    source_block_ids: tuple[str, ...]
    confidence: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentRelationship:
    """Typed relation between logical entities not represented by nesting."""

    relationship_id: str
    kind: RelationshipKind
    source_id: str
    target_id: str
    confidence: float | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BookDocument:
    """Pagination-independent logical representation of ebook content."""

    nodes: tuple[FlowNode, ...]
    relationships: tuple[DocumentRelationship, ...] = ()
