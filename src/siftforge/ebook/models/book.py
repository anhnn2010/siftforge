from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class BlockType(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    QUOTE = "quote"
    LIST = "list"
    IMAGE = "image"
    FOOTNOTE = "footnote"
    TABLE = "table"


@dataclass(frozen=True, slots=True)
class Block:
    type: BlockType
    text: str = ""
    level: int | None = None


@dataclass(frozen=True, slots=True)
class PageContent:
    page_id: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True, slots=True)
class Chapter:
    title: str
    pages: tuple[PageContent, ...]


@dataclass(frozen=True, slots=True)
class Book:
    title: str
    language: str | None = None
    author: str | None = None
    chapters: tuple[Chapter, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)
