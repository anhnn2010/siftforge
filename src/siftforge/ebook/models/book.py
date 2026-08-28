"""Structured ebook-domain data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class BlockType(StrEnum):
    """Supported semantic block types in normalized ebook content."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    QUOTE = "quote"
    LIST = "list"
    IMAGE = "image"
    FOOTNOTE = "footnote"
    TABLE = "table"


@dataclass(frozen=True, slots=True)
class Block:
    """One semantic block of normalized book content."""

    type: BlockType
    text: str = ""
    level: int | None = None


@dataclass(frozen=True, slots=True)
class PageContent:
    """Normalized semantic content associated with one source page."""

    page_id: str
    blocks: tuple[Block, ...]


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
