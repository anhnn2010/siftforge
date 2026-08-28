"""Structured ebook-domain data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PageKind(StrEnum):
    """Supported semantic roles for a scanned book page."""

    COVER = "cover"
    TITLE = "title"
    COPYRIGHT = "copyright"
    TOC = "toc"
    CHAPTER_TITLE = "chapter_title"
    TEXT = "text"
    ILLUSTRATION = "illustration"
    BLANK = "blank"
    OTHER = "other"


class BlockType(StrEnum):
    """Supported semantic block types in normalized ebook content."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    QUOTE = "quote"
    LIST = "list"
    IMAGE = "image"
    IMAGE_CAPTION = "image_caption"
    FOOTNOTE = "footnote"
    TABLE = "table"
    PAGE_HEADER = "page_header"
    PAGE_FOOTER = "page_footer"
    PAGE_NUMBER = "page_number"
    OTHER = "other"


class FontPosture(StrEnum):
    """Explicit slant/posture state for one text span."""

    ROMAN = "roman"
    ITALIC = "italic"
    UNKNOWN = "unknown"


class FontWeight(StrEnum):
    """Explicit weight state for one text span."""

    NORMAL = "normal"
    BOLD = "bold"
    UNKNOWN = "unknown"


class VerticalPosition(StrEnum):
    """Explicit baseline relationship for one text span."""

    BASELINE = "baseline"
    SUPERSCRIPT = "superscript"
    SUBSCRIPT = "subscript"
    UNKNOWN = "unknown"


class CapsStyle(StrEnum):
    """Explicit capitalization typography independent from letter case."""

    NORMAL = "normal"
    SMALL_CAPS = "small_caps"
    UNKNOWN = "unknown"


class TextDecoration(StrEnum):
    """Decorative text treatments worth preserving in reflowable output."""

    UNDERLINE = "underline"


class TextAlignment(StrEnum):
    """Meaningful block alignment that may be retained in ebook output."""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


@dataclass(frozen=True, slots=True)
class Typography:
    """Explicit semantic typography state for a contiguous text span.

    Attributes:
        posture: Roman, italic, or explicitly unknown.
        weight: Normal, bold, or explicitly unknown.
        vertical_position: Baseline, super/subscript, or explicitly unknown.
        caps_style: Normal caps behavior, small caps, or explicitly unknown.
        decorations: Independent decorative treatments such as underline.
    """

    posture: FontPosture
    weight: FontWeight
    vertical_position: VerticalPosition
    caps_style: CapsStyle
    decorations: tuple[TextDecoration, ...] = ()


@dataclass(frozen=True, slots=True)
class TextSpan:
    """Contiguous text sharing one explicit semantic typography state."""

    text: str
    typography: Typography


@dataclass(frozen=True, slots=True)
class Block:
    """One semantic block of normalized book content."""

    type: BlockType
    content: tuple[TextSpan, ...] = ()
    language: str | None = None
    level: int | None = None
    alignment: TextAlignment | None = None

    @property
    def text(self) -> str:
        """Return plain text by concatenating all rich-text spans."""
        return "".join(span.text for span in self.content)


@dataclass(frozen=True, slots=True)
class PageContent:
    """Validated semantic content associated with one source page."""

    page_id: str
    page_kind: PageKind
    language: str | None
    printed_page_number: str | None
    blocks: tuple[Block, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Chapter:
    """Book chapter containing ordered normalized page content."""

    title: str
    pages: tuple[PageContent, ...]


@dataclass(frozen=True, slots=True)
class Book:
    """Application-level normalized representation of an ebook."""

    title: str
    language: str | None = None
    author: str | None = None
    chapters: tuple[Chapter, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)
