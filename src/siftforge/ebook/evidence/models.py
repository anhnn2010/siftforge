"""Page-local evidence models for ebook extraction.

These models describe what an extractor observed on one physical source page.
They intentionally avoid asserting the final pagination-independent document
structure that later book-level analysis will resolve.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from siftforge.ebook.models import (
    CapsStyle,
    FontPosture,
    FontWeight,
    PageKind,
    TextAlignment,
    TextDecoration,
    VerticalPosition,
)
from siftforge.extraction.models import SourceRef


class BlockRoleHint(StrEnum):
    """Page-local semantic role suggested by an extractor."""

    PARAGRAPH = "paragraph"
    HEADING = "heading"
    QUOTE = "quote"
    LIST = "list"
    LIST_ITEM = "list_item"
    VERSE = "verse"
    ATTRIBUTION = "attribution"
    FOOTNOTE = "footnote"
    IMAGE = "image"
    CAPTION = "caption"
    TABLE = "table"
    PAGE_HEADER = "page_header"
    PAGE_FOOTER = "page_footer"
    PAGE_NUMBER = "page_number"
    OTHER = "other"
    UNKNOWN = "unknown"


class HeadingRoleHint(StrEnum):
    """Possible heading role before book-level structural resolution."""

    CHAPTER_LABEL = "chapter_label"
    CHAPTER_TITLE = "chapter_title"
    SECTION_TITLE = "section_title"
    SUBSECTION_TITLE = "subsection_title"
    SUBTITLE = "subtitle"
    GENRE_LABEL = "genre_label"
    SCENARIO_LABEL = "scenario_label"
    SCENARIO_TITLE = "scenario_title"
    UNKNOWN = "unknown"


class MarkerKind(StrEnum):
    """Visual marker category observed before or beside content."""

    BULLET = "bullet"
    NUMERIC = "numeric"
    ALPHABETIC = "alphabetic"
    DASH = "dash"
    GRAPHIC = "graphic"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SourceTypography:
    """Visual typography observed in the source document.

    This data is evidence about glyph appearance. It does not by itself imply
    semantic EPUB markup such as ``<em>`` or ``<strong>``.
    """

    posture: FontPosture
    weight: FontWeight
    vertical_position: VerticalPosition
    caps_style: CapsStyle
    decorations: tuple[TextDecoration, ...] = ()


@dataclass(frozen=True, slots=True)
class TextSpanEvidence:
    """Contiguous source text with observed language and typography."""

    span_id: str
    text: str
    language: str | None
    source_typography: SourceTypography
    semantic_line_break_after: bool = False


@dataclass(frozen=True, slots=True)
class MarkerEvidence:
    """Visual marker evidence without asserting final list semantics."""

    kind: MarkerKind
    raw_text: str | None = None
    ordinal: int | None = None


@dataclass(frozen=True, slots=True)
class NormalizedRegion:
    """Rectangular source region using coordinates normalized to ``[0, 1]``."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class PageBlockEvidence:
    """One ordered block of evidence extracted from a physical source page."""

    block_id: str
    sequence_index: int
    role_hint: BlockRoleHint
    spans: tuple[TextSpanEvidence, ...]
    dominant_language: str | None = None
    alignment: TextAlignment | None = None
    heading_level_hint: int | None = None
    heading_role_hint: HeadingRoleHint = HeadingRoleHint.UNKNOWN
    marker: MarkerEvidence | None = None
    region: NormalizedRegion | None = None

    @property
    def text(self) -> str:
        """Return plain text by concatenating the evidence spans in order."""
        return "".join(span.text for span in self.spans)


@dataclass(frozen=True, slots=True)
class PageExtraction:
    """Structured evidence extracted from one physical source page."""

    page_id: str
    source: SourceRef
    page_kind_hint: PageKind
    dominant_language: str | None
    printed_page_number: str | None
    blocks: tuple[PageBlockEvidence, ...]
    warnings: tuple[str, ...] = ()
