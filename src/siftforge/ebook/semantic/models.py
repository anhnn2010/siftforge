"""EPUB-ready semantic models derived from logical book structure.

These models deliberately omit source typography. Visual evidence remains in the
upstream ``BookDocument`` while this layer contains only semantics that a
reflowable ebook renderer may safely turn into markup.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from siftforge.ebook.structure import HeadingRole, InsetRole, ListKind, SemanticMark


class InlineRole(StrEnum):
    """Special inline role that affects semantic ebook markup."""

    TEXT = "text"
    FOOTNOTE_REF = "footnote_ref"


@dataclass(frozen=True, slots=True)
class SemanticInline:
    """One inline text fragment safe for semantic ebook rendering."""

    text: str
    language: str | None
    marks: tuple[SemanticMark, ...] = ()
    role: InlineRole = InlineRole.TEXT
    target_id: str | None = None
    source_span_id: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticParagraph:
    """One logical prose paragraph."""

    node_id: str
    content: tuple[SemanticInline, ...]


@dataclass(frozen=True, slots=True)
class SemanticHeading:
    """One heading or heading-like label prepared for XHTML projection."""

    node_id: str
    content: tuple[SemanticInline, ...]
    role: HeadingRole
    level: int | None


@dataclass(frozen=True, slots=True)
class SemanticListItem:
    """One list item with structural ordinal separated from readable text."""

    node_id: str
    content: tuple[SemanticInline, ...]
    ordinal: int | None = None


@dataclass(frozen=True, slots=True)
class SemanticList:
    """Ordered or unordered list prepared for semantic HTML markup."""

    node_id: str
    kind: ListKind
    items: tuple[SemanticListItem, ...]


@dataclass(frozen=True, slots=True)
class SemanticVerseLine:
    """One verse line whose boundary must survive reflow."""

    node_id: str
    content: tuple[SemanticInline, ...]


@dataclass(frozen=True, slots=True)
class SemanticVerse:
    """Verse container retaining semantic line boundaries."""

    node_id: str
    lines: tuple[SemanticVerseLine, ...]


@dataclass(frozen=True, slots=True)
class SemanticQuotation:
    """Quotation containing normal ebook flow nodes."""

    node_id: str
    children: tuple[SemanticFlowNode, ...]


@dataclass(frozen=True, slots=True)
class SemanticFigure:
    """Renderable figure asset and optional caption."""

    node_id: str
    asset_id: str
    caption: tuple[SemanticInline, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticInset:
    """Embedded sub-work or excerpt represented as an aside-like container."""

    node_id: str
    role: InsetRole
    children: tuple[SemanticFlowNode, ...]


@dataclass(frozen=True, slots=True)
class SemanticFootnote:
    """Footnote body addressable by inline note references."""

    node_id: str
    content: tuple[SemanticInline, ...]
    label: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticAttribution:
    """Attribution or source line associated with nearby content."""

    node_id: str
    content: tuple[SemanticInline, ...]


type SemanticFlowNode = (
    SemanticParagraph
    | SemanticHeading
    | SemanticList
    | SemanticVerse
    | SemanticQuotation
    | SemanticFigure
    | SemanticInset
    | SemanticFootnote
    | SemanticAttribution
)


@dataclass(frozen=True, slots=True)
class SemanticRelationship:
    """Non-rendering semantic relation retained for downstream packaging."""

    kind: str
    source_id: str
    target_id: str


@dataclass(frozen=True, slots=True)
class SemanticBookDocument:
    """Pagination-independent content ready for semantic XHTML rendering."""

    title: str
    language: str | None
    author: str | None
    nodes: tuple[SemanticFlowNode, ...]
    relationships: tuple[SemanticRelationship, ...] = ()
