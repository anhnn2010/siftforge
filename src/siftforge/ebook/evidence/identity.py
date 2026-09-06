"""Deterministic identifiers for page-local ebook extraction evidence."""

from __future__ import annotations


def build_block_id(page_id: str, block_index: int) -> str:
    """Build a deterministic human-readable identifier for one page block.

    Args:
        page_id: Stable identity of the physical source page.
        block_index: Zero-based block position in provider reading order.

    Returns:
        Stable block identifier derived only from page identity and array order.

    Raises:
        ValueError: If ``block_index`` is negative.
    """
    if block_index < 0:
        raise ValueError("block_index must be non-negative")
    return f"{page_id}:block:{block_index + 1:04d}"


def build_span_id(block_id: str, span_index: int) -> str:
    """Build a deterministic identifier for one span inside a page block.

    Args:
        block_id: Stable parent block identifier.
        span_index: Zero-based span position inside the block.

    Returns:
        Stable span identifier derived from block identity and array order.

    Raises:
        ValueError: If ``span_index`` is negative.
    """
    if span_index < 0:
        raise ValueError("span_index must be non-negative")
    return f"{block_id}:span:{span_index + 1:04d}"
