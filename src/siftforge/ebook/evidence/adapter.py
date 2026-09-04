"""Compatibility adapter from the v4 ebook page model to evidence models."""

from __future__ import annotations

from siftforge.ebook.evidence.models import (
    BlockRoleHint,
    HeadingRoleHint,
    PageBlockEvidence,
    PageExtraction,
    SourceTypography,
    TextSpanEvidence,
)
from siftforge.ebook.models import Block, BlockType, PageContent, TextSpan
from siftforge.extraction.models import SourceRef

_BLOCK_ROLE_HINTS: dict[BlockType, BlockRoleHint] = {
    BlockType.HEADING: BlockRoleHint.HEADING,
    BlockType.PARAGRAPH: BlockRoleHint.PARAGRAPH,
    BlockType.QUOTE: BlockRoleHint.QUOTE,
    BlockType.LIST: BlockRoleHint.LIST,
    BlockType.IMAGE: BlockRoleHint.IMAGE,
    BlockType.IMAGE_CAPTION: BlockRoleHint.CAPTION,
    BlockType.FOOTNOTE: BlockRoleHint.FOOTNOTE,
    BlockType.TABLE: BlockRoleHint.TABLE,
    BlockType.PAGE_HEADER: BlockRoleHint.PAGE_HEADER,
    BlockType.PAGE_FOOTER: BlockRoleHint.PAGE_FOOTER,
    BlockType.PAGE_NUMBER: BlockRoleHint.PAGE_NUMBER,
    BlockType.OTHER: BlockRoleHint.OTHER,
}


def page_content_to_evidence(
    page: PageContent,
    source: SourceRef,
) -> PageExtraction:
    """Convert a v4 ``PageContent`` into page-local extraction evidence.

    The adapter is intentionally conservative. It preserves current v4 text,
    typography, language, order, alignment, and heading-level information while
    leaving all newly introduced evidence fields unresolved. In particular, it
    does not infer marker types, image regions, or heading roles from text.

    Args:
        page: Existing normalized v4 ebook page content.
        source: Source reference for the physical page. The adapter requires the
            caller to provide this explicitly because ``PageContent`` does not
            carry source provenance itself.

    Returns:
        A deterministic ``PageExtraction`` representation of the same page.
    """
    blocks = tuple(
        _block_to_evidence(page.page_id, block, block_index)
        for block_index, block in enumerate(page.blocks)
    )
    return PageExtraction(
        page_id=page.page_id,
        source=source,
        page_kind_hint=page.page_kind,
        dominant_language=page.language,
        printed_page_number=page.printed_page_number,
        blocks=blocks,
        warnings=page.warnings,
    )


def _block_to_evidence(
    page_id: str,
    block: Block,
    block_index: int,
) -> PageBlockEvidence:
    """Convert one v4 block without adding new semantic interpretation."""
    block_id = _block_id(page_id, block_index)
    spans = tuple(
        _span_to_evidence(block_id, span, block.language, span_index)
        for span_index, span in enumerate(block.content)
    )
    return PageBlockEvidence(
        block_id=block_id,
        sequence_index=block_index,
        role_hint=_BLOCK_ROLE_HINTS[block.type],
        spans=spans,
        dominant_language=block.language,
        alignment=block.alignment,
        heading_level_hint=block.level,
        heading_role_hint=HeadingRoleHint.UNKNOWN,
        marker=None,
        region=None,
    )


def _span_to_evidence(
    block_id: str,
    span: TextSpan,
    block_language: str | None,
    span_index: int,
) -> TextSpanEvidence:
    """Convert one v4 span while copying only information v4 actually knows."""
    typography = span.typography
    return TextSpanEvidence(
        span_id=_span_id(block_id, span_index),
        text=span.text,
        language=block_language,
        source_typography=SourceTypography(
            posture=typography.posture,
            weight=typography.weight,
            vertical_position=typography.vertical_position,
            caps_style=typography.caps_style,
            decorations=typography.decorations,
        ),
    )


def _block_id(page_id: str, block_index: int) -> str:
    """Build a deterministic human-readable identifier for one page block."""
    return f"{page_id}:block:{block_index + 1:04d}"


def _span_id(block_id: str, span_index: int) -> str:
    """Build a deterministic identifier for one span inside a page block."""
    return f"{block_id}:span:{span_index + 1:04d}"
